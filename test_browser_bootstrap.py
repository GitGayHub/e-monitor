import subprocess
import unittest
from unittest.mock import patch

from qa import prepare_html_browser as browser


class BrowserBootstrapTests(unittest.TestCase):
    def test_working_render_does_not_touch_system_packages(self):
        with patch.object(browser, 'stage', side_effect=[(0, ''), (0, '')]) as stage:
            self.assertEqual(0, browser.prepare())
        self.assertEqual(2, stage.call_count)
        self.assertIn('--only-shell', stage.call_args_list[0].args[1])

    def test_download_failure_does_not_run_apt_or_claim_success(self):
        with patch.object(browser, 'stage', return_value=(1, 'download unavailable')) as stage:
            self.assertEqual(1, browser.prepare())
        self.assertEqual(1, stage.call_count)

    def test_missing_libraries_are_installed_once_then_render_is_rechecked(self):
        with patch.object(browser.sys, 'platform', 'linux'), \
             patch.object(browser, 'stage', side_effect=[(0, ''), (1, 'error while loading shared libraries'),
                                                        (0, ''), (0, '')]) as stage:
            self.assertEqual(0, browser.prepare())
        self.assertIn('install-deps', stage.call_args_list[2].args[1])
        self.assertEqual(browser.SMOKE, stage.call_args_list[3].args[1][-1])

    def test_other_browser_failures_do_not_trigger_package_installation(self):
        with patch.object(browser, 'stage', side_effect=[(0, ''), (1, 'browser crashed')]) as stage:
            self.assertEqual(1, browser.prepare())
        self.assertEqual(2, stage.call_count)

    def test_failed_dependency_installation_keeps_browser_unavailable(self):
        with patch.object(browser.sys, 'platform', 'linux'), \
             patch.object(browser, 'stage', side_effect=[(0, ''), (1, 'Host system is missing dependencies'),
                                                        (124, 'timed out')]) as stage:
            self.assertEqual(1, browser.prepare())
        self.assertEqual(3, stage.call_count)

    def test_successful_package_installation_is_not_successful_rendering(self):
        with patch.object(browser.sys, 'platform', 'linux'), \
             patch.object(browser, 'stage', side_effect=[(0, ''), (1, 'cannot open shared object file'),
                                                        (0, ''), (1, 'still unavailable')]):
            self.assertEqual(1, browser.prepare())

    def test_linux_timeout_targets_the_process_group(self):
        with patch.object(browser.sys, 'platform', 'linux'), \
             patch.object(browser.subprocess, 'run', return_value=subprocess.CompletedProcess([], 124, '')) as run:
            self.assertEqual(124, browser.stage('bounded', ['python', 'installer'], 60)[0])
        self.assertEqual(['timeout', '--kill-after=5s', '60s', 'python', 'installer'], run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
