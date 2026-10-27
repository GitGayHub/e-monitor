"""Run offline tests without touching production config, state or SQLite files."""
import logging
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="emonitor-tests-") as folder:
        import price_history
        import config_manager
        price_history.DB_PATH = str(Path(folder) / "price_history.db")
        config_manager.CONFIG_PATH = str(Path(folder) / "config.json")
        import monitor
        from mobile import telegram_text_outbox
        telegram_text_outbox.PATH = Path(folder) / "telegram_text_outbox.json.enc"
        monitor.SEEN_IDS_FILE = str(Path(folder) / "seen_ids.json")
        logging.disable(logging.CRITICAL)
        modules = ["test_details_filter", "test_search_intent_rules", "test_search_price_floor",
                   "test_display_replacement_rule", "test_auction_final_stages",
                   "test_auction_serp_recovery", "test_serp_empty_marker", "test_mobile_contract", "test_parity", "test_checkpoint_integration", "test_ebay_access", "test_runtime_status", "test_browse_request_contract", "test_seller_description_scope", "test_manual_device_evidence", "test_query_variants", "test_cloud_search_regressions"]
        original_connect = socket.socket.connect
        modules.append("test_battery_swelling_manual")
        modules.append("test_mouse_catalogue_context")
        modules.append("test_mouse_feature_context")
        modules.append("test_mouse_charging_bundle")
        modules.append("test_mouse_replacement_condition")
        modules.append("test_telegram_text_outbox")
        modules.append("test_median_reports")
        modules.append("test_import_estimates")
        modules.append("test_live_bid_history")
        modules.append("test_verified_history")
        modules.append("test_missing_hybrid_price")
        modules.append("test_monitor_pass_budget")
        modules.append("test_sim_tray_purpose")
        modules.append("test_port_condition")
        modules.append("test_html_primary")
        modules.append("test_phone_bundle_defect")
        modules.append("test_description_pickup")
        modules.append("test_phone_packaging")
        modules.append("test_selected_phone_variant")
        modules.append("qa.test_live_price_probe")
        modules.append("test_phone_family_style")
        modules.append("test_phone_implicit_bundle")
        modules.append("test_samsung_model_codes")
        modules.append("test_country_location")
        modules.append("test_phone_refurbished_history")
        modules.append("test_workflow_dispatch_queue")
        modules.append("test_description_protection")
        modules.append("test_search_response_status")
        modules.append("test_telegram_delivery_uncertain")
        modules.append("test_phone_conversion")
        modules.append("test_euro_money")
        modules.append("test_accessory_package")
        modules.append("test_notification_search_link")
        modules.append("test_linked_seller_description")
        modules.append("test_phone_storage")
        modules.append("test_validation_resume")
        modules.append("test_phone_condition_context")
        modules.append("test_phone_sales_object")
        modules.append("test_live_alias_queue")
        modules.append("test_live_coverage_recovery")
        modules.append("test_live_unstarted_search")
        modules.append("test_laptop_amoled")
        modules.append("test_laptop_led_strip")
        modules.append("test_oled_burn_negation")
        modules.append("test_hp_spectre_oled")
        modules.append("test_followup_dispatch")
        modules.append("test_browser_challenge_wait")
        modules.append("test_spare_accessory_exchange")
        modules.append("test_html_seller_type")
        modules.append("test_phone_cover_negation")
        modules.append("test_decorative_parts")
        modules.append("test_mouse_offer126")
        modules.append("test_model_enrichment")
        modules.append("test_phone_own_model")
        modules.append("test_phone_ambiguous_purpose")
        modules.append("test_mobile_search_status")
        modules.append("test_manufacturer_warranty")
        modules.append("test_gpu_own_spec")
        modules.append("test_laptop_battery_check")
        modules.append("test_ps5_contents")
        modules.append("test_variation_dom_evidence")
        modules.append("test_live_validation_fairness")
        modules.append("test_status_country_oct22")
        modules.append("test_phone_spacing")
        modules.append("test_sold_iphone_oct23")
        modules.append("test_search_priority")
        modules.append("test_browser_bootstrap")
        modules.append("test_phone_usb_chip")
        modules.append("test_image_only_offer")
        modules.append("test_mouse_offer")
        modules.append("test_product_tools")
        modules.append("test_api_usage")
        modules.append("test_samsung_monitor_sku")
        def offline_connect(sock, address):
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
                return original_connect(sock, address)
            raise RuntimeError("Network forbidden in offline unit tests")
        with patch.object(socket.socket, "connect", offline_connect):
            result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
