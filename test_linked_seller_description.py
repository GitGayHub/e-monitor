"""Independent18Oct browser page147635764543 uses a link, not an iframe."""
import unittest
from unittest.mock import Mock, MagicMock, patch
import sys
from bs4 import BeautifulSoup
import monitor
from ebay_access import MonitorPassBudget


class LinkedSellerDescriptionTests(unittest.TestCase):
    item_id = '147635764543'
    body = '<p>Samsung Galaxy S24 Ultra SM-S928B/DS,12GB /256GB.</p><p>Leichte Schäden im Displayglas. Schäden am Backcover.</p>'

    def test_browser_timeout_reports_stage_without_retrying_or_accepting(self):
        page=Mock();page.goto.side_effect=TimeoutError()
        browser=Mock();browser.new_page.return_value=page
        runtime=Mock();runtime.chromium.launch.return_value=browser
        context=MagicMock();context.__enter__.return_value=runtime
        module=Mock();module.sync_playwright.return_value=context
        with patch.dict(sys.modules,{'playwright.sync_api':module}),patch.dict('os.environ',{'EBAY_HTML_PLAYWRIGHT':'1'}),patch.object(monitor.logger,'warning') as warning:
            result=monitor._fetch_item_details_browser(self.item_id)
        self.assertIsNone(result)
        page.goto.assert_called_once()
        browser.close.assert_called_once()
        self.assertEqual(('TimeoutError','item_page'),warning.call_args.args[2:4])

    def page(self, url):
        return '<h1 class="x-item-title">Samsung Galaxy S24 Ultra SM-S928B/DS</h1><div class="x-price-primary">EUR380,00</div><a href="'+url+'">Zur vollständigen Artikelbeschreibung</a>'

    def test_real_http_full_description_link_is_read_over_https(self):
        url='http://itm.ebaydesc.com/itmdesc/'+self.item_id+'?t=0&category=9355&seller=moesyzlake&secureDesc=0'
        session=Mock();session.get.return_value=Mock(status_code=200,text=self.body)
        details=monitor._parse_item_details_html(self.page(url),session=session,item_id=self.item_id)
        self.assertIn('Schäden am Backcover',details['description'])
        self.assertTrue(monitor._is_description_blocked(details['description'],'phones'))
        self.assertEqual('https:'+url.split(':',1)[1],session.get.call_args.args[0])
        session.get.assert_called_once()

    def test_only_own_description_is_selected_not_recommendation_or_other_server(self):
        valid='https://itm.ebaydesc.com/itmdesc/'+self.item_id
        for bad in ('https://itm.ebaydesc.com/itmdesc/123456789012','https://ebaydesc.com.evil.example/itmdesc/'+self.item_id,'https://user@itm.ebaydesc.com/itmdesc/'+self.item_id,'https://itm.ebaydesc.com:8080/itmdesc/'+self.item_id,'http://127.0.0.1/itmdesc/'+self.item_id):
            session=Mock();session.get.return_value=Mock(status_code=200,text=self.body)
            page=self.page(bad)+self.page(valid)
            details=monitor._parse_item_details_html(page,session=session,item_id=self.item_id)
            self.assertIn('Schäden am Backcover',details['description'])
            self.assertEqual(valid,session.get.call_args.args[0])
            session.get.assert_called_once()

    def test_protocol_relative_and_legacy_own_links(self):
        for raw,expected in [('//itm.ebaydesc.com/itmdesc/'+self.item_id,'https://itm.ebaydesc.com/itmdesc/'+self.item_id),('https://vi.vipr.ebaydesc.com/ws/eBayISAPI.dll?ViewItemDescV4&item='+self.item_id,'https://vi.vipr.ebaydesc.com/ws/eBayISAPI.dll?ViewItemDescV4&item='+self.item_id)]:
            self.assertEqual(expected,monitor._linked_seller_description_url(BeautifulSoup(self.page(raw),'html.parser'),self.item_id))
        self.assertIsNone(monitor._linked_seller_description_url(BeautifulSoup(self.page('//itm.ebaydesc.com/itmdesc/'+self.item_id),'html.parser'),None))

    def test_error_or_challenge_is_not_verified_and_deadline_does_not_fetch(self):
        page=self.page('https://itm.ebaydesc.com/itmdesc/'+self.item_id)
        for status,body in [(503,'Unavailable'),(200,'<title>Pardon Our Interruption</title>Verify you are a human')]:
            session=Mock();session.get.return_value=Mock(status_code=status,text=body)
            parsed=monitor._parse_item_details_html(page,session=session,item_id=self.item_id)
            self.assertFalse(monitor._clean_description(parsed['description']))
        session=Mock();token=MonitorPassBudget.current.set(MonitorPassBudget(0))
        try:
            parsed=monitor._parse_item_details_html(page,session=session,item_id=self.item_id)
            self.assertFalse(monitor._clean_description(parsed['description']))
            session.get.assert_not_called()
        finally:MonitorPassBudget.current.reset(token)

    def test_lazy_iframe_data_src_still_reads_full_description(self):
        url='https://itm.ebaydesc.com/itmdesc/'+self.item_id
        session=Mock();session.get.return_value=Mock(status_code=200,text=self.body)
        details=monitor._parse_item_details_html('<iframe id="desc_ifr" data-src="'+url+'"></iframe>',session=session,item_id=self.item_id)
        self.assertIn('Schäden am Backcover',details['description'])
        session.get.assert_called_once()

    def test_browser_link_keeps_prices_from_own_item_page_and_stops_on_challenge(self):
        url='https://itm.ebaydesc.com/itmdesc/'+self.item_id
        own=self.page(url)
        for body,expected in [(self.body,True),('<title>Pardon Our Interruption</title>',False)]:
            page=Mock();page.url='https://www.ebay.de/itm/'+self.item_id
            page.content.side_effect=[own,own,body]
            page.locator.return_value.count.return_value=0
            page.locator.return_value.inner_html.return_value=body
            browser=Mock();browser.new_page.return_value=page
            runtime=Mock();runtime.chromium.launch.return_value=browser
            context=MagicMock();context.__enter__.return_value=runtime
            module=Mock();module.sync_playwright.return_value=context
            with patch.dict(sys.modules,{'playwright.sync_api':module}),patch.dict('os.environ',{'EBAY_HTML_PLAYWRIGHT':'1'}):
                details=monitor._fetch_item_details_browser(self.item_id)
            self.assertEqual(expected,bool(details))
            self.assertEqual(url,page.goto.call_args.args[0])
            if details:
                self.assertEqual('Samsung Galaxy S24 Ultra SM-S928B/DS',details['title'])
                self.assertIn('Schäden am Backcover',details['description'])
            browser.close.assert_called_once()
