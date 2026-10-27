import unittest
import monitor


class LaptopLedStripTest(unittest.TestCase):
    def test_lid_lighting_is_not_a_display_defect(self):
        self.assertFalse(monitor._is_description_blocked('RGB Tastatur und LED Streifen auf dem Deckel.', 'laptops'))
        self.assertFalse(monitor._is_description_blocked('RGB Tastatur und LED-Streifen am Gehäuse.', 'laptops'))
        self.assertFalse(monitor._is_description_blocked('<p>RGB Tastatur und <b>LED Streifen</b> auf dem Deckel.</p>', 'laptops'))

    def test_real_damage_and_separate_screen_stripes_still_block(self):
        for text in ('LED Streifen auf dem Deckel. Das Display hat grüne Streifen.',
                     'LED Streifen auf dem Deckel ist defekt.',
                     'Das Display hat LED Streifen.', 'Streifen im Display.',
                     'LED Streifen auf dem Deckel und Streifen im Display.',
                     'LED Streifen am Gehäuse, Display hat Burn-in.'):
            with self.subTest(text=text):
                self.assertTrue(monitor._is_description_blocked(text, 'laptops'))
