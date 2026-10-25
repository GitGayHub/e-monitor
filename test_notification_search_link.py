import asyncio,copy,io,json,unittest
from unittest.mock import Mock,AsyncMock,patch
from urllib.parse import urlsplit,parse_qs
import monitor
from mobile import feed_writer

class NotificationSearchLinkTest(unittest.TestCase):
    def search(self):
        return {'id':'link-test','query':'playstation 5 pro','filters':{'category':'consoles','listing_type':'auction','best_offer':True,'condition':'used','location':'de','min_price':300,'max_price':2500,'limit_price':750}}

    def test_html_button_keeps_actual_alias_and_filters_after_settings_change(self):
        s=self.search();s['query']='ps5 pro'
        with patch.object(monitor.config,'get_settings',return_value={'user_zip':'09648'}):
            url=monitor._build_url_with_host('ebay.de',s,sub='m')
            item=monitor._stamp_search_origin([{}],'html',url,s['query'])[0]
            s['query']='unrelated new query';s['filters']['min_price']=999
            link=monitor._notification_search_url(item,s)
        self.assertEqual(url,link)
        params=parse_qs(urlsplit(link).query)
        self.assertEqual(['ps5 pro'],params['_nkw']);self.assertEqual(['1'],params['LH_Auction']);self.assertEqual(['1'],params['LH_BO'])
        self.assertEqual(['300'],params['_udlo']);self.assertEqual(['2500'],params['_udhi']);self.assertEqual(['3000'],params['LH_ItemCondition'])
        self.assertEqual('ps5 pro',item['_search_query'])

    def test_api_link_uses_executed_query_not_unapplied_html_aspects(self):
        s=self.search();s['query']='iphone17promax';s['filters'].update(category='phones',condition='any')
        params=monitor._build_ebay_api_params(s,market='EBAY_DE');params['q']='apple iphone 17 pro max'
        with patch.object(monitor.config,'get_settings',return_value={}):
            url=monitor._api_public_search_url(s,'EBAY_DE',params)
        item=monitor._stamp_search_origin([{}],'api',url,params['q'])[0]
        link=monitor._notification_search_url(item,s)
        self.assertEqual(url,link)
        query=parse_qs(urlsplit(link).query)
        self.assertEqual([params['q']],query['_nkw']);self.assertEqual([params['category_ids']],query['_sacat'])
        self.assertNotIn('Modell',query);self.assertNotIn('_dcat',query);self.assertNotIn('LH_ItemCondition',query);self.assertNotIn('LH_BO',query)
        self.assertNotIn('api.ebay.com',url)

    def test_fetch_records_request_origin_and_feed_preserves_it(self):
        s=self.search();data={'itemSummaries':[{'itemId':'v1|123|0','title':'PlayStation 5 Pro','price':{'value':'600','currency':'EUR'},'buyingOptions':['AUCTION']}]}
        with patch.object(monitor,'_get_ebay_api_token',return_value=('secret-test-token',None)),patch.object(monitor.browse_access,'acquire',return_value=True),patch.object(monitor,'record_search_run'),patch.object(monitor.config,'get_settings',return_value={}),patch.object(monitor.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(data).encode())):
            items,err=monitor.fetch_ebay_api_ex(s,force=True)
        self.assertIsNone(err);item=items[0]
        self.assertEqual('api',item['source']);self.assertTrue(item['_search_url'].startswith('https://www.ebay.de/sch/i.html?'))
        self.assertNotIn('secret-test-token',item['_search_url'])
        entry=feed_writer.build_entry(item,s)
        self.assertEqual(item['_search_url'],entry['searchUrl']);self.assertEqual('api',entry['searchSource']);self.assertEqual(item['_search_query'],entry['executedQuery'])

    def test_notification_passes_real_button_to_photo_and_text_delivery(self):
        bot=Mock();bot.get_me=AsyncMock(return_value=Mock(username='test'))
        s=self.search();item={'item_id':'123456789012','title':'PlayStation 5 Pro','price':600,'shipping_cost':6.19,'total_price':606.19,'seller_name':'fixture','condition':'Gebraucht','location':'DE','auction':True,'buy_now':False,'best_offer':True,'source':'html','_search_url':'https://m.ebay.de/sch/i.html?_nkw=ps5+pro&LH_Auction=1'}
        with patch.object(monitor,'safe_send_telegram',new=AsyncMock(return_value=Mock(message_id=1))) as send:
            self.assertTrue(asyncio.run(monitor.send_notification(bot,item,s)))
        keyboard=send.await_args.kwargs['keyboard'];self.assertEqual('https://www.ebay.de/itm/123456789012',keyboard.inline_keyboard[0][0].url)
        self.assertEqual('🔗 Открыть объявление',keyboard.inline_keyboard[0][0].text)
        self.assertIn('>Поиск: eBay HTML</a>',send.await_args.args[2])
        self.assertIn('href="https://m.ebay.de/sch/i.html?_nkw=ps5+pro&amp;LH_Auction=1"',send.await_args.args[2])
        for photo in (True,False):
            sink=Mock();sink.send_message=AsyncMock(return_value=Mock(message_id=1));sink.send_photo=AsyncMock(return_value=Mock(message_id=2))
            asyncio.run(monitor.safe_send_telegram(sink,1,'test',img='https://example.invalid/image.jpg' if photo else None,keyboard=keyboard))
            target=sink.send_photo if photo else sink.send_message
            self.assertEqual(keyboard,target.await_args.kwargs['reply_markup'])

    def test_untrusted_or_private_urls_cannot_be_sent_as_search_button(self):
        for url in ('https://api.ebay.com/buy/browse/v1/item_summary/search?q=phone','https://www.ebay.de.evil.invalid/sch/i.html?_nkw=phone','https://www.ebay.de@evil.invalid/sch/i.html?_nkw=phone','https://www.ebay.de/sch/i.html?_nkw=phone&access_token=secret','https://www.ebay.de/signin?_nkw=phone','javascript:alert(1)','https://www.ebay.de:443/sch/i.html?_nkw=phone'):
            self.assertIsNone(monitor._safe_public_search_url(url))
