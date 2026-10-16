"""Guard the actual GitHub workflow gate, not a parallel Python implementation."""
import unittest
from pathlib import Path

class WorkflowQueueTests(unittest.TestCase):
    def test_skipped_sync_completions_do_not_share_production_pending_slot(self):
        text=(Path(__file__).parent/'.github/workflows/e-monitor.yml').read_text(encoding='utf8')
        group=next(line.strip() for line in text.splitlines() if line.strip().startswith('group:'))
        expression=group.removeprefix('group: ${{').removesuffix('}}').strip()
        # Evaluate this restricted boolean/string expression from the real YAML
        # against the event sequence observed in production. No separate copy of
        # the routing condition is used as the expected implementation.
        expression=expression.replace('github.event_name','event').replace('github.event.workflow_run.conclusion','conclusion').replace('github.run_id','run_id').replace('&&',' and ').replace('||',' or ')
        def route(event,conclusion=None,run_id=1):
            return eval(expression,{'__builtins__':{},'format':lambda pattern,value:pattern.format(value)},dict(event=event,conclusion=conclusion,run_id=run_id))
        for event in ('push','schedule','workflow_dispatch'):
            self.assertEqual('e-monitor-v2',route(event))
        self.assertEqual('e-monitor-v2',route('workflow_run','success'))
        pending_group=route('push',run_id=1)
        for conclusion in ('cancelled','failure','skipped','timed_out'):
            self.assertNotEqual(pending_group,route('workflow_run',conclusion,2),conclusion)
            self.assertNotEqual(route('workflow_run',conclusion,2),route('workflow_run',conclusion,3))
        self.assertIn("if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'",text)
        self.assertIn('cancel-in-progress: false',text)
        other=(Path(__file__).parent/'.github/workflows/mobile-sync.yml').read_text(encoding='utf8')
        self.assertIn('group: e-monitor-v2',other)
        self.assertIn('cancel-in-progress: false',other)
