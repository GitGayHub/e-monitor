import unittest
import monitor


class TouchpadClickFailureTests(unittest.TestCase):
    def test_asserted_intermittent_failure_and_safe_controls(self):
        for text in ('The touchpad occasionally fails to register a click.',
                     'Trackpad fails to register a click.',
                     'Trackpad sometimes fails to register click.'):
            with self.subTest(text=text):
                self.assertTrue(monitor._is_description_blocked(text, 'laptops'))
        for text in ('The touchpad never fails to register a click.',
                     'The trackpad does not fail to register a click.',
                     'If the touchpad fails to register a click, update the driver.',
                     'The touchpad and mouse register every click.'):
            with self.subTest(text=text):
                self.assertFalse(monitor._is_description_blocked(text, 'laptops'))
