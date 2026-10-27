import asyncio, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, Mock
import price_history, config_manager

# Importing the monitor can initialise history; isolate direct test runs too.
with tempfile.TemporaryDirectory() as folder, \
        patch.object(price_history,'DB_PATH',str(Path(folder)/'history.db')), \
        patch.object(config_manager,'CONFIG_PATH',str(Path(folder)/'config.json')):
    import monitor


class LiveBidHistoryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        db=patch.object(price_history,'DB_PATH',str(Path(folder.name)/'history.db'));db.start();self.addCleanup(db.stop)

    def test_purchases_offers_and_bids_are_independent_and_hybrid_prices_projected(self):
        rows=[{'buy_now':True,'auction':False,'best_offer':False,'total_price':1000},
              {'buy_now':True,'auction':False,'best_offer':True,'total_price':900},
              {'buy_now':False,'auction':True,'best_offer':True,'total_price':568.28},
              {'buy_now':False,'auction':True,'best_offer':False,'total_price':1.01},
              {'buy_now':True,'auction':True,'best_offer':True,'total_price':1200,'bin_total_price':1200,'auc_total_price':80}]
        with patch.object(monitor,'is_outlier',return_value=False) as outlier:
            fixed,offers,bids=monitor._market_history_prices(rows,'isolated-live-bid')
        self.assertEqual([1000,900,1200],fixed)
        self.assertEqual([900,1200],offers)
        self.assertEqual([568.28,1.01,80],bids)
        self.assertEqual(3,outlier.call_count)
        price_history.record_snapshot('isolated-live-bid',fixed,offers,bids,verified=True,validation_complete=True)
        self.assertEqual(1000,price_history.get_median_7d('isolated-live-bid'))
        stats=price_history.get_stats_7d('isolated-live-bid')
        self.assertEqual(80,stats['median_auction'])
        self.assertEqual(1.01,stats['min_auction'])

    def test_auction_offer_is_current_bid_not_discount_or_known_offer_price(self):
        item={'item_id':'auction-offer-qa','title':'Apple iPhone 17 Pro Max 512GB','price':562.09,'shipping_cost':6.19,'total_price':568.28,
              'buy_now':False,'auction':True,'best_offer':True,'bids_count':0,'time_left':'6д 23ч 46мин','seller_name':'qa','condition':'Neu','location':'DE'}
        search={'id':'isolated-bid','query':'iphone 17 pro max','filters':{'category':'phones','limit_price':910}}
        bot=Mock();bot.get_me=AsyncMock(return_value=Mock(username='isolated'))
        for offer in (False,True):
            item['best_offer']=offer
            with patch.object(monitor,'is_outlier',return_value=True) as outlier,patch.object(monitor,'safe_send_telegram',new=AsyncMock(return_value=Mock(message_id=1))) as sender:
                self.assertTrue(asyncio.run(monitor.send_notification(bot,item,search,{'median':730,'first_date':'2026-10-06','last_date':'2026-10-13'})))
                text=sender.await_args.args[2]
            outlier.assert_not_called()
            self.assertIn('Текущая ставка + доставка',text)
            self.assertIn('568.28€',text)
            self.assertNotIn('Скидка',text)
            self.assertNotIn('ниже медианы',text)
            self.assertNotIn('Подозрительно низкая',text)
            self.assertNotIn('Цена предложения продавцу неизвестна',text)
            self.assertNotIn('текущая ставка не является ценой покупки',text)

    def test_fixed_price_compares_total_with_purchase_median(self):
        item={'item_id':'fixed-qa','title':'Sony DualSense','price':80,'shipping_cost':20,'total_price':100,'buy_now':True,'auction':False,'best_offer':True,'seller_name':'qa','condition':'Gebraucht','location':'DE'}
        bot=Mock();bot.get_me=AsyncMock(return_value=Mock(username='isolated'))
        with patch.object(monitor,'is_outlier',return_value=False) as outlier,patch.object(monitor,'safe_send_telegram',new=AsyncMock(return_value=Mock(message_id=1))) as sender:
            asyncio.run(monitor.send_notification(bot,item,{'id':'qa','query':'dualsense','filters':{}},{'median':120,'first_date':'a','last_date':'b'}))
        outlier.assert_called_once()
        self.assertEqual((100,'qa'),outlier.call_args.args[:2])
        self.assertEqual(64,len(outlier.call_args.args[2]))
        text=sender.await_args.args[2]
        self.assertIn('100.00€ — на 17%',text)
        self.assertNotIn('на 33%',text)

    def test_missing_current_history_is_visible_without_changing_auction_messages(self):
        item={'item_id':'fixed-qa','title':'Sony DualSense','price':80,'shipping_cost':20,'total_price':100,'buy_now':True,'auction':False,'best_offer':False,'seller_name':'qa','condition':'Gebraucht','location':'DE'}
        bot=Mock();bot.get_me=AsyncMock(return_value=Mock(username='isolated'))
        search={'id':'qa','query':'dualsense','filters':{}}
        for stats, expected in [(None,True),({'median':120,'first_date':'a','last_date':'b','purchase_snapshots':2},True),
                                ({'median':120,'first_date':'a','last_date':'b','purchase_snapshots':3},False)]:
            with self.subTest(stats=stats), patch.object(monitor,'is_outlier',return_value=False), patch.object(monitor,'safe_send_telegram',new=AsyncMock(return_value=Mock(message_id=1))) as sender:
                self.assertTrue(asyncio.run(monitor.send_notification(bot,item,search,stats)))
                self.assertEqual(expected,'Истории цен пока недостаточно' in sender.await_args.args[2])
        item.update(buy_now=False,auction=True)
        with patch.object(monitor,'safe_send_telegram',new=AsyncMock(return_value=Mock(message_id=1))) as sender:
            self.assertTrue(asyncio.run(monitor.send_notification(bot,item,search,None)))
            self.assertNotIn('Истории цен пока недостаточно',sender.await_args.args[2])

    def test_user_screenshot_parts_cannot_notify_even_with_empty_seen(self):
        item={'item_id':'237099772350','title':'Logitech X Superlight 2 Ersatzkufen für Maus','price':13.91,'shipping_cost':6.06,'total_price':29.56,
              'buy_now':True,'auction':False,'best_offer':False,'seller_name':'polarsector','location':'GB','condition':'Neu'}
        cfg=Mock();cfg.get_settings.return_value={'warn_non_eu':True};cfg.get_global_banned_sellers.return_value=[];cfg.get_banned_item_ids.return_value=set();cfg.get_item_hashes.return_value=set()
        search={'id':'isolated-skates','query':'logitech superlight 2','filters':{'category':'mice','limit_price':45,'listing_type':'all'}}
        details={'title':item['title'],'description':'Logitech X Superlight 2 Patins De Remplacement Pour Souris. 1 jeu de pieds inclus par achat. Remplace les pieds de souris existants.','categoryId':'3676','buyingOptions':['FIXED_PRICE'],'price':{'value':'13.91'},'itemLocation':{'country':'GB'}}
        with patch.object(monitor,'config',cfg),patch.object(monitor,'seen_state',{}),patch.object(monitor,'save_seen_ids') as seen,patch.object(monitor,'_fetch_item_details',return_value=details),patch.object(monitor,'send_notification',new=AsyncMock()) as send:
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(None,item,search,None,'initial')))
        send.assert_not_called();seen.assert_not_called()
