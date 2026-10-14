import io
import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock
import monitor
from pathlib import Path


class HtmlPrimaryTest(unittest.TestCase):
    def test_missing_live_price_cannot_pass_candidate_or_send_even_with_complete_seller_body(self):
        item={'item_id':'123456789012','title':'Device','price':30.0,'seller_name':'qa-seller'}
        data={'description':'Device works correctly.'}
        with patch.object(monitor,'_fetch_item_details',return_value=data),patch.object(monitor,'_details_match_contract',return_value=True), \
             patch.object(monitor,'get_seen_entry',return_value={}),patch.object(monitor,'send_notification') as send:
            accepted,_=asyncio.run(monitor._validate_candidate(item,self.search))
            self.assertFalse(accepted);self.assertEqual('unavailable_price',item['_details_status'])
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(None,item,self.search,{},'initial')))
            send.assert_not_called()
    def test_same_provider_completeness_boundaries_as_android(self):
        fixture=json.loads((Path(__file__).parent/'qa/fixtures/provider_details_oct14.json').read_text(encoding='utf8'))
        for case in fixture['cases']:
            self.assertEqual(case['complete'],monitor._provider_details_complete(case['data']),case['name'])

    def setUp(self):
        self.search = {'id':'qa-phone','query':'phone','filters':{'listing_type':'buy_now'}}
        for name,value in [('_ebay_query_cache',{}),('_item_details_cache',{}),('EBAY_SOURCE','auto'),
                           ('_ebay_block_until',0),('_ebay_api_circuit_open',False)]:
            p=patch.object(monitor,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(monitor.browse_access,'is_paused',return_value=False);p.start();self.addCleanup(p.stop)
        p=patch.object(monitor,'_ebay_api_configured',return_value=True);p.start();self.addCleanup(p.stop)

    def test_html_success_and_confirmed_empty_never_use_api(self):
        for rows in ([{'item_id':'123456789012','source':'html'}],[]):
            with self.subTest(rows=rows),patch.object(monitor,'_do_fetch_one',return_value=(rows,None)), \
                 patch.object(monitor,'_do_fetch_playwright',return_value=([],None)),patch.object(monitor,'fetch_ebay_api_ex') as api:
                monitor._ebay_query_cache.clear()
                result,error=monitor.fetch_ebay_ex(self.search,force=True)
                self.assertEqual(rows,result);self.assertIsNone(error);api.assert_not_called()

    def test_html_failure_uses_api_once_but_empty_or_quota_preserve_error(self):
        api_rows=[{'item_id':'123456789012','source':'api'}]
        for reserve in [(api_rows,None),([],None),([], 'api_rate_limit')]:
            with self.subTest(reserve=reserve),patch.object(monitor,'_do_fetch_one',return_value=([], 'network')), \
                 patch.object(monitor,'_do_fetch_playwright',return_value=([], 'network')),patch.object(monitor,'fetch_ebay_api_ex',return_value=reserve) as api:
                result,error=monitor.fetch_ebay_ex(self.search,force=True)
                if reserve[0]:self.assertEqual(api_rows,result);self.assertIsNone(error)
                else:self.assertEqual([],result);self.assertIsNotNone(error)
                api.assert_called_once()

    def test_html_description_before_api_and_no_duplicate_page_on_api_failure(self):
        complete={'description':'Own working phone description','price':{'value':'500','currency':'EUR'}}
        for data in [complete, {'estimatedAvailabilities':[{'estimatedAvailabilityStatus':'UNAVAILABLE'}]}]:
            with patch.object(monitor,'_fetch_item_details_html',return_value=data) as html,patch.object(monitor,'_get_ebay_api_token') as token:
                monitor._item_details_cache.clear()
                self.assertEqual(data,monitor._fetch_item_details('123456789012'))
                html.assert_called_once();token.assert_not_called()
        with patch.object(monitor,'_fetch_item_details_html',return_value=None) as html, \
             patch.object(monitor,'_get_ebay_api_token',return_value=('qa',None)),patch.object(monitor.browse_access,'acquire',return_value=True), \
             patch.object(monitor.urllib.request,'urlopen',side_effect=TimeoutError('qa')) as api:
            monitor._item_details_cache.clear()
            self.assertIsNone(monitor._fetch_item_details('123456789012'))
            html.assert_called_once();api.assert_called_once()

    def test_missing_html_description_uses_full_api_then_normal_defect_filter(self):
        data={'title':'Phone','description':'The phone display is broken','price':{'value':'500','currency':'EUR'}}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(data).encode()
        with patch.object(monitor,'_fetch_item_details_html',return_value={'title':'Phone','description':''}) as html, \
             patch.object(monitor,'_get_ebay_api_token',return_value=('qa',None)),patch.object(monitor.browse_access,'acquire',return_value=True), \
             patch.object(monitor.urllib.request,'urlopen',return_value=response) as api:
            self.assertEqual(data,monitor._fetch_item_details('123456789012'))
            self.assertFalse(monitor._details_match_contract({'title':'Phone'},{'query':'Phone','filters':{'category':'phones'}},data))
            html.assert_called_once();api.assert_called_once()

    def test_html_queue_does_not_request_oauth_or_analytics_with_healthy_api(self):
        with patch.object(monitor,'_get_ebay_api_token') as token,patch.object(monitor.urllib.request,'urlopen') as api, \
             patch.object(monitor.browse_access,'state',return_value={}),patch.object(monitor,'get_last_run',return_value=None):
            monitor.initialize_api_budget_and_queue([self.search])
            self.assertIn((self.search['id'],monitor.EBAY_MARKETPLACE_ID),monitor._allowed_api_targets_this_run)
            token.assert_not_called();api.assert_not_called()
