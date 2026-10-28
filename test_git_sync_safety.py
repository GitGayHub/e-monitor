"""Never reinterpret unreadable remote configuration as an empty configuration."""
import json
import os
import tempfile
import unittest
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import config_crypt
import git_sync
import merge_state
import seen_state_merge


class GitSyncSafetyTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.local={'searches':[{'id':'local','query':'Synthetic'}],'settings':{}}
        (self.root/'config.json').write_text(json.dumps(self.local),encoding='utf8')
        (self.root/'config.json.enc').write_bytes(b'original encrypted data')
        p=patch.object(git_sync,'REPO_DIR',str(self.root));p.start();self.addCleanup(p.stop)
        p=patch.dict(os.environ,{'CONFIG_PASSPHRASE':'synthetic-only'});p.start();self.addCleanup(p.stop)

    def assertRefusedWithoutWrites(self, remote):
        before={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch.object(git_sync,'get_remote_file_content',return_value=remote), \
             patch.object(git_sync,'save_and_encrypt_config') as save:
            with self.assertRaises(ValueError):git_sync.merge_configs()
            save.assert_not_called()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_undecodable_or_missing_remote_never_overwrites_it_with_local(self):
        for remote in (b'bad',None,b''):
            with self.subTest(remote=remote):self.assertRefusedWithoutWrites(remote)

    def test_invalid_local_config_does_not_replace_it_with_remote(self):
        (self.root/'config.json').write_text('{broken',encoding='utf8')
        remote=config_crypt.encrypt(json.dumps({'searches':[]}).encode(),'synthetic-only')
        self.assertRefusedWithoutWrites(remote)

    def test_invalid_ban_collections_are_not_silently_replaced(self):
        remote={'searches':[],'banned_item_ids':{'malformed':'data'}}
        self.assertRefusedWithoutWrites(config_crypt.encrypt(json.dumps(remote).encode(),'synthetic-only'))
        self.local['global_banned_sellers']='malformed'
        (self.root/'config.json').write_text(json.dumps(self.local),encoding='utf8')
        self.assertRefusedWithoutWrites(config_crypt.encrypt(json.dumps({'searches':[]}).encode(),'synthetic-only'))

    def test_missing_passphrase_never_syncs_or_writes_config(self):
        with patch.dict(os.environ,{'CONFIG_PASSPHRASE':''}):self.assertRefusedWithoutWrites(b'bad')

    def test_failed_fetch_does_not_merge_stage_or_push_any_state(self):
        with patch.dict(os.environ,{'GITHUB_TOKEN':''}), \
             patch.object(git_sync,'git_run',return_value=SimpleNamespace(returncode=1,stderr='offline')) as git, \
             patch.object(git_sync,'merge_seen_ids') as seen,patch.object(git_sync,'merge_configs') as config:
            with self.assertRaises(RuntimeError):git_sync.main()
        git.assert_called_once_with('fetch','origin','main')
        seen.assert_not_called();config.assert_not_called()

    def test_github_token_is_passed_transiently_without_modifying_remote_url(self):
        token='synthetic-token-for-test'
        with patch.dict(os.environ,{'GITHUB_TOKEN':token},clear=False), \
             patch.object(git_sync.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            git_sync.git_run('fetch','origin','main')
        args=run.call_args.args[0]
        env=run.call_args.kwargs['env']
        self.assertNotIn(token,' '.join(args))
        count=int(env['GIT_CONFIG_COUNT'])
        keys=[env.get(f'GIT_CONFIG_KEY_{i}') for i in range(count)]
        self.assertIn('http.https://github.com/.extraheader',keys)
        value=env[f'GIT_CONFIG_VALUE_{keys.index("http.https://github.com/.extraheader")}']
        self.assertTrue(value.startswith('AUTHORIZATION: Basic '))
        self.assertNotIn(token,' '.join(args))

    def test_token_does_not_trigger_persistent_remote_url_write(self):
        with patch.dict(os.environ,{'GITHUB_TOKEN':'synthetic-token'},clear=False), \
             patch.object(git_sync,'git_run',return_value=SimpleNamespace(returncode=1,stderr='offline')) as git:
            with self.assertRaises(RuntimeError):git_sync.main()
        git.assert_called_once_with('fetch','origin','main')

    def test_failed_rebase_is_aborted_and_never_pushed(self):
        def command(*args,**kwargs):
            code=1 if args[:3]==('pull','--rebase','-X') or args[:2]==('diff','--cached') else 0
            return SimpleNamespace(returncode=code,stderr='synthetic failure')
        with patch.dict(os.environ,{'GITHUB_TOKEN':''}),patch.object(git_sync,'git_run',side_effect=command) as git, \
             patch.object(git_sync,'merge_seen_ids'),patch.object(git_sync,'merge_run_logs'),patch.object(git_sync,'merge_configs'):
            with self.assertRaises(RuntimeError):git_sync.main()
        calls=[call.args for call in git.call_args_list]
        self.assertIn(('rebase','--abort'),calls)
        self.assertFalse(any(call and call[0]=='push' for call in calls))

    def test_failed_staging_or_commit_stops_without_pushing(self):
        for fail in ('add','commit'):
            def command(*args,**kwargs):
                code=1 if args[0]==fail or args[:2]==('diff','--cached') else 0
                return SimpleNamespace(returncode=code,stderr='synthetic failure')
            with self.subTest(fail=fail),patch.dict(os.environ,{'GITHUB_TOKEN':''}), \
                 patch.object(git_sync,'git_run',side_effect=command) as git, \
                 patch.object(git_sync,'merge_seen_ids'),patch.object(git_sync,'merge_run_logs'),patch.object(git_sync,'merge_configs'):
                with self.assertRaises(RuntimeError):git_sync.main()
            self.assertFalse(any(call.args and call.args[0]=='push' for call in git.call_args_list))

    def test_unreadable_seen_stops_before_config_or_other_state_changes(self):
        with patch.dict(os.environ,{'GITHUB_TOKEN':''}), \
             patch.object(git_sync,'git_run',return_value=SimpleNamespace(returncode=0,stderr='')), \
             patch.object(git_sync,'merge_seen_ids',side_effect=ValueError('unreadable seen')) as seen, \
             patch.object(git_sync,'merge_configs') as config,patch.object(git_sync,'merge_run_logs') as logs:
            with self.assertRaises(ValueError):git_sync.main()
        seen.assert_called_once_with(validate_only=True)
        config.assert_not_called();logs.assert_not_called()

    def test_valid_remote_and_local_keep_remote_searches_and_union_bans(self):
        self.local['banned_item_ids']=['local-ban']
        (self.root/'config.json').write_text(json.dumps(self.local),encoding='utf8')
        remote={'searches':[{'id':'remote','query':'Remote'}],'banned_item_ids':['remote-ban']}
        encrypted=config_crypt.encrypt(json.dumps(remote).encode(),'synthetic-only')
        with patch.object(git_sync,'get_remote_file_content',return_value=encrypted), \
             patch.object(git_sync,'save_and_encrypt_config') as save:
            git_sync.merge_configs()
        merged=save.call_args.args[0]
        self.assertEqual(remote['searches'],merged['searches'])
        self.assertEqual({'local-ban','remote-ban'},set(merged['banned_item_ids']))

    def test_seen_merge_preserves_uncertain_and_interrupted_delivery(self):
        local={'a':{'initial':True,'deliveryPending':'initial'},
               'b':{'initial':True,'deliveryUncertain':{'final_hour':'timeout'}}}
        remote={'a':{'initial':True,'final_hour':True},
                'b':{'initial':True,'final_15m':True,'deliveryUncertain':{'final_15m':'timeout'}}}
        local_path=self.root/'seen_ids.json';local_path.write_text(json.dumps(local),encoding='utf8')
        with patch.object(git_sync,'get_remote_file_content',return_value=json.dumps(remote).encode()):
            git_sync.merge_seen_ids()
        result=json.loads(local_path.read_text(encoding='utf8'))
        self.assertTrue(result['a']['final_hour'])
        self.assertEqual('interrupted_before_confirmation',result['a']['deliveryUncertain']['initial'])
        self.assertTrue(result['b']['final_15m'])
        self.assertEqual({'final_hour':'timeout','final_15m':'timeout'},result['b']['deliveryUncertain'])

    def test_merge_state_preserves_uncertain_delivery_from_both_sides(self):
        left=self.root/'origin.json';right=self.root/'local.json'
        left.write_text(json.dumps({'a':{'initial':True,'deliveryUncertain':{'initial':'timeout'}}}),encoding='utf8')
        right.write_text(json.dumps({'a':{'final_hour':True,'deliveryPending':'final_hour'}}),encoding='utf8')
        result=merge_state.merge_json_lists(str(left),str(right))['a']
        self.assertTrue(result['initial']);self.assertTrue(result['final_hour'])
        self.assertEqual({'initial':'timeout','final_hour':'interrupted_before_confirmation'},result['deliveryUncertain'])

    def test_seen_merge_keeps_existing_insertion_order(self):
        result=seen_state_merge.merge_seen_state({'old':True,'new':True},{'new':True,'remote':True})
        self.assertEqual(['old','new','remote'],list(result))

    def test_seen_merge_supports_legacy_lists_and_is_repeatable(self):
        result=seen_state_merge.merge_seen_state(['old'],{'old':{'final_15m':True},'new':True})
        self.assertTrue(result['old']['initial']);self.assertTrue(result['old']['final_15m'])
        self.assertTrue(result['new']['initial'])
        self.assertEqual(result,seen_state_merge.merge_seen_state(result,result))

    def test_unreadable_seen_state_is_not_overwritten_with_an_empty_one(self):
        path=self.root/'seen_ids.json'
        for local,remote in ((b'{broken',b'{}'),(b'{"a":true}',b'{broken'),(b'{"a":true}',None)):
            path.write_bytes(local)
            with self.subTest(local=local,remote=remote), patch.object(git_sync,'get_remote_file_content',return_value=remote):
                with self.assertRaises(ValueError):git_sync.merge_seen_ids()
            self.assertEqual(local,path.read_bytes())

    def test_backup_seen_merge_refuses_corrupted_input(self):
        left=self.root/'origin.json';right=self.root/'local.json'
        left.write_text('{broken',encoding='utf8');right.write_text('{"a":true}',encoding='utf8')
        with self.assertRaises(ValueError):merge_state.merge_json_lists(str(left),str(right))
        self.assertEqual('{broken',left.read_text(encoding='utf8'))

    def test_launcher_stops_before_monitor_if_sync_fails(self):
        subprocess.run(['git','init','-q',str(self.root)],check=True,capture_output=True)
        source=Path(__file__).parent/'run_launcher.py'
        shutil.copy2(source,self.root/'run_launcher.py')
        (self.root/'git_sync.py').write_text('import sys\nsys.exit(7)\n',encoding='utf8')
        (self.root/'monitor.py').write_text('from pathlib import Path\nPath("monitor-started").write_text("yes")\n',encoding='utf8')
        env=os.environ.copy();env.pop('GITHUB_TOKEN',None);env['CONFIG_PASSPHRASE']='synthetic-only';env['PYTHONIOENCODING']='utf-8'
        result=subprocess.run([sys.executable,str(self.root/'run_launcher.py')],cwd=self.root,
                              env=env,capture_output=True,text=True,timeout=30)
        self.assertNotEqual(0,result.returncode)
        self.assertFalse((self.root/'monitor-started').exists())

    def test_launcher_never_starts_with_unreadable_encrypted_config(self):
        subprocess.run(['git','init','-q',str(self.root)],check=True,capture_output=True)
        for filename in ('run_launcher.py','config_crypt.py'):
            shutil.copy2(Path(__file__).parent/filename,self.root/filename)
        (self.root/'git_sync.py').write_text('import sys\nsys.exit(0)\n',encoding='utf8')
        (self.root/'monitor.py').write_text('from pathlib import Path\nPath("monitor-started").write_text("yes")\n',encoding='utf8')
        (self.root/'config.json.enc').write_bytes(b'invalid')
        saved=(self.root/'config.json').read_bytes()
        env=os.environ.copy();env.pop('GITHUB_TOKEN',None);env['CONFIG_PASSPHRASE']='synthetic-only';env['PYTHONIOENCODING']='utf-8'
        result=subprocess.run([sys.executable,str(self.root/'run_launcher.py')],cwd=self.root,
                              env=env,capture_output=True,text=True,timeout=30)
        self.assertNotEqual(0,result.returncode)
        self.assertFalse((self.root/'monitor-started').exists())
        self.assertEqual(saved,(self.root/'config.json').read_bytes())

    def test_launcher_can_start_after_successful_sync_and_valid_config(self):
        subprocess.run(['git','init','-q',str(self.root)],check=True,capture_output=True)
        for filename in ('run_launcher.py','config_crypt.py'):
            shutil.copy2(Path(__file__).parent/filename,self.root/filename)
        (self.root/'git_sync.py').write_text('import sys\nsys.exit(0)\n',encoding='utf8')
        (self.root/'monitor.py').write_text('from pathlib import Path\nPath("monitor-started").write_text("yes")\n',encoding='utf8')
        plaintext=json.dumps(self.local).encode('utf8')
        (self.root/'config.json.enc').write_bytes(config_crypt.encrypt(plaintext,'synthetic-only'))
        env=os.environ.copy();env.pop('GITHUB_TOKEN',None);env['CONFIG_PASSPHRASE']='synthetic-only';env['PYTHONIOENCODING']='utf-8'
        result=subprocess.run([sys.executable,str(self.root/'run_launcher.py')],cwd=self.root,
                              env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stderr[-500:])
        self.assertTrue((self.root/'monitor-started').exists())
        self.assertEqual(self.local,json.loads((self.root/'config.json').read_text(encoding='utf8')))

    def test_end_to_end_sync_with_isolated_local_git_origin(self):
        origin=self.root/'origin.git';seed=self.root/'seed';client=self.root/'client'
        def run(*args,cwd=None):
            return subprocess.run(args,cwd=cwd,check=True,capture_output=True)
        run('git','init','--bare','--initial-branch=main',str(origin))
        run('git','clone','-q',str(origin),str(seed))
        run('git','config','user.name','QA',cwd=seed);run('git','config','user.email','qa@example.invalid',cwd=seed)
        remote_config={'searches':[{'id':'remote','query':'Remote'}],'banned_item_ids':['remote-ban']}
        (seed/'config.json.enc').write_bytes(config_crypt.encrypt(json.dumps(remote_config).encode(),'synthetic-only'))
        (seed/'seen_ids.json').write_text(json.dumps({'remote':{'initial':True,'deliveryUncertain':{'initial':'timeout'}}}),encoding='utf8')
        run('git','add','config.json.enc','seen_ids.json',cwd=seed)
        run('git','commit','-qm','synthetic fixture',cwd=seed)
        run('git','push','-q','origin','main',cwd=seed)
        run('git','clone','-q',str(origin),str(client))
        run('git','config','user.name','QA',cwd=client);run('git','config','user.email','qa@example.invalid',cwd=client)
        (client/'config.json').write_text(json.dumps({'searches':[{'id':'local','query':'Local'}],
                                                      'banned_item_ids':['local-ban']}),encoding='utf8')
        (client/'seen_ids.json').write_text(json.dumps({'local':{'initial':True,'deliveryPending':'initial'}}),encoding='utf8')
        with patch.object(git_sync,'REPO_DIR',str(client)), \
             patch.object(git_sync,'GIT_BASE',['git','-c',f'safe.directory={client.as_posix()}']), \
             patch.dict(os.environ,{'GITHUB_TOKEN':'','CONFIG_PASSPHRASE':'synthetic-only'}):
            git_sync.main()
        saved=run('git','--git-dir',str(origin),'show','main:seen_ids.json').stdout
        seen=json.loads(saved)
        self.assertEqual('timeout',seen['remote']['deliveryUncertain']['initial'])
        self.assertEqual('interrupted_before_confirmation',seen['local']['deliveryUncertain']['initial'])
        encrypted=run('git','--git-dir',str(origin),'show','main:config.json.enc').stdout
        merged=json.loads(config_crypt.decrypt(encrypted,'synthetic-only'))
        self.assertEqual(remote_config['searches'],merged['searches'])
        self.assertEqual({'local-ban','remote-ban'},set(merged['banned_item_ids']))

