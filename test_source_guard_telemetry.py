"""Synthetic checks for privacy-preserving description-source diagnostics."""
import unittest
from unittest.mock import patch

import monitor


class SourceGuardTelemetryTests(unittest.TestCase):
    def test_source_guard_reasons_are_logged_without_item_identity(self):
        reasons = (
            'seller_description_untrusted_url', 'seller_description_untrusted_response',
            'seller_description_untrusted_redirect', 'seller_description_redirect_limit',
            'http_source_verified', 'browser_untrusted_item_page',
            'browser_untrusted_description_page', 'browser_description_page_changed',
            'browser_untrusted_description_frame', 'browser_description_frame_changed',
            'browser_source_verified_link', 'browser_source_verified_frame',
        )
        with patch.object(monitor.logger, 'info') as info:
            for reason in reasons:
                monitor._details_event('private-test-item-id', reason)
        self.assertEqual(len(reasons), info.call_count)
        for call, reason in zip(info.call_args_list, reasons):
            self.assertIn('SOURCE_GUARD', call.args[0])
            self.assertEqual(reason, call.args[1])
            self.assertNotIn('private-test-item-id', repr(call))

    def test_unrelated_details_events_do_not_emit_source_guard_logs(self):
        with patch.object(monitor.logger, 'info') as info:
            monitor._details_event('private-test-item-id', 'html_network')
        info.assert_not_called()
