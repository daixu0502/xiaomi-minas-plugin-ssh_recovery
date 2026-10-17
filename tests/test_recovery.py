import base64
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import io
import zipfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('ssh_recovery',str(ROOT/'payload/system/ssh-recovery-helper'))
spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)

def field(value):return struct.pack('>I',len(value))+value
def key(point=b'x'*32):return 'ssh-ed25519 '+base64.b64encode(field(b'ssh-ed25519')+field(point)).decode()
def digest(src):return hashlib.sha256(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'\n' for p in sorted(src.rglob('*')) if p.is_file()).encode()).hexdigest()

class PublicTests(unittest.TestCase):
    def test_fingerprint_and_newline(self):
        public,fp=m.public_key(key()+' device\r\n')
        self.assertTrue(public.endswith('ssh-recovery'));self.assertTrue(fp.startswith('SHA256:'))
    def test_no_authorized_keys_options(self):
        for value in ['command="sh" '+key(),key()+'\n'+key(),'ssh-rsa !!!!','not a key',key(b'x'*31)]:
            with self.assertRaises(m.RecoveryError):m.public_key(value)
    def test_type_mismatch(self):
        with self.assertRaises(m.RecoveryError):m.public_key(key().replace('ssh-ed25519 ','ssh-rsa ',1))
    def test_wrapped_key_bom_comments_and_missing_padding(self):
        algorithm,encoded=key().split()
        wrapped='\ufeff# exported public key\r\n'+algorithm+' '+encoded[:20]+'\r\n'+encoded[20:48]+'\r\n'+encoded[48:]+' device\r\n'
        self.assertEqual(m.public_key(wrapped),m.public_key(key()))
        self.assertEqual(m.public_key(key().rstrip('=')),m.public_key(key()))
    def test_rfc4716_public_key(self):
        encoded=key().split()[1]
        text='---- BEGIN SSH2 PUBLIC KEY ----\nComment: "exported \\\nkey"\n'+encoded[:32]+'\n'+encoded[32:]+'\n---- END SSH2 PUBLIC KEY ----\n'
        self.assertEqual(m.public_key(text),m.public_key(key()))
    def test_private_key_has_actionable_error(self):
        for algorithm in ('OPENSSH','RSA','ENCRYPTED'):
            with self.assertRaisesRegex(m.RecoveryError,'选择的是私钥'):
                m.public_key('-----BEGIN '+algorithm+' PRIVATE KEY-----\nfixture\n-----END '+algorithm+' PRIVATE KEY-----')
    def test_multiple_or_option_keys_are_still_rejected(self):
        with self.assertRaisesRegex(m.RecoveryError,'多条公钥'):m.public_key(key()+'\n'+key())
        for option in ('command="sh"','from="example.test"','restrict','no-pty'):
            with self.assertRaises(m.RecoveryError):m.public_key(option+' '+key())
        with self.assertRaises(m.RecoveryError):m.public_key(key()+'\nnot-base64!')
        with self.assertRaises(m.RecoveryError):m.public_key('---- BEGIN SSH2 PUBLIC KEY ----\n'+key().split()[1])

