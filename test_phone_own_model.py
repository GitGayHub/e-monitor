import asyncio,json,unittest
from pathlib import Path
from unittest.mock import Mock,patch,AsyncMock
import monitor

class OwnPhoneModelTests(unittest.TestCase):
    def test_shared_own_statements_and_context_in_every_format(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_own_model_oct20.json').read_text(encoding='utf8'))
        for c in cases:
          for auction in (False,True):
           for offer in (False,True):
            with self.subTest(case=c['id'],auction=auction,offer=offer):
                d=dict(title=c['title'],description=c['description'],price=dict(value='500',currency='EUR'),buyingOptions=(['AUCTION'] if auction else ['FIXED_PRICE'])+(['BEST_OFFER'] if offer else []),localizedAspects=[dict(name='Modell',value=c['title'])],itemEndDate='2099-01-01T00:00:00Z')
                if auction:d['currentBidPrice']=dict(value='500',currency='EUR')
                actual=bool(monitor._details_match_contract(dict(item_id='123456789001',title=c['title']),dict(query=c['query'],filters=dict(category='phones')),d))
                self.assertEqual(c['expected'],actual)

    def test_own_conflict_cannot_reach_the_verified_notification_callback(self):
        cfg=Mock();cfg.get_settings.return_value=dict(user_zip='09648',non_eu_tax_rate=.19,warn_non_eu=False)
        cfg.get_global_banned_sellers.return_value=set();cfg.get_banned_item_ids.return_value=set();cfg.get_item_hashes.return_value=set()
        search=dict(id='qa',query='iphone 17 pro max',filters=dict(category='phones',listing_type='buy_now',limit_price=910))
        item=dict(item_id='123456789001',title='Apple iPhone 17 Pro Max',price=900,shipping=6.19,currency='EUR',seller_name='qa',location='Deutschland',condition='Gebraucht',buy_now=True,auction=False,best_offer=False)
        details=dict(title=item['title'],description='iPhone 7 Pro Max 256 GB. Complete working phone.',price=dict(value='900',currency='EUR'),buyingOptions=['FIXED_PRICE'],shippingOptions=[dict(shippingCost=dict(value='6.19',currency='EUR'))])
        callback=AsyncMock()
        with patch.object(monitor,'config',cfg),patch.object(monitor,'_fetch_item_details',return_value=details):
            self.assertEqual([],asyncio.run(monitor._verified_history([item],search,on_verified=callback)))
        callback.assert_not_awaited()
