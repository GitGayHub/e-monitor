"""Real concurrent Git checkpoints, entirely inside temporary repositories."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from config_crypt import encrypt, decrypt
from mobile import checkpoint_push

class CheckpointIntegrationTests(unittest.TestCase):
    def scenario(self, conflicting=False, unknown=False):
        with tempfile.TemporaryDirectory(prefix="emonitor-git-test-") as folder:
            root=Path(folder); origin=root/"origin.git"; local=root/"local"; remote=root/"remote"
            def git(path,*args):
                result=subprocess.run(["git",*args],cwd=path,capture_output=True,check=True)
                return result.stdout.decode().strip()
            git(root,"init","--bare",str(origin));git(root,"clone",str(origin),str(local))
            git(local,"checkout","-b","main")
            for path in [local]:
                git(path,"config","user.email","audit@example.invalid");git(path,"config","user.name","Isolated audit")
            def save(path,data):
                (path/"config.json.enc").write_bytes(encrypt(json.dumps(data).encode(),"isolated-test-passphrase"))
            (local/"mobile").mkdir();(local/"mobile/app_sync.json").write_text(json.dumps({"writer":"server","searches":[{"id":"s","maxPrice":50}]}))
            (local/"state.txt").write_text("base")
            save(local,{"searches":[{"id":"s","price":50}],"settings":{"checkpoint":0}})
            git(local,"add",".");git(local,"commit","-m","base");git(local,"push","-u","origin","main")
            git(root,"clone","--branch","main",str(origin),str(remote))
            git(remote,"config","user.email","audit@example.invalid");git(remote,"config","user.name","Isolated audit")
            save(remote,{"searches":[{"id":"s","price":40}],"settings":{"checkpoint":0}})
            (remote/"mobile/app_sync.json").write_text(json.dumps({"writer":"android","searches":[{"id":"s","maxPrice":40}]}))
            if unknown:(remote/"state.txt").write_text("remote")
            git(remote,"add",".");git(remote,"commit","-m","phone edit");git(remote,"push")
            save(local,{"searches":[{"id":"s","price":30 if conflicting else 50}],"settings":{"checkpoint":1}})
            (local/"mobile/app_sync.json").write_text(json.dumps({"writer":"server","searches":[{"id":"s","maxPrice":50}],"checkpoint":1}))
            if unknown:(local/"state.txt").write_text("local")
            git(local,"add",".");git(local,"commit","-m","confirmed delivery checkpoint")
            original=git(local,"rev-parse","HEAD")
            with patch.object(checkpoint_push,"ROOT",local),patch.dict(os.environ,{"CONFIG_PASSPHRASE":"isolated-test-passphrase"}),patch.object(checkpoint_push.time,"sleep"):
                if conflicting or unknown:
                    with self.assertRaises((RuntimeError,ValueError)):checkpoint_push.push()
                    self.assertEqual(git(local,"rev-parse","HEAD"),original)
                    self.assertFalse((local/".git/rebase-merge").exists())
                else:
                    checkpoint_push.push()
                    actual=json.loads(decrypt((local/"config.json.enc").read_bytes(),"isolated-test-passphrase"))
                    self.assertEqual(actual,{"searches":[{"id":"s","price":40}],"settings":{"checkpoint":1}})
                    self.assertEqual(json.loads((local/"mobile/app_sync.json").read_text())["writer"],"android")
                    self.assertEqual(git(local,"rev-parse","HEAD"),git(local,"rev-parse","origin/main"))
    def test_independent_phone_edit_and_delivery_checkpoint_survive(self):self.scenario()
    def test_same_field_conflict_keeps_unpublished_checkpoint(self):self.scenario(conflicting=True)
    def test_unknown_state_conflict_keeps_unpublished_checkpoint(self):self.scenario(unknown=True)
