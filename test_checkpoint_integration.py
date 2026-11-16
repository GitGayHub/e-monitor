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

    def test_concurrent_disable_on_one_search_and_local_update_on_another_merge_cleanly(self):
        base = {"searches": [{"id": "a", "enabled": True}, {"id": "b", "enabled": True}], "item_hashes": []}
        local = {"searches": [{"id": "a", "enabled": True}, {"id": "b", "enabled": True, "priority": 2}], "item_hashes": ["h1"]}
        remote = {"searches": [{"id": "a", "enabled": False}, {"id": "b", "enabled": True}], "item_hashes": []}
        merged = checkpoint_push.merge_config(base, local, remote)
        self.assertEqual(
            merged,
            {"searches": [{"id": "a", "enabled": False}, {"id": "b", "enabled": True, "priority": 2}], "item_hashes": ["h1"]},
        )

    def test_merge_app_sync_preserves_remote_consumed_server_edits_over_stale_checkpoint(self):
        base = {
            "writer": "server", "logicVersion": 100, "settingsRevision": "rev-1",
            "updatedAt": "2026-11-16T22:13:08+00:00",
            "searches": [{"id": "s1", "enabled": True}, {"id": "s2", "enabled": True}],
            "items": [{"itemId": "old"}],
        }
        local = {
            "writer": "server", "logicVersion": 100, "settingsRevision": "rev-1",
            "updatedAt": "2026-11-16T22:26:11+00:00",
            "searches": [{"id": "s1", "enabled": True}, {"id": "s2", "enabled": True}],
            "items": [{"itemId": "new-item"}],
        }
        remote = {
            "writer": "server", "logicVersion": 200, "settingsRevision": "rev-2",
            "updatedAt": "2026-11-16T22:23:51+00:00",
            "searches": [{"id": "s1", "enabled": False}, {"id": "s2", "enabled": True}, {"id": "redmagic_12_buy", "enabled": True}],
            "items": [{"itemId": "old"}],
        }
        merged = checkpoint_push.merge_app_sync(base, local, remote)
        self.assertEqual([s["id"] for s in merged["searches"]], ["s1", "s2", "redmagic_12_buy"])
        self.assertFalse(merged["searches"][0]["enabled"])
        self.assertEqual(merged["logicVersion"], 200)
        self.assertEqual(merged["settingsRevision"], "rev-2")
        self.assertEqual(merged["items"], [{"itemId": "new-item"}])

        pending_android = dict(remote, writer="android")
        self.assertIs(checkpoint_push.merge_app_sync(base, local, pending_android), pending_android)

    def test_merge_base_deepens_shallow_checkout_before_resolving(self):
        calls = []
        ok = subprocess.CompletedProcess([], 0, b"abc123\n", b"")
        err = subprocess.CompletedProcess([], 1, b"", b"")
        responses = iter([err, subprocess.CompletedProcess([], 0, b"", b""), ok])
        def fake_git(*args, check=True):
            calls.append(args)
            return next(responses)
        with patch.object(checkpoint_push, "git", side_effect=fake_git):
            self.assertEqual("abc123", checkpoint_push._merge_base())
        self.assertEqual([("merge-base", "HEAD", "origin/main"), ("fetch", "--deepen=25", "origin", "main"), ("merge-base", "HEAD", "origin/main")], calls)