class RecoveryTests(unittest.TestCase):
    def test_recover_without_public_key_never_touches_key_files(self):
        before=digest(self.src)
        with patch.object(m,'unit_state',return_value={'LoadState':'loaded','ActiveState':'active'}),patch.object(m,'boot_finished',return_value=True),patch.object(m,'command',return_value=''),patch.object(self.r,'restore_host') as host,patch.object(self.r,'restore_public') as public:
            self.assertIn('未改动任何密钥文件',self.r.recover())
            host.assert_not_called();public.assert_not_called()
        self.assertFalse(self.host.exists());self.assertFalse((self.home/'.ssh').exists());self.assertFalse(self.r.host_backup.exists())
        self.assertEqual(digest(self.src),before)
    def test_generation_setting_is_off_and_does_not_generate_until_recover(self):
        self.assertFalse(self.r.settings()['generateWithoutPublicKey'])
        self.r.save_settings(True)
        self.assertTrue(self.r.settings()['generateWithoutPublicKey'])
        self.assertFalse(self.r.key.exists());self.assertFalse(self.r.generated.exists())
        with self.assertRaises(m.RecoveryError):self.r.save_settings('true')
    def test_generated_login_pair_download_once_without_source_mutation(self):
        before=digest(self.src);self.r.save_settings(True);self.host.write_bytes(b'host-identity')
        with patch.object(m,'unit_state',return_value={'LoadState':'loaded','ActiveState':'active'}),patch.object(m,'boot_finished',return_value=True),patch.object(m,'command',return_value=''):
            self.assertIn('15 分钟',self.r.recover())
        self.assertTrue(self.r.generated_info()['ready'])
        archive=base64.b64decode(self.r.download_generated())
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertEqual(set(z.namelist()),{'ssh-login.key','ssh-login.pub'})
            private=z.read('ssh-login.key').decode();public=z.read('ssh-login.pub').decode()
            self.assertEqual(m.public_key(m.private_public(private))[1],m.public_key(public)[1])
        self.assertFalse(self.r.generated.exists());self.assertTrue(self.r.key.exists())
        with self.assertRaises(m.RecoveryError):self.r.download_generated()
        self.assertEqual(digest(self.src),before)
    def test_expired_generated_private_key_is_pruned(self):
        self.r.generate_login_key()
        expiry=json.loads((self.r.generated/'meta.json').read_bytes())['expires']
        with patch.object(m.time,'time',return_value=expiry+60),patch.object(m,'STATE',self.state),patch.object(os,'geteuid',return_value=0):m.prune()
        self.assertFalse(self.r.generated.exists());self.assertTrue(self.r.key.exists())
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name);self.src=self.path/'src';self.src.mkdir();(self.src/'static').write_bytes(b'immutable')
        self.state=self.path/'state'
        for name in ('keys','host','tmp'):(self.state/name).mkdir(parents=True)
        self.home=self.path/'home';self.home.mkdir();self.host=self.path/'dropbear/key';self.host.parent.mkdir()
        self.shell_paths=(self.path/'systemd/90-normal-shell.conf',self.path/'bash.bash',self.path/'mi-shell')
        self.r=m.Recovery('u123',self.state,self.home,self.host,self.shell_paths)
        self.safe=patch.object(m,'safe');self.safe.start();self.addCleanup(self.safe.stop)
        for name,value in [('ROOT_TOOL',self.path/'restore/recover-ssh.py'),('LOGIN_BACKUP',self.path/'restore/login-authorized-keys')]:
            patcher=patch.object(m,name,value);patcher.start();self.addCleanup(patcher.stop)
    def test_status_does_not_confuse_host_identity_with_missing_login_home(self):
        self.home.rmdir();self.host.write_bytes(b'server identity')
        state=self.r.login_status()
        self.assertFalse(state['ready']);self.assertEqual(state['reason'],'home_missing')
        self.assertTrue(self.host.exists())
    def test_saved_public_key_is_not_ready_until_installed(self):
        self.r.save_public(key());self.assertFalse(self.r.login_status()['ready'])
        self.r.restore_public();self.assertTrue(self.r.login_status()['ready'])
        (self.home/'.ssh/authorized_keys').chmod(0o666)
        self.assertFalse(self.r.login_status()['ready'])
    def test_emergency_archive_contains_no_private_or_host_key(self):
        self.r.save_public(key());self.host.write_bytes(b'host-private-never-export')
        with patch.object(m,'BASE',ROOT/'payload/system'):
            # The installed boot asset uses a different filename from its source.
            asset=self.path/'asset';asset.mkdir();(asset/'ssh-recovery-boot.sh').write_bytes((ROOT/'payload/system/restore-ssh.sh').read_bytes())
            with patch.object(m,'BASE',asset):archive=base64.b64decode(self.r.emergency_bundle())
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertIn('recover-ssh.py',z.namelist());self.assertIn('recovery.pub',z.namelist())
            self.assertFalse(any('PRIVATE KEY' in z.read(n).decode(errors='ignore') for n in ['recovery.pub','manifest.json','README.txt']))
            self.assertFalse(any(b'host-private-never-export' in z.read(n) for n in z.namelist()))
    def test_boot_snapshot_does_not_replace_an_existing_authorization(self):
        auth=self.home/'.ssh/authorized_keys';auth.parent.mkdir(mode=0o700);auth.write_bytes(b'current')
        m.snapshot_login(self.home);self.assertEqual(m.LOGIN_BACKUP.read_bytes(),b'current')
        auth.write_bytes(b'revoked-and-replaced');self.assertNotEqual(auth.read_bytes(),m.LOGIN_BACKUP.read_bytes())
    def test_root_tool_preserves_shared_cgi_traversal_and_private_key_directories(self):
        base=self.path/'shared';state=base/'sshrecovery';tool=self.path/'restore/recover-ssh.py'
        with patch.object(m,'BASE',base),patch.object(m,'STATE',state),patch.object(m,'ROOT_TOOL',tool):
            m.init_recovery_state()
            self.assertEqual(base.stat().st_mode&0o777,0o755)
            for path in (state,state/'keys',state/'host',state/'tmp',tool.parent):
                self.assertEqual(path.stat().st_mode&0o777,0o700)
            base.chmod(0o700)
            m.init_recovery_state()
            self.assertEqual(base.stat().st_mode&0o777,0o755)
    def test_offline_recovery_only_queues_activation_until_host_cron_runs(self):
        import contextlib
        public=self.path/'recovery.pub';public.write_text(key())
        cron=self.path/'cron/ssh-recovery-once';cron.parent.mkdir()
        result=self.path/'restore/emergency-result.json'
        with contextlib.ExitStack() as stack:
            for name,value in [('BASE',self.path/'base'),('STATE',self.state),('PENDING_CRON',cron),('PENDING_RESULT',result)]:stack.enter_context(patch.object(m,name,value))
            stack.enter_context(patch.object(os,'geteuid',return_value=0))
            stack.enter_context(patch.object(m,'prepare_root_account',return_value=self.home))
            stack.enter_context(patch.object(m.Recovery,'restore_host',return_value='preserved'))
            run=stack.enter_context(patch.object(m,'command'))
            m.root_cli(['--local-recover','--offline','--user','u123','--public-key',str(public)])
            run.assert_not_called();self.assertEqual(json.loads(result.read_text())['state'],'pending')
            self.assertIn('--activate-pending',cron.read_text())
            stack.enter_context(patch.object(m,'repair_boot_materials'))
            stack.enter_context(patch.object(m,'boot_finished',return_value=True))
            stack.enter_context(patch.object(m,'unit_state',return_value={'ActiveState':'active'}))
            self.assertTrue(m.activate_pending()['ok']);self.assertFalse(cron.exists())
            self.assertEqual(json.loads(result.read_text())['state'],'ready')
    def test_vendor_login_shell_is_changed_without_touching_password_or_other_accounts(self):
        passwd=self.path/'passwd';passwd.write_text('root:x:0:0:root:'+str(self.home)+':/usr/sbin/mi-shell\nu123:x:1000:1000:user:/home/u123:/bin/bash\n')
        self.assertEqual(m.prepare_root_account(passwd),self.home)
        self.assertIn('root:x:0:0:root:'+str(self.home)+':/bin/sh',passwd.read_text())
        self.assertIn('u123:x:1000:1000:user:/home/u123:/bin/bash',passwd.read_text())
    def test_shell_restore_is_scoped_to_dropbear_and_keeps_vendor_binary(self):
        dropin,bash,limited=self.shell_paths
        bash.write_bytes(b'bash');bash.chmod(0o755);limited.write_bytes(b'vendor shell')
        with patch.object(m,'command',return_value='') as run:
            self.assertTrue(self.r.restore_shell());self.assertTrue(self.r.restore_shell())
        run.assert_called_once_with(['/usr/bin/systemctl','daemon-reload'])
        self.assertEqual(dropin.read_text(),'[Service]\nBindReadOnlyPaths='+str(bash)+':'+str(limited)+'\n')
        self.assertEqual(limited.read_bytes(),b'vendor shell')
    def test_different_shell_override_is_preserved(self):
        dropin,bash,limited=self.shell_paths
        bash.write_bytes(b'bash');bash.chmod(0o755);limited.write_bytes(b'vendor')
        dropin.parent.mkdir();dropin.write_text('custom config')
        with self.assertRaises(m.RecoveryError):self.r.restore_shell()
        self.assertEqual(dropin.read_text(),'custom config')
    def test_shell_reload_failure_removes_new_override(self):
        dropin,bash,limited=self.shell_paths
        bash.write_bytes(b'bash');bash.chmod(0o755);limited.write_bytes(b'vendor')
        with patch.object(m,'command',side_effect=m.RecoveryError('reload failed')):
            with self.assertRaises(m.RecoveryError):self.r.restore_shell()
        self.assertFalse(dropin.exists())
    def test_save_restore_deduplicate_preserve_other_keys(self):
        self.r.save_public(key())
        ssh=self.home/'.ssh';ssh.mkdir();auth=ssh/'authorized_keys';auth.write_text(key(b'z'*32)+'\n')
        before=digest(self.src)
        self.r.restore_public();self.r.restore_public()
        self.assertEqual(len(auth.read_text().splitlines()),2);self.assertEqual(auth.stat().st_mode&0o777,0o600)
        self.assertEqual(ssh.stat().st_mode&0o777,0o700);self.assertEqual(digest(self.src),before)
    def test_no_saved_key_does_not_touch_authorized_keys(self):
        self.assertFalse(self.r.restore_public());self.assertFalse((self.home/'.ssh').exists())
    def test_missing_root_home_is_recreated_before_restoring_public_key(self):
        self.r.save_public(key())
        self.home.rmdir()
        self.assertTrue(self.r.restore_public())
        self.assertTrue((self.home/'.ssh/authorized_keys').is_file())
        self.assertEqual(self.home.stat().st_mode&0o777,0o700)
    def test_non_directory_root_home_is_rejected(self):
        self.r.save_public(key())
        self.home.rmdir();self.home.write_text('occupied')
        with self.assertRaises(m.RecoveryError):self.r.restore_public()
    def test_host_backup_restore_does_not_overwrite_existing(self):
        self.host.write_bytes(b'host-identity');self.assertEqual(self.r.restore_host(),'preserved')
        self.host.unlink();self.assertEqual(self.r.restore_host(),'restored');self.assertEqual(self.host.read_bytes(),b'host-identity')
        self.host.write_bytes(b'new-valid-host');self.r.restore_host();self.assertEqual(self.host.read_bytes(),b'new-valid-host')
    def test_boot_check_in_progress_blocks_mutation(self):
        with patch.object(m,'unit_state',return_value={'LoadState':'loaded'}),patch.object(m,'boot_finished',return_value=False):
            with self.assertRaises(m.RecoveryError):self.r.recover()
        self.assertFalse(self.host.exists())
    def test_private_import_memory_only_and_digest_unchanged(self):
        seed=bytes(range(32));der=bytes.fromhex('302e020100300506032b657004220420')+seed
        public=subprocess.check_output(['/usr/bin/openssl','pkey','-inform','DER','-pubout','-outform','DER'],input=der)[-32:]
        pub=field(b'ssh-ed25519')+field(public)
        private=struct.pack('>II',42,42)+field(b'ssh-ed25519')+field(public)+field(seed+public)+field(b'fixture')
        pad=8-len(private)%8;private+=bytes(range(1,pad+1))
        blob=b'openssh-key-v1\0'+field(b'none')+field(b'none')+field(b'')+struct.pack('>I',1)+field(pub)+field(private)
        text='-----BEGIN OPENSSH PRIVATE KEY-----\n'+base64.b64encode(blob).decode()+'\n-----END OPENSSH PRIVATE KEY-----\n'
        before=digest(self.src);fp=self.r.save_private(text)
        self.assertTrue(fp.startswith('SHA256:'));self.assertEqual(list((self.state/'tmp').iterdir()),[])
        self.assertEqual(digest(self.src),before)
        self.assertFalse(any(b'PRIVATE KEY' in p.read_bytes() for p in self.state.rglob('*') if p.is_file()))
        bad=blob.replace(seed+public,b'a'*32+public)
        with self.assertRaises(m.RecoveryError):m.private_public('-----BEGIN OPENSSH PRIVATE KEY-----\n'+base64.b64encode(bad).decode()+'\n-----END OPENSSH PRIVATE KEY-----')
    def test_upload_invalid_private_leaves_no_files(self):
        before=list(self.state.rglob('*'))
        with self.assertRaises(m.RecoveryError):self.r.save_private('private secret')
        self.assertEqual(list(self.state.rglob('*')),before)
    def test_install_boot_when_no_previous_service_exists(self):
        assets=self.path/'assets';assets.mkdir()
        worker=(ROOT/'payload/system/restore-ssh.sh').read_bytes()
        (assets/'ssh-recovery-boot.sh').write_bytes(worker)
        paths=[self.path/'restore/worker',self.path/'cron/keep-ssh',self.path/'dropin/90-keep-ssh.conf']
        with patch.object(m,'BASE',assets),patch.object(m,'WORKER',paths[0]),patch.object(m,'CRON',paths[1]),patch.object(m,'DROPIN',paths[2]),patch.object(m,'unit_state',return_value={'LoadState':'loaded'}),patch.object(m,'command',return_value=''):
            self.r.install_boot()
        self.assertEqual(paths[0].read_bytes(),worker)
        self.assertIn('@reboot root /bin/sh /data/ssh-autostart-fix/restore-ssh.sh',paths[1].read_text())
        self.assertIn('ExecStartPost=/usr/bin/systemctl start dropbear.socket',paths[2].read_text())
    def test_existing_custom_boot_service_requires_explicit_override(self):
        assets=self.path/'assets';assets.mkdir();(assets/'ssh-recovery-boot.sh').write_bytes(b'#!/bin/sh\nexit 0\n')
        existing=self.path/'existing';existing.write_bytes(b'user-custom-code')
        with patch.object(m,'BASE',assets),patch.object(m,'WORKER',existing),patch.object(m,'CRON',self.path/'cron'),patch.object(m,'DROPIN',self.path/'dropin'),patch.object(m,'unit_state',return_value={'LoadState':'loaded'}):
            with self.assertRaises(m.RecoveryError):self.r.install_boot()
        self.assertEqual(existing.read_bytes(),b'user-custom-code')
    @contextlib.contextmanager
    def boot_fixture(self):
        assets=self.path/'boot-assets';assets.mkdir()
        (assets/'ssh-recovery-boot.sh').write_bytes((ROOT/'payload/system/restore-ssh.sh').read_bytes())
        with contextlib.ExitStack() as stack:
            for name,value in [('BASE',assets),('WORKER',self.path/'boot/restore-ssh.sh'),('CRON',self.path/'cron/keep-ssh'),('DROPIN',self.path/'dropin/90-keep-ssh.conf')]:
                stack.enter_context(patch.object(m,name,value))
            stack.enter_context(patch.object(m,'unit_state',return_value={'LoadState':'loaded'}))
            stack.enter_context(patch.object(m,'command',return_value=''))
            expected=m.boot_data()
            for path,data in expected.items():path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            yield expected
    def test_shell_upload_extra_blank_line_is_current_and_needs_no_override(self):
        with self.boot_fixture() as expected:
            m.WORKER.write_bytes(expected[m.WORKER]+b'\n')
            self.assertTrue(m.boot_status()['current']);self.assertEqual(m.boot_status()['conflicts'],[])
            self.r.install_boot()
            self.assertEqual(m.WORKER.read_bytes(),expected[m.WORKER])
    def test_optional_old_python_cli_is_not_a_boot_conflict_or_overwritten(self):
        with self.boot_fixture():
            m.ROOT_TOOL.parent.mkdir(parents=True,exist_ok=True);m.ROOT_TOOL.write_bytes(b'old emergency CLI fixture')
            self.r.install_boot()
            self.assertTrue(m.boot_status()['current'])
            self.assertEqual(m.ROOT_TOOL.read_bytes(),b'old emergency CLI fixture')
    def test_crlf_is_compatible_but_executable_change_is_a_conflict(self):
        with self.boot_fixture() as expected:
            m.CRON.write_bytes(expected[m.CRON].replace(b'\n',b'\r\n'))
            self.assertTrue(m.boot_status()['current'])
            m.WORKER.write_bytes(expected[m.WORKER]+b'echo modified-code\n')
            self.assertEqual(m.boot_status()['conflicts'],['restore-ssh.sh'])
            with self.assertRaisesRegex(m.RecoveryError,'restore-ssh.sh'):
                self.r.install_boot()
            self.assertTrue(m.WORKER.read_bytes().endswith(b'echo modified-code\n'))
    def test_partial_install_is_not_reported_as_current(self):
        with self.boot_fixture():
            m.CRON.unlink()
            state=m.boot_status();self.assertFalse(state['current']);self.assertEqual(state['conflicts'],[])
    def test_recover_restores_materials_without_old_boot_service(self):
        before=digest(self.src);self.r.save_public(key());self.r.host_backup.write_bytes(b'host-identity')
        with patch.object(m,'unit_state',return_value={'LoadState':'loaded','ActiveState':'active'}),patch.object(m,'boot_finished',return_value=True),patch.object(m,'command',return_value=''):
            self.assertIn('SSH 已开启',self.r.recover())
        self.assertEqual(self.host.read_bytes(),b'host-identity');self.assertTrue((self.home/'.ssh/authorized_keys').is_file())
        self.assertEqual(digest(self.src),before)

