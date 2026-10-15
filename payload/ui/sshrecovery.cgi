#!/usr/bin/env python3
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
from urllib.parse import parse_qs
sys.dont_write_bytecode=True
UI=Path(__file__).resolve().parent
HELPER='/data/.minas-privileged/minas-helper'
def output(data,mime='application/json; charset=utf-8'):
    print('Content-Type: '+mime+'\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n',end='')
    if isinstance(data,bytes):sys.stdout.flush();sys.stdout.buffer.write(data)
    else:print(json.dumps(data,ensure_ascii=False))
try:
    action=parse_qs(os.environ.get('QUERY_STRING','')).get('action',[''])[0]
    if not action:
        name=os.environ.get('REQUEST_URI','/index.html').split('?')[0].split('/')[-1]
        allowed={'app.js':'application/javascript','client-bridge.js':'application/javascript','style.css':'text/css','palette.css':'text/css'}
        mime=allowed.get(name,'text/html')
        output((UI/(name if name in allowed else 'index.html')).read_bytes(),mime+'; charset=utf-8')
    else:
        match=re.fullmatch(r'/nas/(pool[0-9]+)/(u[0-9]+)/plugin/pluginsrc/sshrecovery/ui',str(UI))
        if not match or pwd.getpwuid(os.geteuid()).pw_name!=match[2]:raise ValueError('身份验证失败')
        if not os.path.ismount('/nas/'+match[1]):raise ValueError('存储池未就绪')
        if os.environ.get('REQUEST_METHOD')!='POST' or not os.environ.get('CONTENT_TYPE','').startswith('application/json'):raise ValueError('仅允许 JSON POST 请求')
        if action not in ('status','recover','import_public','import_private','forget_key','install_boot','save_settings','download_keys','download_emergency'):raise ValueError('未知操作')
        length=int(os.environ.get('CONTENT_LENGTH','0'))
        if not 0<length<=98304:raise ValueError('请求大小无效')
        data=json.loads(sys.stdin.buffer.read(length))
        if not isinstance(data,dict):raise ValueError('无效请求')
        data['action']=action
        data['pluginUser']=match[2]
        result=subprocess.run(['/usr/bin/sudo','-n',HELPER,'sshrecovery'],input=json.dumps(data).encode(),capture_output=True,timeout=55)
        try:response=json.loads(result.stdout)
        except ValueError:response={'ok':False,'error':'权限组件不可用，请重新安装插件'}
        output(response)
except Exception as exc:
    output({'ok':False,'error':str(exc) if isinstance(exc,ValueError) else '请求失败，请稍后重试'})
