import io
import asyncio
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import monitor
import price_history
from ebay_access import BrowseAccess


class BrowseAccessTest(unittest.TestCase):
    def test_html_queue_is_bounded_and_failed_attempts_do_not_starve_other_searches(self):
        self.access.save({'remaining':0,'reset':time.time()+21600,'checked':time.time()})
        searches=[{'id':f'p{i:02d}','query':'phone'} for i in range(14)]
        with patch.object(monitor,'browse_access',self.access), patch.object(monitor,'_get_ebay_api_token',return_value=('qa',None)):
            monitor.initialize_api_budget_and_queue(searches)
            first=monitor._allowed_api_targets_this_run.copy()
            self.assertEqual(8,len(first))
            for search_id,market in first:
                self.access.record_html_attempt(search_id,market)
            monitor.initialize_api_budget_and_queue(searches)
            following=monitor._allowed_api_targets_this_run
            self.assertEqual(6,len(following))
            self.assertFalse(first & following)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = patch.object(price_history, "DB_PATH", str(Path(self.folder.name) / "db.sqlite"))
        self.db.start()
        self.addCleanup(self.db.stop)
        price_history.init_db()
        self.access = BrowseAccess()

    def test_pause_survives_new_runner_and_does_not_consume_calls(self):
        self.access.pause("120")
        self.assertFalse(BrowseAccess().acquire())
        self.assertEqual(price_history.get_api_calls_count_24h(), 0)

    def test_exhausted_quota_refuses_force_requests_until_reset(self):
        self.access.save({"remaining": 0, "reset": time.time() + 60})
        self.assertFalse(self.access.acquire())
        self.access.save({"remaining": 0, "reset": time.time() - 1})
        self.assertTrue(self.access.acquire())

    def test_details_attempts_are_counted_and_quota_is_consumed(self):
        self.access.save({"remaining": 5, "reset": time.time() + 600})
        self.assertTrue(self.access.acquire())
        self.assertEqual(self.access.state()["remaining"], 4)
        self.assertEqual(price_history.get_api_calls_count_24h(), 1)

    def test_analytics_uses_shared_browse_quota_not_bulk(self):
        rates = lambda remaining: [{"remaining": remaining, "limit": 5000, "reset": "2030-01-01T00:00:00Z"}]
        self.assertTrue(self.access.update_quota({"rateLimits": [{"resources": [
            {"name": "buy.browse.item.bulk", "rates": rates(5000)},
            {"name": "buy.browse", "rates": rates(90)}]}]}))
        self.assertEqual(self.access.state()["remaining"], 90)
        self.assertGreater(self.access.interval(46), 900)

    def test_exhausted_quota_uses_html_cadence_without_false_runtime_error(self):
        self.access.save({'remaining':0,'reset':time.time()+21600,'checked':time.time()})
        with patch.object(monitor,'browse_access',self.access), \
             patch.object(monitor,'_get_ebay_api_token',return_value=('qa',None)), \
             patch.object(monitor,'_runtime_errors',[]) as errors, \
             patch.object(monitor.urllib.request,'urlopen') as requests:
            monitor.initialize_api_budget_and_queue([])
            self.assertEqual([],errors)
            self.assertTrue(monitor._runtime_html_fallback)
            monitor.initialize_api_budget_and_queue([])
            self.assertEqual([],errors)
            requests.assert_not_called()


