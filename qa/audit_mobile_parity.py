"""Read-only live audit. No Telegram sends and no production state writes."""
import argparse
import copy
import json
import logging
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = json.loads(Path(args.config).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"startedAt": datetime.now(timezone.utc).isoformat(), "searches": [], "cases": []}
    with tempfile.TemporaryDirectory(prefix="emonitor-live-audit-", ignore_cleanup_errors=True) as folder:
        import price_history, config_manager
        price_history.DB_PATH = str(Path(folder) / "price_history.db")
        config_manager.CONFIG_PATH = str(Path(folder) / "config.json")
        Path(config_manager.CONFIG_PATH).write_text(json.dumps(source), encoding="utf-8")
        import monitor
        from mobile.build_app_sync import convert_search
        from test_parity import evaluate
        monitor.SEEN_IDS_FILE = str(Path(folder) / "seen_ids.json")
        logging.getLogger().setLevel(logging.ERROR)
        active = [s for s in source["searches"] if s.get("enabled", True)]
        monitor.initialize_api_budget_and_queue(active)
        for n, search in enumerate(active, 1):
            started = datetime.now(timezone.utc).isoformat()
            rows, error = monitor.fetch_ebay_ex(monitor._prepare_monitor_fetch_search(search), force=False)
            result = {"id": search["id"], "query": search["query"], "startedAt": started,
                      "fetched": len(rows), "error": error, "matched": 0, "notifyEligible": 0}
            for index, raw in enumerate(rows):
                case = {"name": f"{search['id']}::{raw.get('item_id', index)}", "search": convert_search(search),
                        "item": copy.deepcopy(raw), "settings": source.get("settings", {}),
                        "state": {"hiddenItems": source.get("banned_item_ids", []), "bannedSellers": source.get("global_banned_sellers", [])}}
                accepted, reason, total = evaluate(case)
                case["expected"] = {"accepted": accepted, "reason": reason, "totalPrice": total}
                report["cases"].append(case)
                result["matched"] += int(accepted)
                result["notifyEligible"] += int(accepted and reason == "notify")
            report["searches"].append(result)
            (output / "live-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"progress": f"{n}/{len(active)}", **result}, ensure_ascii=False), flush=True)
            if str(error or "").startswith("cooldown"):
                # Record subsequent failures honestly; do not bypass eBay cooldown.
                time.sleep(1)
            else:
                time.sleep(2)
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        (output / "live-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
