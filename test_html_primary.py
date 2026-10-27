import io
import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import price_history
import config_manager
from pathlib import Path

# Direct unittest invocation must not initialise the user's local history.
with tempfile.TemporaryDirectory() as folder, \
        patch.object(price_history,'DB_PATH',str(Path(folder)/'history.db')), \
        patch.object(config_manager,'CONFIG_PATH',str(Path(folder)/'config.json')):
    import monitor


class HtmlPrimaryTest(unittest.TestCase):
    def test_incomplete_html_keeps_own_description_if_browser_is_unavailable(self):
        c=json.loads((Path(__file__).parent/'qa/fixtures/shipping_unconfirmed_oct23.json').read_text(encoding='utf8'))[0]
        partial=monitor._parse_item_details_html(c['html'],description=c['description'])
        self.assertFalse(monitor._provider_details_complete(partial))
        response=MagicMock(status_code=200,text=c['html'],url='https://www.ebay.de/itm/327411626248')
        session=MagicMock();session.get.return_value=response
        with patch.object(monitor,'_get_ebay_session',return_value=session), \
             patch.object(monitor,'_parse_item_details_html',return_value=partial), \
             patch.object(monitor,'_fetch_item_details_browser',return_value=None) as browser:
            result=monitor._fetch_item_details_html('327411626248')
        self.assertEqual(partial,result)
        self.assertFalse(monitor._provider_details_complete(result))
        browser.assert_called_once_with('327411626248')
        with patch.object(monitor,'_get_ebay_session',return_value=session), \
             patch.object(monitor,'_parse_item_details_html',return_value={'description':''}), \
             patch.object(monitor,'_fetch_item_details_browser',return_value=None):
            self.assertIsNone(monitor._fetch_item_details_html('327411626248'))

    def test_unknown_html_shipping_uses_api_or_stays_unverified(self):
        c=json.loads((Path(__file__).parent/'qa/fixtures/shipping_unconfirmed_oct23.json').read_text(encoding='utf8'))[0]
        partial=monitor._parse_item_details_html(c['html'],description=c['description'])
        quote={'description':c['description'],'price':{'value':'19.17','currency':'EUR'},'shippingOptions':[{'shippingCost':{'value':'12','currency':'EUR'},'shippingCostType':'FIXED','shipToLocationUsedForEstimate':{'country':'DE','postalCode':'09648'}}]}
        for api_data in (quote,None):
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(api_data).encode()
            with self.subTest(quoted=api_data is not None),patch.object(monitor,'_fetch_item_details_html',return_value=partial) as html,patch.object(monitor,'_get_ebay_api_token',return_value=('qa',None)),patch.object(monitor.browse_access,'acquire',return_value=True),patch.object(monitor.urllib.request,'urlopen',return_value=response,side_effect=TimeoutError('offline API') if api_data is None else None) as api:
                monitor._item_details_cache.clear()
                data=monitor._fetch_item_details('123456789012')
                self.assertEqual(api_data is not None,monitor._provider_details_complete(data))
                html.assert_called_once();api.assert_called_once()
    def test_missing_live_price_cannot_pass_candidate_or_send_even_with_complete_seller_body(self):
        item={'item_id':'123456789012','title':'Device','price':30.0,'seller_name':'qa-seller'}
        data={'description':'Device works correctly.'}
        with patch.object(monitor,'_fetch_item_details',return_value=data),patch.object(monitor,'_details_match_contract',return_value=True), \
             patch.object(monitor,'get_seen_entry',return_value={}),patch.object(monitor,'send_notification') as send:
            accepted,_=asyncio.run(monitor._validate_candidate(item,self.search))
            self.assertFalse(accepted);self.assertEqual('unavailable_price',item['_details_status'])
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(None,item,self.search,{},'initial')))
            send.assert_not_called()
    def test_rejected_details_refresh_seller_and_photo_without_accepting_or_replacing_price(self):
        seller_case=json.loads((Path(__file__).parent/'qa/fixtures/html_seller.json').read_text(encoding='utf8'))[0]
        own_photo='https://i.ebayimg.com/images/g/own/s-l1600.jpg'
        html=seller_case['html'] + f'<meta property="og:image" content="{own_photo}">'
        details=monitor._parse_item_details_html(html,description='Der Controller ist defekt. Stickdrift, nur als Ersatzteil.')
        item={'item_id':'128121409205','title':'Sony DualSense Wireless Controller','price':30.0,
              'seller_name':'unknown','image_url':'old','_details_status':'preliminary'}
        with patch.object(monitor,'_fetch_item_details',return_value=details) as fetch, \
             patch.object(monitor,'_refresh_candidate_details') as refresh, \
             patch.object(monitor,'send_notification') as send:
            accepted,returned=asyncio.run(monitor._validate_candidate(item,{'query':'DualSense','filters':{}}))
            self.assertFalse(accepted)
            self.assertIs(details,returned)
            self.assertEqual('rejected',item['_details_status'])
            self.assertEqual('marclemmor',item['seller_name'])
            self.assertEqual(452,item['seller_rating_count'])
            self.assertEqual(100.0,item['seller_rating_percent'])
            self.assertEqual('private',item['seller_type'])
            self.assertEqual(own_photo,item['image_url'])
            self.assertEqual(30.0,item['price'])
            self.assertNotIn('_details_loaded',item)
            fetch.assert_called_once();refresh.assert_not_called();send.assert_not_called()

    def test_missing_seller_metadata_preserves_known_card_fields_on_refusal(self):
        item={'item_id':'128121409205','title':'Sony DualSense Wireless Controller','price':30.0,
              'seller_name':'known-seller','seller_rating_count':42,'seller_rating_percent':99.5,
              'seller_type':'commercial','image_url':'known-photo'}
        with patch.object(monitor,'_fetch_item_details',return_value={'description':'defekt'}), \
             patch.object(monitor,'_details_match_contract',return_value=False):
            accepted,_=asyncio.run(monitor._validate_candidate(item,self.search))
        self.assertFalse(accepted)
        self.assertEqual('known-seller',item['seller_name'])
        self.assertEqual(42,item['seller_rating_count'])
        self.assertEqual(99.5,item['seller_rating_percent'])
        self.assertEqual('commercial',item['seller_type'])
        self.assertEqual('known-photo',item['image_url'])

    def test_fresh_serp_sellers_survive_refurbished_refusal(self):
        from test_search_intent_rules import DummyConfig
        cases=json.loads((Path(__file__).parent/'qa/fixtures/seller_cards_oct15.json').read_text(encoding='utf8'))
        search={'id':'qa-s25','query':'samsung galaxy s25 edge','filters':{'category':'phones','listing_type':'all','limit_price':325}}
        for case in cases:
            item=monitor.parse_ebay_results(case['html'])[0]
            self.assertEqual(case['seller'],item['seller_name'])
            accepted=monitor.filter_results([item],search,DummyConfig(),skip_seen=True,is_statistics=True)
            self.assertEqual(not case['rejected'],bool(accepted),case['id'])
            self.assertEqual(case['seller'],item['seller_name'])

    def test_same_provider_completeness_boundaries_as_android(self):
        fixture=json.loads((Path(__file__).parent/'qa/fixtures/provider_details_oct14.json').read_text(encoding='utf8'))
        for case in fixture['cases']:
            self.assertEqual(case['complete'],monitor._provider_details_complete(case['data']),case['name'])

    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        db=patch.object(price_history,'DB_PATH',str(Path(folder.name)/'history.db'));db.start();self.addCleanup(db.stop)
        keys=patch.object(monitor,'_configured_ebay_api_keys',return_value=[]);keys.start();self.addCleanup(keys.stop)
        self.search = {'id':'qa-phone','query':'phone','filters':{'listing_type':'buy_now'}}
        for name,value in [('_ebay_query_cache',{}),('_item_details_cache',{}),('EBAY_SOURCE','auto'),
                           ('_ebay_block_until',0),('_ebay_api_circuit_open',False)]:
            p=patch.object(monitor,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(monitor.browse_access,'is_paused',return_value=False);p.start();self.addCleanup(p.stop)
        p=patch.object(monitor,'_ebay_api_configured',return_value=True);p.start();self.addCleanup(p.stop)

    def test_html_success_and_confirmed_empty_never_use_api(self):
        for rows in ([{'item_id':'123456789012','source':'html'}],[]):
            with self.subTest(rows=rows),patch.object(monitor,'_do_fetch_one',return_value=(rows,None)), \
                 patch.object(monitor,'_do_fetch_playwright',return_value=([],None)) as browser,patch.object(monitor,'fetch_ebay_api_ex') as api:
                monitor._ebay_query_cache.clear()
                result,error=monitor.fetch_ebay_ex(self.search,force=True)
                self.assertEqual(rows,result);self.assertIsNone(error);api.assert_not_called()
                browser.assert_not_called()

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
