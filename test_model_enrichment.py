import asyncio
import copy
import unittest
from unittest.mock import Mock,patch
import monitor

class ModelEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.config=Mock()
        self.config.get_settings.return_value=dict(user_zip='09648',warn_non_eu=False,non_eu_tax_rate=.19)
        self.config.get_global_banned_sellers.return_value=set()
        self.config.get_banned_item_ids.return_value=set()
        self.config.get_item_hashes.return_value=set()
        self.item=dict(item_id='123456789001',title='Logitech G PRO X Superlight 2 Gaming Maus',price=80,shipping=0,total_price=80,currency='EUR',seller_name='qa',seller_rating_count=100,seller_rating_percent=100,condition='Gebraucht',location='Deutschland',buy_now=True,auction=False,best_offer=False,url='https://www.ebay.de/itm/123456789001')

    def details(self,mpn,body='Complete working Logitech Superlight 2 mouse.',title=None):
        return dict(title=title or self.item['title'],description=body,price=dict(value='80',currency='EUR'),buyingOptions=['FIXED_PRICE'],shippingOptions=[dict(shippingCost=dict(value='0',currency='EUR'))],localizedAspects=[dict(name='Herstellernummer',value=mpn),dict(name='Modell',value='Logitech Superlight 2')])

    def search(self,suffix='c'):
        return dict(id='qa',query='logitech superlight 2'+suffix,filters=dict(category='mice',listing_type='all',limit_price=100),include_words=['2c','2 c','compact'] if suffix=='c' else [])

    def test_missing_suffix_reaches_own_details_then_can_pass_all_formats(self):
        for suffix,mpn in [('c','910-007531'),(' se','910-007555'),(' dex','910-007358')]:
          for auction in (False,True):
           for offer in (False,True):
            with self.subTest(suffix=suffix,auction=auction,offer=offer),patch.object(monitor,'config',self.config):
                search=self.search(suffix);item=copy.deepcopy(self.item);item.update(auction=auction,buy_now=not auction,best_offer=offer)
                self.assertEqual([],monitor.filter_results([item],search,self.config,skip_seen=True,is_statistics=True))
                candidates=monitor._history_candidates([item],search)
                self.assertEqual(1,len(candidates),'Ambiguous model must reach own-details validation')
                d=self.details(mpn);d['buyingOptions']=(['AUCTION'] if auction else ['FIXED_PRICE'])+(['BEST_OFFER'] if offer else [])
                if auction:d['currentBidPrice']=dict(value='80',currency='EUR')
                with patch.object(monitor,'_fetch_item_details',return_value=d):
                    valid,_=asyncio.run(monitor._validate_candidate(candidates[0],search))
                self.assertTrue(valid)
                self.assertEqual(self.item['title'],candidates[0]['title'])
                self.assertEqual(1,len(monitor.filter_results(candidates,search,self.config,skip_seen=True,is_statistics=True)))

    def test_unknown_or_conflicting_evidence_never_confirms_a_variant(self):
        with patch.object(monitor,'config',self.config):
          for d in [self.details(''),self.details('910-999999'),self.details('910-007555'),self.details('910-007531',title='Logitech Superlight 2 DEX Gaming Maus'),self.details('910-007531',body='The mouse is broken.'),self.details('910-007531',body='')]:
            item=copy.deepcopy(self.item)
            with self.subTest(details=d),patch.object(monitor,'_fetch_item_details',return_value=d):
                valid,_=asyncio.run(monitor._validate_candidate(item,self.search()))
                self.assertFalse(valid)

    def test_accessory_and_explicit_other_variant_do_not_gain_pending_model_status(self):
        with patch.object(monitor,'config',self.config):
          for title in ['Logitech Superlight 2 DEX Gaming Maus','Logitech Superlight 1 Gaming Maus','Ersatzkufen für Logitech Superlight 2','Logitech Superlight 2 PCB Ersatzteil','Logitech Superlight 2 Maus defekt']:
            item=dict(self.item,title=title)
            self.assertEqual([],monitor._history_candidates([item],self.search()),title)
