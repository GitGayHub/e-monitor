import json, subprocess, sys, tempfile, types
from pathlib import Path
import git_sync
from mobile import checkpoint_push as checkpoint

import os,unittest
from pathlib import Path
from unittest.mock import patch
import config_crypt as c
class ConfigPolicyTests(unittest.TestCase):
 def setUp(self):
  self.plain=b'{"searches":[{"id":"synthetic"}]}'
  self.password='test-only';self.env=patch.dict(os.environ,{'CONFIG_REQUIRE_AUTHENTICATED':''});self.env.start();self.addCleanup(self.env.stop)
 def test_legacy_still_roundtrips_before_cutover(self):
  old=c.encrypt(self.plain,self.password);new=c.encrypt_config(self.plain,self.password,[old]);self.assertFalse(new.startswith(c.AUTH_MAGIC));self.assertEqual(self.plain,c.decrypt_config(new,self.password))
 def test_authenticated_previous_version_is_preserved(self):
  legacy=c.encrypt(self.plain,self.password);v2=c.encrypt_authenticated(self.plain,self.password)
  for previous in ([v2],[legacy,v2,legacy]):
   with self.subTest(previous=len(previous)):
    new=c.encrypt_config(self.plain,self.password,previous);self.assertTrue(new.startswith(c.AUTH_MAGIC));self.assertEqual(self.plain,c.decrypt_config(new,self.password))
 def test_authenticated_corruption_or_wrong_password_stops_before_write(self):
  v2=c.encrypt_authenticated(self.plain,self.password);bad=bytearray(v2);bad[-1]^=1
  for previous,pw in ((bytes(bad),self.password),(v2,'wrong')):
   with self.subTest(password=pw),self.assertRaises(ValueError):c.encrypt_config(self.plain,pw,[previous])
 def test_strict_external_policy_rejects_legacy_and_downgrade(self):
  v2=c.encrypt_authenticated(self.plain,self.password);old=c.encrypt(self.plain,self.password)
  with patch.dict(os.environ,{'CONFIG_REQUIRE_AUTHENTICATED':'true'}):
   self.assertEqual(self.plain,c.decrypt_config(v2,self.password))
   for bad in (old,v2[len(c.AUTH_MAGIC):],bytes([v2[0]^1])+v2[1:]):
    with self.assertRaises(ValueError):c.decrypt_config(bad,self.password)
   with self.assertRaises(ValueError):c.encrypt_config(self.plain,self.password,[old])
   self.assertTrue(c.encrypt_config(self.plain,self.password).startswith(c.AUTH_MAGIC))
 def test_unknown_policy_fails_closed_for_both_read_and_write(self):
  old=c.encrypt(self.plain,self.password)
  with patch.dict(os.environ,{'CONFIG_REQUIRE_AUTHENTICATED':'enabled_typo'}):
   with self.assertRaises(ValueError):c.decrypt_config(old,self.password)
   with self.assertRaises(ValueError):c.encrypt_config(self.plain,self.password,[old])
 def test_generic_outbox_encryption_remains_legacy(self):
  with patch.dict(os.environ,{'CONFIG_REQUIRE_AUTHENTICATED':'true'}):
   ciphertext=c.encrypt(self.plain,self.password);self.assertFalse(ciphertext.startswith(c.AUTH_MAGIC));self.assertEqual(self.plain,c.decrypt(ciphertext,self.password))


