"""«Display neu» is a swapped screen. «OLED Monitor … NEU» is a new monitor.

The old rule matched `(display|oled|glas|…) .* (neu|getauscht|…)` across the
whole title, so the only live LG auction lot on 2026-07-26 —
«LG Ultragear 32GS95UX-B.AEU (32") 4K UHD OLED Gaming Monitor 240Hz/480Hz - NEU»,
item 267738467047, 450 € — was thrown away as a replacement part and the bucket
printed «Не найдено» over real stock.

Repair verbs still match at any distance; the bare "neu" family has to sit next
to the display word; and on a monitor/TV, where the panel is the product, the
heuristic does not run at all.
"""

import unittest

import monitor


def _blocked(title, category, query="lg ultragear oled 480hz"):
    return monitor._is_category_blocked_title(
        monitor._normalize(title), category, monitor._normalize(query)
    )


def _is_replacement(title):
    return monitor._is_display_replacement(monitor._normalize(title))


class PhoneScreenSwapsStillBlockedTest(unittest.TestCase):
    def test_adjacent_new_display(self):
        for title in (
            "iPhone 13 Pro Display neu",
            "iPhone 13 Pro neues Display",
            "Samsung S21 Display ist neu",
            "iPhone 12 OLED neu",
        ):
            self.assertTrue(_is_replacement(title), title)

    def test_repair_verbs_at_any_distance(self):
        for title in (
            "iPhone 13 Pro Max 256GB Display wurde letzte Woche getauscht",
            "Samsung S21 Ultra, Bildschirm nach Sturz repariert",
            "iPhone 11 — ersetztes Display, sonst top Zustand",
        ):
            self.assertTrue(_is_replacement(title), title)

    def test_negation_directly_before_the_repair_word_passes(self):
        for title in (
            "iPhone 13 Pro Display nicht getauscht",
            "iPhone 13 Pro Display ohne Austausch",
        ):
            self.assertFalse(_is_replacement(title), title)

    def test_known_gap_negation_before_the_part_word(self):
        """Pre-existing, unchanged by this fix: the lookbehinds guard the repair
        word only, so "ohne Display Austausch" still reads as a swap. Documented
        rather than silently altered — it is phone-filter behaviour, not the
        auction-bucket bug this change is about."""
        self.assertTrue(_is_replacement("iPhone 13 Pro ohne Display Austausch"))

    def test_phone_category_still_blocks_swapped_screens(self):
        self.assertTrue(
            _blocked("iPhone 13 Pro Display neu getauscht", "phones", "iphone 13 pro")
        )


class OledDeviceIsNotAPartTest(unittest.TestCase):
    LG = 'LG Ultragear 32GS95UX-B.AEU (32") 4K UHD OLED Gaming Monitor 240Hz/480Hz - NEU'

    def test_the_lot_the_rule_used_to_eat(self):
        self.assertFalse(_is_replacement(self.LG))
        self.assertFalse(_blocked(self.LG, "monitors"))

    def test_new_oled_laptop_survives(self):
        title = "ASUS Vivobook 14X OLED 14 Zoll i5 16GB 512GB - NEU & OVP"
        self.assertFalse(_is_replacement(title), title)
        self.assertFalse(_blocked(title, "laptops", "asus vivobook 14x oled"))

    def test_monitor_category_skips_the_heuristic_entirely(self):
        # Even the adjacent phrasing is a new device when the panel is the product.
        title = "LG UltraGear OLED neu, 27 Zoll 480Hz"
        self.assertTrue(_is_replacement(title), "adjacency still fires on the raw text")
        self.assertFalse(_blocked(title, "monitors"), "…but monitors never use it")

    def test_phones_are_not_exempt(self):
        title = "iPhone 15 Pro OLED neu"
        self.assertTrue(_blocked(title, "phones", "iphone 15 pro"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
