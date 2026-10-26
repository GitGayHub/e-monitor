import unittest
import monitor


class OledBurnNegationTest(unittest.TestCase):
    def test_denial_does_not_hide_other_or_affirmed_damage(self):
        for text, blocked in (
            ('There is no OLED burn-in.', False),
            ('without AMOLED burn in', False),
            ('no OLED burn-in, but burn-in on screen', True),
            ('not without OLED burn-in', True),
            ('OLED burn-in present', True),
            ('no OLED burn-in. Screen cracked', True),
        ):
            with self.subTest(text=text):
                self.assertEqual(blocked, monitor._is_description_blocked(text, 'laptops'))