class Integrations(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='crypto-policy-integration-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.key='test-only';self.env=patch.dict(os.environ,{'CONFIG_REQUIRE_AUTHENTICATED':'','CONFIG_PASSPHRASE':self.key});self.env.start();self.addCleanup(self.env.stop)
  self.doc={'searches':[{'id':'synthetic','query':'sample'}],'banned_item_ids':['synthetic-ban']};self.raw=json.dumps(self.doc).encode()
 def test_cli_preserves_v2_and_rejects_downgrade_without_truncating_output(self):
  plain=self.root/'plain.json';enc=self.root/'config.enc';plain.write_bytes(self.raw);enc.write_bytes(c.encrypt_authenticated(self.raw,self.key))
  script=Path(c.__file__);args=[sys.executable,str(script),'encrypt',str(plain),str(enc)]
  self.assertEqual(0,subprocess.run(args,capture_output=True).returncode);self.assertTrue(enc.read_bytes().startswith(c.AUTH_MAGIC))
  enc.write_bytes(c.encrypt(self.raw,self.key));before=enc.read_bytes()
  with patch.dict(os.environ,{'CONFIG_REQUIRE_AUTHENTICATED':'1'}):
   self.assertNotEqual(0,subprocess.run(args,capture_output=True).returncode)
  self.assertEqual(before,enc.read_bytes())
 def test_sync_preserves_v2_and_never_replaces_searches_or_bans(self):
  self.enterContext(patch.object(git_sync,'REPO_DIR',str(self.root))); local={'searches':[{'id':'local'}],'banned_item_ids':['local-ban']}
  (self.root/'config.json').write_text(json.dumps(local));(self.root/'config.json.enc').write_bytes(c.encrypt(json.dumps(local).encode(),self.key))
  remote=c.encrypt_authenticated(self.raw,self.key)
  with patch.object(git_sync,'get_remote_file_content',return_value=remote):git_sync.merge_configs()
  saved=(self.root/'config.json.enc').read_bytes();self.assertTrue(saved.startswith(c.AUTH_MAGIC));merged=json.loads(c.decrypt(saved,self.key,require_authenticated=True))
  self.assertEqual(self.doc['searches'],merged['searches']);self.assertEqual({'local-ban','synthetic-ban'},set(merged['banned_item_ids']))
 def test_sync_auth_error_does_not_change_files(self):
  self.enterContext(patch.object(git_sync,'REPO_DIR',str(self.root))); plain=self.root/'config.json';enc=self.root/'config.json.enc';plain.write_bytes(self.raw);enc.write_bytes(c.encrypt_authenticated(self.raw,self.key));old=(plain.read_bytes(),enc.read_bytes())
  with patch.dict(os.environ,{'CONFIG_REQUIRE_AUTHENTICATED':'1'}),patch.object(git_sync,'get_remote_file_content',return_value=c.encrypt(self.raw,self.key)):
   with self.assertRaises(ValueError):git_sync.merge_configs()
  self.assertEqual(old,(plain.read_bytes(),enc.read_bytes()))
 def test_sync_corrupt_v2_stops_before_plaintext_or_ciphertext_change(self):
  self.enterContext(patch.object(git_sync,'REPO_DIR',str(self.root)))
  plain=self.root/'config.json';enc=self.root/'config.json.enc';plain.write_bytes(self.raw)
  corrupt=bytearray(c.encrypt_authenticated(self.raw,self.key));corrupt[-1]^=1;enc.write_bytes(bytes(corrupt))
  old=(plain.read_bytes(),enc.read_bytes())
  with patch.object(git_sync,'get_remote_file_content',return_value=c.encrypt(self.raw,self.key)):
   with self.assertRaises(ValueError):git_sync.merge_configs()
  self.assertEqual(old,(plain.read_bytes(),enc.read_bytes()))
 def test_checkpoint_conflict_does_not_downgrade_v2_and_keeps_both_changes(self):
  self.enterContext(patch.object(checkpoint,'ROOT',self.root))
  base={'searches':[{'id':'synthetic'}],'left':0,'right':0};local={**base,'left':1};remote={**base,'right':2}
  versions=[c.encrypt(json.dumps(base).encode(),self.key),c.encrypt(json.dumps(local).encode(),self.key),c.encrypt_authenticated(json.dumps(remote).encode(),self.key)]
  manifests=[b'{"writer":"server"}']*3;push_count=[0]
  def command(*args,check=True):
   if args[0]=='push':push_count[0]+=1;return types.SimpleNamespace(returncode=int(push_count[0]==1),stdout=b'')
   if args[0]=='merge-base':return types.SimpleNamespace(returncode=0,stdout=b'BASE')
   if args[0]=='show':
    rev,path=args[1].split(':',1);index={'BASE':0,'HEAD':1,'origin/main':2}[rev]
    return types.SimpleNamespace(returncode=0,stdout=(versions if path.endswith('.enc') else manifests)[index])
   if args[0]=='rebase' and args[1]=='origin/main':return types.SimpleNamespace(returncode=1,stdout=b'')
   if args[0]=='diff':return types.SimpleNamespace(returncode=0,stdout=b'config.json.enc\n')
   return types.SimpleNamespace(returncode=0,stdout=b'')
  with patch.object(checkpoint,'git',side_effect=command),patch.object(checkpoint.time,'sleep'):checkpoint.push()
  result=(self.root/'config.json.enc').read_bytes();self.assertTrue(result.startswith(c.AUTH_MAGIC));merged=json.loads(c.decrypt(result,self.key,require_authenticated=True));self.assertEqual((1,2),(merged['left'],merged['right']))


if __name__=='__main__':unittest.main(verbosity=2)
