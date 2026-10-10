import io
import unittest
from unittest.mock import patch
import monitor
from query_variants import phone_aliases,stored_aliases,api_query_batches

class QueryVariantsTests(unittest.TestCase):
    def test_real_sony_product_name_is_discovered_without_requiring_sku(self):
        import json
        from pathlib import Path
        evidence=json.loads((Path(__file__).parent/'qa/fixtures/sony_ult_manual_oct10.json').read_text(encoding='utf8'))
        search={'query':evidence['query'],'filters':{'category':'headphones'}}
        aliases=monitor._search_query_variants(search)
        self.assertTrue(set(evidence['requiredAliases']).issubset(aliases))
        requests=[]
        def fetch(child,force=False):
            query=child['_query_override'];requests.append(query)
            if query==evidence['primaryQuery']:
                return [{'item_id':'307029264069','title':evidence['cases'][0]['title'],'price':79.9,'buy_now':True,'best_offer':True}],None
            return [],None
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor.browse_access,'is_paused',return_value=False),patch.object(monitor,'fetch_ebay_api_ex',side_effect=fetch),patch.dict(monitor._ebay_query_cache,{},clear=True):
            rows,error=monitor.fetch_ebay_ex(search,force=True)
        self.assertIsNone(error)
        self.assertEqual(evidence['primaryQuery'],requests[0])
        self.assertEqual(['307029264069'],[x['item_id'] for x in rows])
        for case in evidence['cases']:
            self.assertEqual(case['keep'],monitor._details_match_contract({'title':case['title']},search,case),case['id'])

    def test_long_individual_alias_never_reaches_provider_truncation(self):
        search={'query':'x'*101,'_query_override':'x'*101,'_api_query_batch':True}
        with patch.object(monitor,'_get_ebay_api_token') as token,patch.object(monitor.urllib.request,'urlopen') as network:
            self.assertEqual(([],'api_query_too_long'),monitor.fetch_ebay_api_ex(search,force=True))
            token.assert_not_called()
            network.assert_not_called()
    def test_alias_batches_preserve_all_terms_without_provider_truncation(self):
        iphone=phone_aliases('iPhone 17 Pro Max')
        batches=api_query_batches(iphone)
        self.assertEqual(1,len(batches))
        self.assertEqual(iphone,stored_aliases(batches[0]))
        leading=phone_aliases('nubia z80 ultra leading')
        batches=api_query_batches(leading)
        self.assertEqual(2,len(batches))
        self.assertTrue(all(len(q)<=100 for q in batches))
        self.assertEqual(leading,[alias for q in batches for alias in (stored_aliases(q) or [q])])
        nested='rtx 4050 (aero,vivobook,spectre,yoga,xps,legion,proart)'
        self.assertEqual(['(rtx 4050 oled laptop,laptop 4050 oled)',nested],api_query_batches(['rtx 4050 oled laptop','laptop 4050 oled',nested]))

    def test_redmagic_batch_does_not_create_nested_alternatives(self):
        batch=api_query_batches(phone_aliases('redmagic 11 pro'))[0]
        self.assertEqual(batch,monitor._build_ebay_api_query({'query':'redmagic 11 pro','_query_override':batch,'_api_query_batch':True}))
        self.assertEqual(1,batch.count('('))
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
        search={'query':'nubia z80 ultra leading','filters':{}}
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor,'fetch_ebay_api_ex',side_effect=fetch),patch.dict(monitor._ebay_query_cache,{},clear=True):
            items,error=monitor.fetch_ebay_ex(search,force=True)
        self.assertIsNone(error)
        self.assertEqual('nubia z80 ultra leading',requests[0])
        self.assertEqual(phone_aliases(search['query']),[alias for q in requests for alias in (stored_aliases(q) or [q])])
        self.assertEqual(3,len(items))
    def test_alias_failure_is_visible_even_after_a_successful_primary(self):
        requests=[]
        def fetch(search,force=False):
            requests.append(search['_query_override'])
            if len(requests)==2:return [],'network'
            return [{'item_id':'primary','title':'iPhone 17 Pro Max','price':1000,'buy_now':True}],None
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor,'fetch_ebay_api_ex',side_effect=fetch) as request,patch.dict(monitor._ebay_query_cache,{},clear=True):
            items,error=monitor.fetch_ebay_ex({'query':'nubia z80 ultra leading','filters':{}},force=True)
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
        self.assertEqual(2,request.call_count)
        self.assertEqual(2,acquire.call_count)
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor,'_get_ebay_api_token',return_value=('test-token',None)),patch.object(monitor,'_allowed_api_targets_this_run',set()),patch.object(monitor.urllib.request,'urlopen') as request,patch.dict(monitor._ebay_query_cache,{},clear=True):
            items,error=monitor.fetch_ebay_ex(search)
        self.assertEqual('api_deferred',error)
        request.assert_not_called()
