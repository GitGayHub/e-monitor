import unittest

import monitor


class SoldIphoneOct23Tests(unittest.TestCase):
    """Browser-read sold iPhone 17 Pro Max listings, 23 October 2026."""
    q = "iphone 17 pro max"

    def test_model_ram_next_to_storage_is_not_wrong_storage(self):
        # 377582903538 sold for 800 EUR and was never offered by the bot.
        title = monitor._normalize('Apple iPhone 17 Pro Max 256GB Silber 6,9" 5G ohne Simlock iOS 12GB')
        self.assertTrue(monitor._matches_phone_query_model(title, self.q))
        self.assertFalse(monitor._phone_specifications_match("apple iphone 17 pro max 12gb", "", self.q))
        self.assertFalse(monitor._phone_specifications_match("apple iphone 17 pro max 256gb 8gb", "", self.q))

    def test_promax_written_together(self):
        search = {"query": self.q, "filters": {"category": "phones"}}
        self.assertTrue(monitor._intent_prelim_matches_title(monitor._normalize("Apple iphone 17 ProMax 512GB Blau MFYU4ZD/A"), search))
        self.assertFalse(monitor._matches_phone_query_model(monitor._normalize("Apple iphone 16 ProMax 512GB Blau"), self.q))

    def test_battery_health_before_accessory_package(self):
        self.assertFalse(monitor._is_phone_accessory_title(monitor._normalize("Apple iPhone 17 Pro Max 512 GB Tiefblau / Blau 97 % Akku OVP + Zubehörpaket")))
        self.assertTrue(monitor._is_phone_accessory_title(monitor._normalize("Akku für iPhone 17 Pro Max + Werkzeug")))

    def test_generated_chip_name_next_to_own_12gb_ram(self):
        self.assertTrue(monitor._phone_specifications_match("iphone 17 pro max 256gb", "256GB Speicherkapazität und 12GB RAM, ermöglicht durch den leistungsstarken Apple A17 Pro Chipsatz", self.q))
        self.assertFalse(monitor._phone_specifications_match("iphone 17 pro max 256gb", "8GB RAM, ermöglicht durch den leistungsstarken Apple A17 Pro Chipsatz", self.q))
        self.assertFalse(monitor._phone_specifications_match("iphone 17 pro max 256gb", "mit einem leistungsstarken Apple A17 Pro Chipsatz", self.q))

    def test_off_platform_messenger_contact(self):
        for body in ("Contact me whasapp 48 453371795", "please ask in a message Whapp. 453371795", "Schreib mir auf WhatsApp: +49 170 1234567"):
            self.assertTrue(monitor._description_off_platform_contact(f"<html><body>{body}</body></html>"), body)
        for body in ("Keine WhatsApp Anfragen bitte.", "Rechnung vom 17.10.2026, Versand mit DHL 12345678 Sendungsnummer", "Telegram-Gruppe nicht vorhanden"):
            self.assertFalse(monitor._description_off_platform_contact(f"<html><body>{body}</body></html>"), body)


if __name__ == "__main__":
    unittest.main()
