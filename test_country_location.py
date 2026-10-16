import unittest
import monitor

class CountryLocationTests(unittest.TestCase):
    def test_pickup_map_code_between_city_and_postal_code(self):
        for location,expected in [('Brand-Erbisdorf DE 09618','DE'),('Brand-Erbisdorf DE09618','DE'),('London GB SW1A','GB'),('London UK SW1A','GB'),('Brand-Erbisdorf, Deutschland','DE'),('Berlin, DE','DE'),('de','DE'),('Val de Loire, France','FR'),('Val de Loire',None),('Denver',None),('',None)]:
            with self.subTest(location=location):self.assertEqual(expected,monitor._country_code_from_location(location))
        self.assertEqual('🇩🇪 Германия',monitor._format_country_for_notification('Brand-Erbisdorf DE 09618'))

