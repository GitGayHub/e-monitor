import io,json,unittest
from pathlib import Path
from unittest.mock import patch
import monitor

class EuroMoneyTest(unittest.TestCase):
    def test_api_shipping_regions_and_destination_quotes(self):
        for c in json.loads((Path(__file__).parent/'qa/fixtures/api_shipping_quote_oct23.json').read_text()):
            with self.subTest(case=c['id']),patch.object(monitor,'EBAY_MARKETPLACE_ID','EBAY_FR' if c['country']=='FR' else 'EBAY_DE'):
                self.assertEqual(c['complete'],monitor._provider_details_complete(c['data']))
    def test_shipping_without_a_destination_quote_is_not_free(self):
        for c in json.loads((Path(__file__).parent/'qa/fixtures/shipping_unconfirmed_oct23.json').read_text(encoding='utf8')):
            with self.subTest(case=c['id']):
                d=monitor._parse_item_details_html(c['html'],description=c['description'])
                self.assertEqual(c['complete'],monitor._provider_details_complete(d))
                self.assertEqual(c['shipping'],monitor._api_float(d.get('htmlShippingCost')))

    def test_shared_quotes(self):
        for c in json.loads((Path(__file__).parent/'qa/fixtures/euro_money_oct17.json').read_text(encoding='utf8'))['text']:
            with self.subTest(text=c['text']):
                self.assertEqual(c['eur'],monitor._parse_price(c['text']))

    def test_own_polish_auction_quote_and_shipping(self):
        fixture=json.loads((Path(__file__).parent/'qa/fixtures/euro_money_oct17.json').read_text(encoding='utf8'))
        d=monitor._parse_item_details_html(fixture['html'],description='New unused phone with complete set.')
        self.assertEqual(858.22,monitor._api_float(d['price']))
        self.assertEqual(858.22,monitor._api_float(d['currentBidPrice']))
        self.assertEqual(24.95,monitor._api_float(d['htmlShippingCost']))
        self.assertAlmostEqual(883.17,monitor._api_float(d['price'])+monitor._api_float(d['htmlShippingCost']))
        self.assertEqual(['AUCTION'],d['buyingOptions'])

    def test_other_listing_conversion_cannot_certify_unknown_bid(self):
        d=monitor._parse_item_details_html('<div><div class="x-price-primary">3.750,00 PLN</div></div><aside><div class="x-price-approx">EUR 858,22</div></aside><button class="ux-call-to-action">Bieten</button>',description='Complete phone.')
        self.assertFalse(monitor._provider_details_complete(d))

    def test_unsupported_money_and_paid_shipping(self):
        for value in (True,-1,'NaN','Infinity'):
            self.assertIsNone(monitor._api_float({'value':value,'currency':'EUR'}))
        self.assertIsNone(monitor._api_float({'value':3750,'currency':'PLN'}))
        self.assertEqual(24.95,monitor._parse_shipping('109,00 PLN (ca. EUR 24,95)'))
        self.assertEqual(6.19,monitor._parse_shipping('EUR 6,19 Versand; kostenlose Abholung'))
        self.assertIsNone(monitor._parse_shipping('109,00 PLN Versand'))
        self.assertFalse(monitor._provider_details_complete({'description':'Complete phone.','price':{'value':'600','currency':'EUR'},'shippingOptions':[{'shippingCost':{'value':'109','currency':'PLN'}}]}))

    def test_unknown_shipping_quote_and_hybrid_bid_stay_unverified(self):
        d=monitor._parse_item_details_html('<div class="x-price-primary">EUR 600,00</div><div class="ux-labels-values--shipping">Versand: 109,00 PLN</div>',description='Complete phone.')
        self.assertFalse(monitor._provider_details_complete(d))
        hybrid='<script type="application/ld+json">{"@type":"Product","offers":{"price":1000,"priceCurrency":"EUR"}}</script><div><div class="x-price-primary">Aktuelles Gebot 3750,00 PLN</div><div class="x-price-approx">EUR 1000,00</div></div><button class="ux-call-to-action">Bieten</button><button class="ux-call-to-action">Sofort-Kaufen</button>'
        d=monitor._parse_item_details_html(hybrid,description='Complete phone.')
        self.assertEqual(1000,monitor._api_float(d['price']))
        self.assertIsNone(d.get('currentBidPrice'))

    def test_nonempty_api_with_unsupported_units_is_parse_error(self):
        good={'itemId':'v1|123|0','title':'Phone','price':{'value':'600','currency':'EUR'},'buyingOptions':['FIXED_PRICE']}
        bad={**good,'price':{'value':'3750','currency':'PLN'}}
        for data,expected,error in (({'itemSummaries':[]},0,None),({'itemSummaries':[bad]},0,'parse'),({'itemSummaries':[good,bad]},1,'parse')):
            with patch.object(monitor,'_get_ebay_api_token',return_value=('test',None)),patch.object(monitor.browse_access,'acquire',return_value=True),patch.object(monitor,'record_search_run'),patch.object(monitor.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(data).encode())):
                items,err=monitor.fetch_ebay_api_ex({'query':'phone','filters':{}},force=True)
                self.assertEqual(expected,len(items));self.assertEqual(error,err)
