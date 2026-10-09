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
        monitor.SEEN_IDS_FILE = str(Path(folder) / "seen_ids.json")
        logging.disable(logging.CRITICAL)
        modules = ["test_details_filter", "test_search_intent_rules", "test_search_price_floor",
                   "test_display_replacement_rule", "test_auction_final_stages",
                   "test_auction_serp_recovery", "test_serp_empty_marker", "test_mobile_contract", "test_parity", "test_checkpoint_integration", "test_ebay_access", "test_runtime_status", "test_browse_request_contract", "test_seller_description_scope", "test_manual_device_evidence", "test_query_variants", "test_cloud_search_regressions"]
        original_connect = socket.socket.connect
        def offline_connect(sock, address):
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
                return original_connect(sock, address)
            raise RuntimeError("Network forbidden in offline unit tests")
        with patch.object(socket.socket, "connect", offline_connect):
            result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
