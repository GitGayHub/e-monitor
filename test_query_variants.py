import io
import unittest
from unittest.mock import patch
import monitor
from query_variants import phone_aliases,stored_aliases

class QueryVariantsTests(unittest.TestCase):
    def test_generation_and_modification_remain_in_every_alias(self):
        self.assertEqual(['iphone 17 pro max','apple iphone 17 pro max','iphone17 pro max','iphone17promax'],phone_aliases('iPhone 17 Pro Max'))
        self.assertEqual(['samsung galaxy s25 edge','samsung s25 edge','galaxy s25 edge','s25edge'],phone_aliases('Samsung S25 Edge'))
        leading=phone_aliases('nubia z80 ultra leading')
        self.assertEqual(4,len(leading))
        self.assertTrue(all('leading' in q for q in leading))
        self.assertEqual(leading,phone_aliases('nubia z80 ultra lv leading version'))
        self.assertTrue(all('wf' in q for q in phone_aliases('Sony WF-1000XM6')))
        self.assertEqual(phone_aliases('iPhone 17 Pro Max'),phone_aliases('iPhone 17 Pro-Max'))
        self.assertEqual(3,len(phone_aliases('asus vivobook 14x oled')))
        self.assertEqual(['ps5 pro','playstation 5 pro'],stored_aliases('(ps5 pro, playstation 5 pro)'))
    def test_api_fetch_uses_all_aliases_and_merges_duplicates(self):
        requests=[]
        def fetch(search,force=False):
            requests.append(search['_query_override'])
            return [{'item_id':'shared','title':'Sony WH-1000XM6','price':300,'buy_now':True},{'item_id':str(len(requests)),'title':'Sony WH-1000XM6','price':300,'buy_now':True}],None
        search={'query':'Sony WH-1000XM6','filters':{}}
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor,'fetch_ebay_api_ex',side_effect=fetch),patch.dict(monitor._ebay_query_cache,{},clear=True):
            items,error=monitor.fetch_ebay_ex(search,force=True)
        self.assertIsNone(error)
        self.assertEqual(phone_aliases(search['query']),requests)
        self.assertEqual(4,len(items))
    def test_alias_failure_is_visible_even_after_a_successful_primary(self):
        def fetch(search,force=False):
            if search['_query_override'].startswith('apple'):return [],'network'
            return [{'item_id':'primary','title':'iPhone 17 Pro Max','price':1000,'buy_now':True}],None
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor,'fetch_ebay_api_ex',side_effect=fetch) as request,patch.dict(monitor._ebay_query_cache,{},clear=True):
            items,error=monitor.fetch_ebay_ex({'query':'iphone 17 pro max','filters':{}},force=True)
        self.assertEqual('network',error)
        self.assertEqual(1,len(items))
        self.assertEqual(2,request.call_count)
    def test_scheduled_product_keeps_reservation_for_remaining_aliases(self):
        search={'id':'scheduled','query':'iphone 17 pro max','filters':{'listing_type':'all','category':'phones','condition':'any','location':'de'}}
        target=('scheduled',monitor.EBAY_MARKETPLACE_ID)
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor,'_get_ebay_api_token',return_value=('test-token',None)),patch.object(monitor,'_allowed_api_targets_this_run',{target}),patch.object(monitor.browse_access,'acquire',return_value=True) as acquire,patch.object(monitor,'record_search_run'),patch.object(monitor.urllib.request,'urlopen',side_effect=lambda *a,**k:io.BytesIO(b'{"itemSummaries":[]}')) as request,patch.dict(monitor._ebay_query_cache,{},clear=True):
            items,error=monitor.fetch_ebay_ex(search)
        self.assertIsNone(error)
        self.assertEqual([],items)
        self.assertEqual(4,request.call_count)
        self.assertEqual(4,acquire.call_count)
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor,'_get_ebay_api_token',return_value=('test-token',None)),patch.object(monitor,'_allowed_api_targets_this_run',set()),patch.object(monitor.urllib.request,'urlopen') as request,patch.dict(monitor._ebay_query_cache,{},clear=True):
            items,error=monitor.fetch_ebay_ex(search)
        self.assertEqual('api_deferred',error)
        request.assert_not_called()
