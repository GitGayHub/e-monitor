import base64
import unittest
from unittest.mock import Mock
from qa.dispatch_followup import followup


class FollowupDispatchTests(unittest.TestCase):
    def check(self,mode='normal',runs=None,dry=False):
        get=Mock(side_effect=[{'content':base64.b64encode(mode.encode()).decode()},
                              {'workflow_runs':runs or []}]);post=Mock()
        result=followup(get,post,'current',dry_run=dry)
        return result,get,post

    def test_empty_queue_dispatches_once_after_reading_current_main_mode(self):
        value,get,post=self.check(runs=[{'id':'current','path':'.github/workflows/e-monitor.yml','status':'in_progress'}])
        self.assertEqual('dispatch_requested',value['action'])
        self.assertEqual('contents/mode.txt?ref=main',get.call_args_list[0].args[0])
        post.assert_called_once_with('actions/workflows/e-monitor.yml/dispatches',{'ref':'main'})

    def test_settings_and_monitor_queue_are_never_replaced_deliberately(self):
        for path in ('e-monitor.yml','mobile-sync.yml'):
            for status in ('queued','pending','waiting','in_progress'):
                value,_,post=self.check(runs=[{'id':'another','path':'.github/workflows/'+path,'status':status}])
                self.assertEqual('already_queued',value['action']);post.assert_not_called()

    def test_statistics_stop_and_blank_mode_never_self_start_normal_monitor(self):
        for mode in ('statistics','stop',''):
            value,get,post=self.check(mode=mode)
            self.assertEqual('mode_not_normal',value['action']);self.assertEqual(1,get.call_count);post.assert_not_called()

    def test_ambiguous_dispatch_is_not_retried(self):
        get=Mock(side_effect=[{'content':base64.b64encode(b'normal').decode()},{'workflow_runs':[]}])
        post=Mock(side_effect=TimeoutError)
        with self.assertRaises(TimeoutError):followup(get,post,'current')
        self.assertEqual(1,post.call_count)

    def test_read_only_preflight_does_not_dispatch(self):
        value,_,post=self.check(dry=True)
        self.assertEqual('dispatch',value['action']);post.assert_not_called()
