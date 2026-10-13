import asyncio,copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock,AsyncMock
import monitor,price_history
from test_verified_history import HistoryConfig
from test_search_intent_rules import item

class MissingHybridPriceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.cfg=HistoryConfig();self.cfg.raw={'mobile_managed':True}
        self.config_patch=patch.object(monitor,'config',self.cfg);self.config_patch.start()
        self.db=patch.object(price_history,'DB_PATH',str(Path(self.folder.name)/'history.db'));self.db.start()
        self.search={'id':'hybrid-qa','query':'logitech superlight 2','filters':{'category':'mice','listing_type':'all','limit_price':150,'max_price':2500,'location':'worldwide'}}
        self.raw=item('Logitech Superlight 2 Gaming-Maus',item_id='hybrid-qa',price=80,shipping_cost=6,total_price=86,buy_now=True,auction=True,bin_price=None,auc_price=80,seller_name='seller',time_left='4d 10h')
        self.details={'title':self.raw['title'],'description':'Logitech Superlight 2. Voll funktionsfähig.','buyingOptions':['FIXED_PRICE','AUCTION'],'currentBidPrice':{'value':'80'}}
    def tearDown(self):
        self.db.stop();self.config_patch.stop();self.folder.cleanup()
    def test_api_summary_never_uses_the_only_price_for_both_sides(self):
        base={'itemId':'v1|123|0','title':self.raw['title'],'buyingOptions':['FIXED_PRICE','AUCTION']}
        bid=monitor.parse_ebay_api_results({'itemSummaries':[dict(base,currentBidPrice={'value':'80'})]})[0]
        self.assertEqual(80,bid['auc_price']);self.assertIsNone(bid['bin_price'])
        buy=monitor.parse_ebay_api_results({'itemSummaries':[dict(base,price={'value':'1000'})]})[0]
        self.assertEqual(1000,buy['bin_price']);self.assertIsNone(buy['auc_price'])
    def test_query_tag_and_merge_cannot_invent_purchase_from_bid(self):
        tagged=monitor._tag_items_for_search([self.raw],{'filters':{'listing_type':'buy_now'}})[0]
        self.assertIsNone(tagged['bin_price'])
        merged=monitor._merge_same_item(self.raw,dict(self.raw,price=70,auc_price=70))
        self.assertIsNone(merged['bin_price']);self.assertEqual(70,merged['auc_price'])
        buy=dict(self.raw,buy_now=True,auction=False,price=1000,bin_price=None,auc_price=None)
        bid=dict(self.raw,buy_now=False,auction=True,price=80,bin_price=None,auc_price=None)
        merged=monitor._merge_same_item(buy,bid)
        self.assertEqual((1000,80),(merged['bin_price'],merged['auc_price']))
    def test_all_selects_known_bid_and_keeps_auction_timing(self):
        self.assertEqual([],monitor.filter_results([self.raw],self.search,self.cfg))
        row=monitor.filter_results([dict(self.raw,time_left='20h')],self.search,self.cfg)[0]
        self.assertTrue(row['auction']);self.assertFalse(row['buy_now']);self.assertEqual(86,row['total_price'])
        row['time_left']=self.raw['time_left']
        self.assertEqual((False,'wait_24h'),monitor._notify_eligibility(row,self.search))
    def test_full_description_does_not_confirm_missing_purchase(self):
        purchase=monitor.split_statistics_buckets([self.raw])[0][0]
        search=copy.deepcopy(self.search);search['filters']['listing_type']='buy_now'
        with patch.object(monitor,'_fetch_item_details',return_value=self.details):
            selected=asyncio.run(monitor._select_cheapest_valid_candidate([purchase],search,stats_soft_fallback=True))
        self.assertIsNotNone(selected);self.assertEqual('unavailable_price',selected['_details_status'])
        self.assertTrue(monitor._hybrid_selected_price_missing(selected))
        self.assertEqual((False,'price_unavailable'),monitor._notify_eligibility(selected,search))
    def test_recovered_exact_purchase_is_refiltered_at_its_own_price(self):
        purchase=monitor.split_statistics_buckets([self.raw])[0][0]
        search=copy.deepcopy(self.search);search['filters']['listing_type']='buy_now'
        details=dict(self.details,price={'value':'1000'})
        with patch.object(monitor,'_fetch_item_details',return_value=details):
            selected=asyncio.run(monitor._select_cheapest_valid_candidate([purchase],search))
        self.assertEqual(1006,selected['total_price']);self.assertEqual('verified',selected['_details_status'])
        self.assertFalse(monitor.filter_results([selected],search,self.cfg))
    def test_missing_bid_cannot_use_known_buy_price_after_detail_refresh(self):
        raw=dict(self.raw,price=1000,bin_price=1000,auc_price=None)
        auction=monitor.split_statistics_buckets([raw])[2][0]
        search=copy.deepcopy(self.search);search['filters']['listing_type']='auction'
        details=dict(self.details,price={'value':'1000'});details.pop('currentBidPrice')
        with patch.object(monitor,'_fetch_item_details',return_value=details):
            valid,_=asyncio.run(monitor._validate_candidate(auction,search))
        self.assertFalse(valid);self.assertTrue(monitor._hybrid_selected_price_missing(auction))
    def test_missing_price_is_blocked_before_reserving_any_delivery_stage(self):
        for kind,index in (('buy_now',0),('auction',2)):
            raw=self.raw if kind=='buy_now' else dict(self.raw,price=1000,bin_price=1000,auc_price=None)
            selected=monitor.split_statistics_buckets([raw])[index][0]
            search=copy.deepcopy(self.search);search['filters']['listing_type']=kind
            details=self.details if kind=='buy_now' else {k:v for k,v in dict(self.details,price={'value':'1000'}).items() if k!='currentBidPrice'}
            with patch.object(monitor,'seen_state',{}),patch.object(monitor,'_fetch_item_details',return_value=details),patch.object(monitor,'mark_seen_item') as reserve,patch.object(monitor,'send_notification',new=AsyncMock()) as send:
                self.assertFalse(asyncio.run(monitor._process_notify_candidate(None,selected,search,None,'initial')))
            reserve.assert_not_called();send.assert_not_called()
        with patch.object(monitor,'safe_send_telegram',new=AsyncMock()) as send:
            self.assertFalse(asyncio.run(monitor.send_notification(None,monitor._project_price_side(self.raw,'bin'),self.search)))
        send.assert_not_called()
    def test_zero_is_known_and_never_substituted_with_other_side(self):
        raw=dict(self.raw,bin_price=0)
        purchase=monitor._project_price_side(monitor._calculate_total(raw,self.cfg.get_settings()),'bin')
        self.assertEqual(0,purchase['price']);self.assertFalse(monitor._hybrid_selected_price_missing(purchase))
    def test_hybrid_buy_offer_does_not_become_early_auction_offer(self):
        raw=dict(self.raw,best_offer=True)
        self.assertEqual([],monitor.filter_results([raw],self.search,self.cfg))
        row=monitor.filter_results([dict(raw,time_left='20h')],self.search,self.cfg)[0]
        row['time_left']=raw['time_left']
        self.assertFalse(row['best_offer']);self.assertEqual((False,'wait_24h'),monitor._notify_eligibility(row,self.search))
        tagged=monitor._tag_items_for_search([dict(raw,auc_price=None,bin_price=1000,price=1000)],{'filters':{'listing_type':'auction'}})[0]
        self.assertTrue(tagged['_was_hybrid']);self.assertIsNone(tagged['auc_price'])
    def test_full_statistics_report_shows_unknown_purchase_without_fake_price(self):
        self.cfg.get_searches=lambda:[copy.deepcopy(self.search)]
        messages=[]
        async def send(*args,**kwargs):messages.append(args[2]);return True
        with patch.object(monitor,'_is_statistics_mode',return_value=True),patch.object(monitor,'initialize_api_budget_and_queue'),patch.object(monitor,'fetch_ebay_ex',side_effect=lambda *a,**k:([copy.deepcopy(self.raw)],None)),patch.object(monitor,'_fetch_item_details',return_value=self.details),patch.object(monitor,'safe_send_telegram',send),patch('mobile.feed_writer.flush_pending'):
            asyncio.run(monitor.process_searches(None,once=True))
        report='\n'.join(messages)
        self.assertIn('Цена покупки недоступна',report)
        self.assertNotIn('Sofort      86',report)
        self.assertIn('Auktion     86',report)