class BrowseTransportTest(unittest.TestCase):
    def setUp(self):
        monitor._ebay_query_cache.clear()
        monitor._item_details_cache.clear()

    def test_rate_limit_switches_to_html_once_and_keeps_its_errors(self):
        with patch.object(monitor, "EBAY_SOURCE", "auto"), patch.object(monitor, "_ebay_api_configured", return_value=True), \
             patch.object(monitor, "fetch_ebay_api_ex", return_value=([], "api_rate_limit")), \
             patch.object(monitor, "_fetch_quota_html",return_value=([], "blocked")) as html:
            self.assertEqual(monitor.fetch_ebay_ex({"id":"x", "query":"phone"}, force=True), ([], "blocked"))
            html.assert_called_once()

    def test_known_quota_pause_skips_api_and_html_never_loops_back(self):
        rows=[{"item_id":"123456789012","title":"Phone"}]
        with patch.object(monitor,"EBAY_SOURCE","auto"), patch.object(monitor,"_ebay_api_configured",return_value=True), \
             patch.object(monitor.browse_access,"is_paused",return_value=True), \
             patch.object(monitor,"fetch_ebay_api_ex") as api, \
             patch.object(monitor,"_do_fetch_one",return_value=(rows,None)) as html:
            result,error=monitor.fetch_ebay_ex({"id":"x","query":"phone"},force=True)
            self.assertIsNone(error)
            self.assertEqual(["123456789012"],[row['item_id'] for row in result])
            self.assertTrue(all(row['source']=='html' for row in result))
            self.assertEqual(2,html.call_count)
            self.assertEqual({'buy_now','auction'},{call.args[1]['filters']['listing_type'] for call in html.call_args_list})
            self.assertTrue(html.call_args.args[1]["_html_fallback"])
            api.assert_not_called()

    def test_details_under_quota_use_complete_html_and_cache_without_api(self):
        details={"description":"A complete working phone", "price":{"value":"500","currency":"EUR"}}
        with patch.object(monitor,"_ebay_api_configured",return_value=True), \
             patch.object(monitor.browse_access,"is_paused",return_value=True), \
             patch.object(monitor,"_get_ebay_api_token") as token, \
             patch.object(monitor,"_fetch_item_details_html",return_value=details) as html:
            self.assertEqual(details,monitor._fetch_item_details("123456789012"))
            self.assertEqual(details,monitor._fetch_item_details("123456789012"))
            html.assert_called_once()
            token.assert_not_called()

    def test_specs_without_seller_description_remain_unverified_under_quota(self):
        with patch.object(monitor,"_ebay_api_configured",return_value=True), \
             patch.object(monitor.browse_access,"is_paused",return_value=True), \
             patch.object(monitor,"_fetch_item_details_html",return_value={"description":"","localizedAspects":[{"name":"Modell","value":"Phone"}]}):
            self.assertIsNone(monitor._fetch_item_details("123456789012"))

    def test_not_scheduled_is_error_not_empty_success(self):
        with patch.object(monitor, "_get_ebay_api_token", return_value=("token", None)), \
             patch.object(monitor, "_allowed_api_targets_this_run", set()), \
             patch.object(monitor.urllib.request, "urlopen") as opener:
            self.assertEqual(monitor.fetch_ebay_api_ex({"id":"x", "query":"phone"}), ([], "api_deferred"))
            opener.assert_not_called()

    def test_one_429_persists_pause_without_second_request(self):
        response = urllib.error.HTTPError("url", 429, "limited", {"Retry-After":"60"}, io.BytesIO())
        with patch.object(monitor, "_get_ebay_api_token", return_value=("token", None)), \
             patch.object(monitor, "browse_access") as access, \
             patch.object(monitor.urllib.request, "urlopen", side_effect=response) as opener:
            access.acquire.return_value = True
            self.assertEqual(monitor.fetch_ebay_api_ex({"query":"phone"}, force=True), ([], "api_rate_limit"))
            self.assertEqual(opener.call_count, 1)
            access.pause.assert_called_once_with("60")

    def test_details_without_description_are_never_verified(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"title":"Phone","price":{"value":"500"}}'
        with patch.object(monitor, "EBAY_SOURCE", "auto"), patch.object(monitor, "_ebay_api_configured", return_value=True), \
             patch.object(monitor, "_get_ebay_api_token", return_value=("token", None)), \
             patch.object(monitor, "browse_access"), patch.object(monitor.urllib.request, "urlopen", return_value=response), \
             patch.object(monitor, "_fetch_item_details_html",return_value=None) as html:
            self.assertIsNone(monitor._fetch_item_details("123456789"))
            html.assert_called_once()

    def test_mixed_listing_and_ending_soon_api_filters(self):
        params = monitor._build_ebay_api_params({"query":"phone", "filters":{"listing_type":"all", "sort":"ending_soon"}})
        self.assertIn("buyingOptions:{FIXED_PRICE|AUCTION}", params["filter"])
        self.assertEqual(params["sort"], "endingSoonest")

    def test_release_footer_contains_apk_and_actual_source(self):
        with tempfile.TemporaryDirectory() as folder:
            version=Path(folder)/'mobile/app_version.json'
            version.parent.mkdir()
            version.write_text(json.dumps({'schema':1,'versionName':'0.123'}),encoding='utf8')
            with patch.object(monitor,'__file__',str(Path(folder)/'monitor.py')):
                self.assertEqual(monitor._apk_version_label(), "0.123")
        self.assertEqual(monitor._fetch_source_label("api"), "eBay Browse API")

    def test_unavailable_description_does_not_pass_statistics_or_scrape_html(self):
        item = {"item_id":"123456789", "title":"DualSense", "price":30, "total_price":30, "buy_now":True}
        with patch.object(monitor, "_fetch_item_details", return_value=None), patch.object(monitor, "_is_item_page_multivariation") as html:
            passed, details = asyncio.run(monitor._validate_candidate(item, {"query":"DualSense", "filters":{}}))
            self.assertFalse(passed)
            self.assertEqual(item["_details_status"], "unavailable")
            html.assert_not_called()

    def test_rejected_description_is_never_statistics_soft_fallback(self):
        item = {"item_id":"123456789", "title":"DualSense", "price":30, "total_price":30, "buy_now":True}
        with patch.object(monitor, "_fetch_item_details", return_value={"description":"Controller defekt"}), \
             patch.object(monitor, "_details_match_contract", return_value=False):
            selected = asyncio.run(monitor._select_cheapest_valid_candidate([item], {"query":"DualSense", "filters":{}}, stats_soft_fallback=True))
            self.assertIsNone(selected)
