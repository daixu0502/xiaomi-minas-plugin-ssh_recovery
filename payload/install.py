#!/usr/bin/env python3
"""Standard NAS registration plus a narrowly scoped root-owned SSH helper."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time

PLUGIN, VERSION = 'sshrecovery', '1.1.0'
SYSTEM = Path('/data/.minas-privileged')

def system_install(user, payload):
    host=Path('/etc/dropbear/dropbear_rsa_host_key')
    if host.exists():
        require(not host.is_symlink() and host.stat().st_uid==0 and host.stat().st_size<=65536,'主机密钥异常')
    result=subprocess.run([sys.executable,'-B',str(payload/'common/component_admin.py'),'install',
                           '--plugin',PLUGIN,'--user',user,'--payload',str(payload),'--plugin-version',VERSION],
                          capture_output=True,check=True,timeout=120)
    report=json.loads(result.stdout)
    saved=SYSTEM/'sshrecovery/host/dropbear_rsa_host_key'
    if host.is_file() and not saved.exists():atomic(saved,host.read_bytes(),0o400,(0,0))
    return report

def system_remove(user):
    subprocess.run([sys.executable,'-B',str(SYSTEM/'component_admin.py'),'remove',
                    '--plugin',PLUGIN,'--user',user],check=True,timeout=120)

def require(condition, message):
    if not condition: raise RuntimeError(message)

def read_json(path):
    result = json.loads(path.read_text())
    require(isinstance(result, dict), 'JSON 配置必须为对象：' + str(path))
    return result

def installed(user):
    home = Path('/home') / user / 'plugin' / PLUGIN
    if home.exists(): return True
    registry = Path('/data/plugin') / (user + '.list')
    return registry.exists() and bool(read_json(registry).get(PLUGIN, {}).get('install'))

def users(action):
    candidates = {p.name for p in Path('/home').glob('u*')} | {p.stem for p in Path('/data/plugin').glob('u*.list')}
    result = []
    for user in sorted(candidates):
        if not re.fullmatch('u[0-9]+', user): continue
        try: pwd.getpwnam(user)
        except KeyError: continue
        state = installed(user)
        if action == 'uninstall' and not state: continue
        if action == 'install' and not (Path('/data/plugin') / (user + '.list')).is_file(): continue
        result.append((user, 'installed' if state else 'available'))
    return result

def paths(user, action):
    require(bool(re.fullmatch('u[0-9]+', user)), '无效用户')
    account = pwd.getpwnam(user)
    home = Path('/home') / user / 'plugin' / PLUGIN
    require(not home.is_symlink(), '插件主目录不能是符号链接')
    src = Path(os.readlink(home / 'src')) if (home / 'src').is_symlink() else Path('/nas/pool0') / user / 'plugin/pluginsrc' / PLUGIN
    match = re.fullmatch('/nas/(pool[0-9]+)/' + user + '/plugin/pluginsrc/sshrecovery', str(src))
    require(bool(match), '插件源码路径异常')
    pool = Path('/nas') / match[1]
    require(os.path.ismount(pool), '存储池尚未挂载，请恢复后重试')
    require((pool / user).is_dir(), '存储池用户目录不存在')
    tmp = pool / user / 'plugin/plugintmp' / PLUGIN
    for path in (home, src, tmp): require(path.resolve() == path, '路径存在意外重定向：' + str(path))
    for name, expected in (('src', src), ('tmp', tmp)):
        link = home / name
        require(not link.exists() or link.is_symlink(), '插件目录异常：' + str(link))
        if link.is_symlink(): require(Path(os.readlink(link)) == expected, '插件链接目标不符')
    registry = Path('/data/plugin') / (user + '.list')
    require(registry.is_file() and not registry.is_symlink(), '用户插件清单不存在或异常')
    read_json(registry)
    web_root = Path(read_json(Path('/etc/config/plugin')).get('settings', {}).get('nginx_plugin', '/data/plugin/www'))
    require(web_root.is_absolute(), '网页根目录必须是绝对路径')
    web = web_root / user / PLUGIN
    require(not web.exists() or web.is_symlink(), '网页入口已被其他文件占用')
    if web.is_symlink(): require(web.resolve() == src / 'ui', '网页入口目标异常')
    for name in ('var','etc','scripts','INFO'):
        require(not (home/name).is_symlink(), '插件配置路径不能是符号链接')
    if action == 'uninstall': require(installed(user), '该用户尚未安装SSH 恢复')
    return dict(user=user, uid=account.pw_uid, gid=account.pw_gid, home=home, src=src, tmp=tmp, registry=registry, web=web)

def atomic(path, content, mode=0o644, owner=None):
    fd, name = tempfile.mkstemp(prefix='.sshrecovery-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(content); out.flush(); os.fsync(out.fileno()); os.fchmod(out.fileno(), mode)
            if owner: os.fchown(out.fileno(), *owner)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def encoded(value): return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()

def abstract(src):
    content = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '\n' for p in sorted(src.rglob('*')) if p.is_file() and not p.is_symlink())
    return hashlib.sha256(content.encode()).hexdigest()

def install(p, payload):
    home, src, tmp, registry, web = (p[k] for k in ('home', 'src', 'tmp', 'registry', 'web'))
    owner = (p['uid'], p['gid'])
    for name in ('ui', 'system', 'scripts','common'): require((payload / name).is_dir(), '安装包缺少 ' + name)
    old_registry = registry.read_bytes()
    previous_info = (home / 'INFO').read_bytes() if (home / 'INFO').is_file() else None
    new_home, new_tmp = not home.exists(), not tmp.exists()
    for directory in (home, src.parent, tmp, web.parent, Path('/data/plugin/www/icon')): directory.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.sshrecovery-new-', dir=src.parent))
    backup = Path(tempfile.mkdtemp(prefix='.sshrecovery-old-', dir=src.parent))
    previous_src, control = backup / 'src', home / 'scripts/control'
    previous_control = control.read_bytes() if control.is_file() else None
    switched, src_moved = False, False
    icon = Path('/data/plugin/www/icon/sshrecovery.icon')
    old_icon = icon.read_bytes() if icon.exists() else None
    web_existed = web.is_symlink()
    try:
        for name in ('ui',): shutil.copytree(payload / name, stage / name)
        for path in stage.rglob('*'):
            require(not path.is_symlink(), '安装包不允许符号链接')
            os.chown(path, *owner); path.chmod(0o755 if path.is_dir() or path.suffix == '.cgi' else 0o644)
        os.chown(stage, *owner); stage.chmod(0o700)
        if src.exists(): os.replace(src, previous_src); src_moved = True
        os.replace(stage, src); switched = True
        for name in ('scripts', 'var', 'etc'):
            directory = home / name
            require(not directory.is_symlink(), '插件数据目录异常')
            directory.mkdir(exist_ok=True); directory.chmod(0o700); os.chown(directory, *owner)
        atomic(control, (payload / 'scripts/control').read_bytes(), 0o755, owner)
        for name, target in (('src', src), ('tmp', tmp)):
            if not (home / name).is_symlink(): (home / name).symlink_to(target)
            os.lchown(home / name, *owner)
        for directory in (home, tmp): os.chown(directory, *owner); directory.chmod(0o700)
        now = int(time.time())
        info = dict(plugin=PLUGIN, name='SSH 恢复', id=19098, version=VERSION, tags=['tool'], timestamp=now,
                    desc='手动开启 SSH、恢复主机密钥与登录公钥', developer='Local', publisher='Local', changelog='新旧固件恢复、实际登录授权诊断与无私钥离线应急包',
                    system=False, size=sum(f.stat().st_blocks * 512 for f in src.rglob('*') if f.is_file()), port='', type='standard',
                    forceupgrade=False, ext={'admin':True}, hotplug=[], abstract=abstract(src))
        atomic(home / 'INFO', encoded(info), owner=owner)
        if not web.is_symlink(): web.symlink_to(src / 'ui')
        os.lchown(web, *owner)
        subprocess.run([sys.executable, '-B', str(payload / 'make_icon.py'), str(icon)], check=True)
        icon.chmod(0o644)
        data = read_json(registry)
        data[PLUGIN] = dict(resource={'mpk':'','icon':'','preview':None}, status='running', install=True, upgrade=False,
                            enable=True, changetime=now, icon='/icon/sshrecovery.icon', progress='100', frontend=read_json(src / 'ui/config'),
                            info={k:v for k,v in info.items() if k!='abstract'}, online=True)
        st=registry.stat(); atomic(registry, encoded(data), st.st_mode & 0o777, (st.st_uid, st.st_gid))
        env = dict(os.environ, PLUG_USER=p['user'], PLUG_NAME=PLUGIN, PLUG_SRC_DIR=str(src), PLUG_HOME_DIR=str(home), PLUG_TMP_DIR=str(tmp), PLUG_STATUS='unverified')
        check = subprocess.run(['/usr/bin/plugin.sh', 'verify'], env=env, capture_output=True, timeout=60)
        require(check.returncode == 0, '系统源码校验未通过，正在回退安装')
        report=system_install(p['user'],payload)
        print('公共权限组件：'+report['helperVersion']+'；升级回退副本：'+report['backup'])
        print('SSH 恢复 1.1.0 已安装：' + p['user'] + '；未改动开机修复服务，未预置登录公钥。')
    except BaseException:
        st=registry.stat(); atomic(registry,old_registry,st.st_mode & 0o777,(st.st_uid,st.st_gid))
        if not web_existed and web.is_symlink(): web.unlink()
        if switched and src.exists(): shutil.rmtree(src)
        if src_moved and previous_src.exists(): os.replace(previous_src, src)
        if new_home: shutil.rmtree(home)
        else:
            if previous_info is not None: atomic(home/'INFO',previous_info,owner=owner)
            if previous_control is not None: atomic(control,previous_control,0o755,owner)
        if new_tmp and tmp.exists(): shutil.rmtree(tmp)
        if old_icon is not None: atomic(icon,old_icon)
        elif icon.exists(): icon.unlink()
        raise
    finally:
        if stage.exists(): shutil.rmtree(stage)
        if backup.exists(): shutil.rmtree(backup)

def uninstall(p):
    home, src, tmp, registry, web = (p[k] for k in ('home', 'src', 'tmp', 'registry', 'web'))
    backup = Path('/data/.sshrecovery-backups') / p['user'] / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid()))
    backup.mkdir(parents=True, mode=0o700)
    for name in ('var','INFO'):
        path=home/name
        require(not path.is_symlink(), '备份对象不能为符号链接')
        if path.is_dir(): shutil.copytree(path,backup/name,symlinks=True)
        elif path.is_file(): shutil.copy2(path,backup/name)
    shutil.copy2(registry,backup/'plugin-list.json')
    # Refuse module removal before touching the UI, e.g. if another privileged
    # operation is active. A failed permission transaction leaves the UI intact.
    system_remove(p['user'])
    data=read_json(registry);data.pop(PLUGIN,None);st=registry.stat()
    atomic(registry,encoded(data),st.st_mode & 0o777,(st.st_uid,st.st_gid))
    if web.is_symlink(): web.unlink()
    for path in (src,tmp,home):
        require(path.resolve()==path and path.name==PLUGIN, '删除目标发生变化，已停止')
        if path.exists(): shutil.rmtree(path)
    if not any(state=='installed' for _,state in users('uninstall')): Path('/data/plugin/www/icon/sshrecovery.icon').unlink(missing_ok=True)
    print('SSH 恢复已卸载。插件配置备份：' + str(backup))

def main(args):
    require(os.geteuid()==0 and Path('/etc/config/plugin').is_file(), '请通过安装脚本以 root 连接小米智能存储')
    require(bool(args), '缺少操作')
    action=args[0]
    if action in ('--scan','--check'):
        require(len(args)>=3 and args[1]==PLUGIN and args[2] in ('install','uninstall'), '扫描参数无效')
        if action=='--scan':
            for user,state in users(args[2]): print(user+'\t'+state)
        else:
            for user in args[3:]: paths(user,args[2])
        return
    require(action in ('install','uninstall') and len(args)==2, '操作参数无效')
    require(bool(re.fullmatch('u[0-9]+',args[1])), '无效用户')
    with contextlib.ExitStack() as stack:
        for path in ('/data/plugin/.local-plugin-installer.lock', '/data/plugin/.'+args[1]+'.plugins.lock'):
            lock=stack.enter_context(open(path,'a'));fcntl.flock(lock,fcntl.LOCK_EX)
        p=paths(args[1],action)
        if action=='install': install(p,Path(__file__).resolve().parent)
        else: uninstall(p)

if __name__=='__main__':
    try: main(sys.argv[1:])
    except Exception as exc:
        print('[错误] '+str(exc),file=sys.stderr);sys.exit(1)