class PackagingTests(unittest.TestCase):
    def test_shared_dispatch_requires_separate_grant_and_matching_user(self):
        import sys
        common=ROOT/'payload/common';sys.path.insert(0,str(common/'common'))
        self.addCleanup(lambda:sys.path.remove(str(common/'common')))
        dispatcher_loader=importlib.machinery.SourceFileLoader('ssh_test_dispatcher',str(common/'minas-helper'))
        dispatcher_spec=importlib.util.spec_from_loader(dispatcher_loader.name,dispatcher_loader)
        dispatcher=importlib.util.module_from_spec(dispatcher_spec);dispatcher_loader.exec_module(dispatcher)
        runtime=dispatcher.runtime
        with patch.object(runtime,'account',side_effect=lambda u:u),patch.object(runtime,'registry',return_value={'users':{'u123':['dockermanager','taskcenter']}}):
            with self.assertRaises(ValueError):dispatcher.dispatch('sshrecovery',{'pluginUser':'u123','action':'status'},'u123')
        with patch.object(runtime,'account',side_effect=lambda u:u),patch.object(runtime,'registry',return_value={'users':{'u123':['sshrecovery']}}),patch.object(dispatcher,'load') as load:
            with self.assertRaises(ValueError):dispatcher.dispatch('sshrecovery',{'pluginUser':'u456','action':'status'},'u123')
            load.assert_not_called()
            response=dispatcher.dispatch('sshrecovery',{'pluginUser':'u123','action':'capabilities'},'u123')
            self.assertEqual(response['module'],'sshrecovery')
        self.assertEqual(response['helperVersion'],'1.1.0')
    def test_boot_code_is_original(self):
        project=ROOT.parent/'nas-root'
        if not project.exists():self.skipTest('Sibling SSH tool project unavailable')
        expected=(ROOT/'payload/system/restore-ssh.sh').read_text().strip()
        self.assertEqual((project/'tools/ssh/src/restore-ssh.sh').read_text().strip(),expected)
        for name in ('xiaomi-storage-open-ssh-wsl.sh','install-ssh-autostart-fix.sh'):
            original=(project/name).read_text()
            worker=original.split("<<'MINAS_SSH_REPAIR_SH_SOURCE'\n")[1].split('\nMINAS_SSH_REPAIR_SH_SOURCE')[0]
            self.assertEqual(worker.strip(),expected)
        self.assertNotIn('python',expected.lower())
    def test_common_copies_match(self):
        for name in ('minas-helper','component_admin.py','common/privileged_runtime.py','common/component_admin.py','common/user_state_io.py','common/telemetry_cache.py'):
            expected=(ROOT/'payload/common'/name).read_bytes().replace(b'\r\n',b'\n')
            for plugin in ('docker-manager-plugin','task-center-plugin'):
                if not (ROOT.parent/plugin).exists():self.skipTest('Sibling installer project unavailable')
                self.assertEqual(expected,(ROOT.parent/plugin/'payload/common'/name).read_bytes().replace(b'\r\n',b'\n'))
    def test_no_private_material_or_source_upload_directory(self):
        self.assertFalse(list((ROOT/'payload').rglob('id_ed25519*')))
        cgi=(ROOT/'payload/ui/sshrecovery.cgi').read_text();self.assertIn('sys.dont_write_bytecode=True',cgi)
        helper=(ROOT/'payload/system/ssh-recovery-helper').read_text()
        self.assertIn("STATE = BASE/'sshrecovery'",helper)
        self.assertNotIn('path.write_text(text)',helper)

if __name__=='__main__':unittest.main()
