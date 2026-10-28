import json,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import monitor

class DescriptionProtectionTests(unittest.TestCase):
    def test_protection_is_missing_description_in_all_formats(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/description_protection_oct16.json').read_text(encoding='utf8'))
        title='Apple iPhone 16 Pro Max 256GB Smartphone'
        for c in cases:
            self.assertEqual(c['accepted'],bool(monitor._clean_description(c['description']).strip()),c['id'])
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                search={'query':'iphone 16 pro max','filters':{'category':'phones','listing_type':listing,'best_offer':offer}}
                d={'title':title,'description':c['description'],'condition':'Gebraucht','categoryId':'9355','price':{'value':'400'}}
                self.assertEqual(c['accepted'],monitor._provider_details_complete(d),c['id'])
                self.assertEqual(c['accepted'],monitor._details_match_contract({'title':title,'item_id':c['id']},search,d),(c['id'],listing,offer))

    def test_description_http_error_and_challenge_are_separate_and_never_seller_text(self):
        page='<h1 class="x-item-title">Apple iPhone 16 Pro Max 256GB</h1><div class="x-price-primary">EUR 400,00</div><iframe id="desc_ifr" src="https://itm.ebaydesc.com/itmdesc/123"></iframe>'
        for status,body,reason in [(403,'Forbidden','seller_description_http'),(200,'<title>Pardon Our Interruption</title>Verify you are a human','seller_description_challenge')]:
            monitor._item_details_events.pop('123',None)
            session=Mock();session.get.return_value=Mock(status_code=status,text=body,url='https://itm.ebaydesc.com/itmdesc/123')
            details=monitor._parse_item_details_html(page,session=session,item_id='123')
            self.assertFalse(monitor._clean_description(details['description']))
            self.assertFalse(monitor._provider_details_complete(details))
            self.assertIn(reason,[e['reason'] for e in monitor.item_details_diagnostics('123')['events']])
            if status==403:self.assertEqual(403,monitor.item_details_diagnostics('123')['events'][0]['httpStatus'])

    def test_page_challenge_stops_without_automating_captcha(self):
        session=Mock();session.get.return_value=Mock(status_code=200,url='https://www.ebay.de/splashui/captcha',text='<title>Pardon Our Interruption</title>')
        with patch.object(monitor,'_get_ebay_session',return_value=session),patch.object(monitor,'EBAY_SOURCE','html'),patch.object(monitor,'_item_details_cache',{}),patch.object(monitor,'_fetch_item_details_browser') as browser:
            self.assertIsNone(monitor._fetch_item_details('diagnostic-control'))
        self.assertEqual('html_challenge',monitor.item_details_diagnostics('diagnostic-control')['events'][-1]['reason'])
        browser.assert_not_called();self.assertEqual(1,session.get.call_count)

    def test_expired_deadline_prevents_new_browser_and_iframe_requests(self):
        from ebay_access import MonitorPassBudget
        token=MonitorPassBudget.current.set(MonitorPassBudget(0))
        session=Mock()
        try:
            page='<iframe id="desc_ifr" src="https://itm.ebaydesc.com/itmdesc/123"></iframe>'
            parsed=monitor._parse_item_details_html(page,session=session,item_id='123')
            self.assertFalse(monitor._clean_description(parsed['description']))
            session.get.assert_not_called()
            self.assertIn('seller_description_deadline',[e['reason'] for e in monitor.item_details_diagnostics('123')['events']])
            self.assertEqual(([],'pass_deferred'),monitor._do_fetch_playwright('https://www.ebay.de/sch/i.html?_nkw=qa'))
        finally:
            MonitorPassBudget.current.reset(token)
