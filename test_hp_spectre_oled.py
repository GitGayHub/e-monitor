import unittest
import monitor


class HpSpectreOledTest(unittest.TestCase):
    def test_exact_seller_model_and_screen_evidence(self):
        title = monitor._normalize('HP Spectre x360 RTX4050 Laptop')
        cases = (
            ('Modellbez.: 9P2N2EA#ABD / 16-aa0779ng. Displayauflösung: 2880x1800', True),
            ('Modellbez.: 9P2N2EA#ABD / 16-aa0779ng. Displayauflösung: 1920x1200', False),
            ('Modellbez.: 9P2N2EB#ABD. Displayauflösung: 2880x1800', False),
            ('Passend für 9P2N2EA. Displayauflösung: 2880x1800', False),
            ('Modellbez.: 9P2N2EA#ABD. Displayauflösung: 2880x1800 IPS', False),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(expected, monitor._known_oled_configuration(title, monitor._normalize(body)))
        self.assertFalse(monitor._known_oled_configuration('dell xps laptop', monitor._normalize(cases[0][0])))
