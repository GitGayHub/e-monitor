import json
import tempfile
import unittest
from pathlib import Path
from config_manager import ConfigManager
from mobile.runtime_status import publish, application_failure
import monitor


class RuntimeStatusTests(unittest.TestCase):
    def test_declared_hardware_agrees_with_known_phone_model(self):
        for generation in (15, 16, 17):
            query = f"iphone {generation} pro max"
            self.assertFalse(monitor._phone_specifications_match(f"Apple {query} 128GB", "", query))
            self.assertTrue(monitor._phone_specifications_match(f"Apple {query} 12GB RAM 256GB mit 128GB USB Stick", "", query))
        self.assertTrue(monitor._phone_model_aspect_matches("A3526", "iphone 17 pro max"))
        self.assertFalse(monitor._phone_model_aspect_matches("A3106", "iphone 17 pro max"))
        self.assertFalse(monitor._phone_model_aspect_matches("Apple iPhone 15 Pro Max", "iphone 17 pro max"))
        self.assertTrue(monitor._phone_specifications_match("iPhone 17 Pro Max 2TB", "Apple A19 Pro Chipsatz", "iphone 17 pro max"))
        self.assertFalse(monitor._phone_specifications_match("iPhone 17 Pro Max 256GB", "Apple A17 Pro Chipsatz", "iphone 17 pro max"))
    def test_only_active_configuration_is_acknowledged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runtime_status.json"
            active = {"mobile_settings_revision": "old", "searches": [{"enabled": True}], "settings": {}}
            first = publish(active, 123, "ok", path=path)
            failed = application_failure("new settings rejected", path)
            self.assertEqual(failed["settingsRevision"], "old")
            self.assertEqual(failed["appliedAt"], first["appliedAt"])
            self.assertEqual(failed["lastSuccessfulRun"], first["lastSuccessfulRun"])
            active["mobile_settings_revision"] = "new"
            loaded = publish(active, 124, "running", path=path)
            self.assertEqual(loaded["settingsRevision"], "new")
            self.assertEqual(loaded["lastSuccessfulRun"], first["lastSuccessfulRun"])
            self.assertEqual(publish(active, 124, "ok", path=path)["appliedAt"], loaded["appliedAt"])

    def test_bad_reload_keeps_last_working_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps({"searches": [{"id": "saved", "query": "Pixel 5"}]}), encoding="utf-8")
            manager = ConfigManager(str(path))
            path.write_text("{invalid", encoding="utf-8")
            self.assertFalse(manager.load())
            self.assertEqual(manager.get_searches()[0]["id"], "saved")
            with self.assertRaises(ValueError):
                ConfigManager(str(path))

    def test_numbers_outside_device_model_cannot_match_iphone_generation(self):
        query = monitor._normalize("iPhone 17 Pro Max")
        for title in ("Apple iPhone 12 Pro Max 17 cm 6.7 Zoll", "Apple iPhone 15 Pro Max iOS 17.7", "Apple iPhone 15 Pro Max A17 Pro", "Apple iPhone Xs Max 256 GB in iPhone 17 Pro Max Cosmic Orange Style OVP TOP!", "Premium Android Smartphone in iPhone 17 Pro Max Design 2TB 6,9 Zoll ohne Simlock"):
            self.assertFalse(monitor._matches_phone_query_model(monitor._normalize(title), query), title)
        self.assertTrue(monitor._matches_phone_query_model(monitor._normalize("Apple iPhone 17 Pro Max 256GB"), query))
        self.assertFalse(monitor._matches_phone_query_model(monitor._normalize("XS max New Converter to iPhone 17 Pro max 265GB 100%"), query))
        search = {"query": "iPhone 17 Pro Max", "filters": {"category": "phones"}}
        item = {"title": "Apple iPhone 17 Pro Max 256GB"}
        self.assertFalse(monitor._details_match_contract(item, search, {"title": item["title"], "description": "Es handelt sich NICHT um ein originales Apple iPhone. Nachbau/Replica."}))
        self.assertFalse(monitor._details_match_contract(item, search, {"title": item["title"], "description": "Achtung Umbau"}))
        self.assertFalse(monitor._is_phone_accessory_title(monitor._normalize("Apple Iphone 17 Pro Max 256GB Cosmic Orange OVP ink. Rhinoshield Clear Case")))
        self.assertTrue(monitor._is_phone_accessory_title(monitor._normalize("Rhinoshield Clear Case inklusive Kabel für iPhone 17 Pro Max")))
        exchange = "Das iPhone ist nagelneu und wurde nicht benutzt. Es handelt sich um ein originales Austauschgerät direkt von Apple, da mein vorheriges iPhone einen Defekt hatte und von Apple ersetzt wurde."
        self.assertFalse(monitor._is_description_blocked(exchange, "phones"))
        self.assertTrue(monitor._is_description_blocked(exchange + " Das angebotene Gerät hat einen Displaybruch.", "phones"))
        original = "Das Display ist kratzerfrei und ohne Einbrennungen. Das Gerät wurde nie repariert und es wurden keine Teile ausgetauscht."
        self.assertFalse(monitor._is_description_blocked(original, "phones"))
        self.assertFalse(monitor._is_description_blocked("Display wurde noch nie repariert.", "phones"))
        self.assertTrue(monitor._is_description_blocked(original + " Das Display wurde ersetzt.", "phones"))
        protector = "Auf dem Bild ist nur das Panzerglas kaputt unter dem Glas ist nichts kaputt."
        self.assertFalse(monitor._is_description_blocked(protector, "phones"))
        self.assertTrue(monitor._is_description_blocked(protector + " Das Display ist kaputt.", "phones"))
        self.assertTrue(monitor._is_description_blocked("Kein Defekt am Display. Der SIM-Leser ist defekt.", "phones"))

    def test_independently_read_sony_bundle_is_a_device(self):
        # 820202936472: headphones, Sony case, cable and original box in full description.
        title = monitor._normalize("Sony ULT WEAR WH-ULT900N Over-Ear Bluetooth Kopfhörer ANC Schwarz Etui & Kabel")
        self.assertTrue(monitor._matches_category_query(title, "headphones", "sony ult wear"))
        self.assertFalse(monitor._is_category_blocked_title(title, "headphones", "sony ult wear"))
        details = {"title": title, "localizedAspects": [{"name": "Produktart", "value": "Kopfbügel"}, {"name": "Besonderheiten", "value": "Abnehmbares Kabel"}]}
        self.assertFalse(monitor._is_details_blocked(details, {"query": "sony ult wear", "filters": {"category": "headphones"}}))
        self.assertFalse(monitor._is_device_bundle(monitor._normalize("Case für Sony ULT Wear Kopfhörer & Kabel"), "headphones"))
        self.assertTrue(monitor._is_category_blocked_title(monitor._normalize("Sony ULT WEAR Kopfhörer Gelenk defekt mit Kabel"), "headphones", "sony ult wear"))
        self.assertTrue(monitor._is_description_blocked("Funktioniert, aber die Halterung ist kaputt.", "headphones"))
        self.assertFalse(monitor._is_category_blocked_title(monitor._normalize("Sony ULT Wear Bluetooth-Kopfhörer schwarz Headset Kopfbügel Over-Ear faltbar ANC"), "headphones", "sony ult wear"))
        self.assertFalse(monitor._is_description_blocked("Neu ungeöffneter Verpackung. Rücknahme, Wandlung, Tausch oder Preisminderung ist ausgeschlossen.", "headphones"))
        self.assertTrue(monitor._is_description_blocked("Tausche meine Kopfhörer gegen ein Handy. Rücknahme ist ausgeschlossen.", "headphones"))
