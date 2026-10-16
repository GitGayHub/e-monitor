import asyncio,copy,json,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
import monitor
from test_parity import evaluate

class PhoneConversionTest(unittest.TestCase):
    def test_live_housing_and_controls_in_every_listing_format(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_conversion_oct16.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            for auction,offer in [(False,False),(False,True),(True,False),(True,True)]:
                with self.subTest(id=c['id'],auction=auction,offer=offer):
                    search={'id':'conversion-control','query':c['query'],'category':'phones','listingType':'auction' if auction else 'buy_now','bestOffer':offer,'condition':'any','maxPrice':1000,'enabled':True,'notify':True}
                    item={'item_id':c['id'],'title':c['title'],'price':700,'shipping_cost':6.19,'seller_name':'fixture','condition':'Gebraucht','location':'DE','buy_now':not auction,'auction':auction,'best_offer':offer}
                    self.assertEqual(c['titleAccepted'],evaluate({'search':search,'item':item,'settings':{'warn_non_eu':False}})[0])
                    cfg={'query':c['query'],'filters':{'category':'phones','listing_type':'auction' if auction else 'buy_now','best_offer':offer}}
                    details={'title':c['title'],'description':c['description'],'categoryId':'9355','condition':'Gebraucht','localizedAspects':c['aspects']}
                    self.assertEqual(c['accepted'],bool(monitor._details_match_contract(item,cfg,details)))

    def test_actual_housing_is_rejected_before_confirmed_send(self):
        c=json.loads((Path(__file__).parent/'qa/fixtures/phone_conversion_oct16.json').read_text(encoding='utf8'))['cases'][0]
        details=dict(title=c['title'],description=c['description'],categoryId='9355',localizedAspects=c['aspects'],price={'value':'700'})
        item=dict(item_id=c['id'],title=c['title'],price=700)
        search={'id':'conversion-control','query':c['query'],'filters':{'category':'phones','listing_type':'buy_now','limit_price':910}}
        with patch.object(monitor,'_fetch_item_details',return_value=details),patch.object(monitor,'send_notification',new=AsyncMock()) as send:
            accepted,_=asyncio.run(monitor._validate_candidate(item,search))
            self.assertFalse(accepted);self.assertEqual('rejected',item['_details_status'])
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(None,item,search,{},'initial')))
            send.assert_not_awaited()
