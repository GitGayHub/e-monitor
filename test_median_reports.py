import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import price_history
from mobile import median_reports as m
from mobile import build_app_sync as build, merge_app_sync_to_config as merge


class MedianReportsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch=patch.object(price_history,'DB_PATH',str(Path(self.temp.name)/'history.db'))
        self.patch.start();self.addCleanup(self.patch.stop)
        self.now=20000*m.DAY+3600
        self.config=dict(searches=[dict(id='iphone',query='iPhone 17 Pro Max',enabled=True,filters={})],
                         settings=dict(median_products=['iphone'],median_interval_days=7))
        self.bot=Mock(token='test-only-route',send_photo=AsyncMock(return_value=Mock(message_id=12)),
                      send_message=AsyncMock(return_value=Mock(message_id=13)))
        self.store=m.DeliveryStore(Path(self.temp.name)/'delivery.json',remote=False)

    def row(self, item='one', price=1000, **changes):
        return dict(item_id=item,total_price=price,buy_now=True,auction=False,_details_status='verified',
                    _details_verified_at=self.now,**changes)

    def seed(self, prices=(900,920,940,960,980,1000), day=0, search='iphone', signature='sig'):
        m.record_verified(search,signature,[self.row(str(i),p) for i,p in enumerate(prices)],self.now-day*m.DAY)

    def test_unknown_description_live_bid_import_estimate_and_missing_hybrid_bin_are_excluded(self):
        rows=[self.row()]
        for updates in [dict(_details_status='unavailable'),dict(_details_verified_at=None),dict(buy_now=False,auction=True),
                        dict(import_estimated=True),dict(auction=True),dict(total_price=float('nan')),dict(total_price=True)]:
            row=self.row();row.update(updates);rows.append(row)
        self.assertEqual(1,m.record_verified('iphone','sig',rows,self.now))
        self.assertEqual(1,m.trend({'iphone':'sig'},self.now)['count'])

    def test_hybrid_known_purchase_total_never_uses_current_bid(self):
        row=self.row();row.update(auction=True,total_price=10,bin_total_price=1010)
        m.record_verified('iphone','sig',[row],self.now)
        with price_history._connect() as db:
            self.assertEqual(1010,db.execute('select total from median_observations').fetchone()[0])

    def test_one_wrong_case_and_one_extreme_asking_price_do_not_distort_median(self):
        result=m.robust_median([100,900,920,940,960,980,1000,5000])
        self.assertEqual(950,result['median']);self.assertEqual(2,result['excluded']);self.assertEqual(6,result['count'])

    def test_small_or_trimmed_sample_is_explicitly_insufficient(self):
        self.assertIsNone(m.robust_median([100,900,1000])['median'])
        self.assertIsNone(m.robust_median([100,900,920,940,960])['median'])

    def test_gradual_market_change_is_not_blocked_by_an_old_price_floor(self):
        self.assertEqual(650,m.robust_median([630,640,650,660,670])['median'])

    def test_daily_alias_and_cross_day_duplicates_get_one_vote_per_listing(self):
        self.seed()
        for n in range(20):
            m.record_verified('iphone','sig',[self.row('0',900)],self.now-1)
        m.record_verified('other','alias',[self.row('0',900)],self.now-1)
        self.seed(day=1)
        result=m.trend({'iphone':'sig','other':'alias'},self.now)
        self.assertEqual(6,result['count']);self.assertEqual(950,result['median'])

    def test_changed_filters_old_rules_future_and_expired_prices_are_not_reused(self):
        self.seed(day=8);self.seed(signature='old');self.seed(day=-1)
        self.assertIsNone(m.trend({'iphone':'sig'},self.now)['median'])
        self.seed()
        with patch.object(price_history,'HISTORY_VERSION',999):
            self.assertIsNone(m.trend({'iphone':'sig'},self.now)['median'])

    def test_trend_uses_verified_window_and_keeps_missing_days_as_gaps(self):
        self.seed(day=8);self.seed(prices=[800,820,840,860,880,900])
        data=m.trend({'iphone':'sig'},self.now)
        self.assertEqual(850,data['median'])
        self.assertTrue(any(p['median'] is None for p in data['points']))
        text=m.caption('<iPhone>',data,7)
        self.assertIn('&lt;iPhone&gt;',text);self.assertIn('-10.5%',text)

    def test_opt_in_all_variants_group_into_one_report_and_disabled_products_pause(self):
        cfg=copy.deepcopy(self.config)
        cfg['searches'].append(dict(cfg['searches'][0],id='iphone_auc'))
        cfg['settings']['median_products'].append('iphone_auc')
        self.assertEqual(1,len(m.groups(cfg,lambda s:s['id'])))
        for row in cfg['searches']:row['enabled']=False
        self.assertEqual([],m.groups(cfg,lambda s:s['id']))
        self.assertEqual([],m.groups(dict(searches=cfg['searches'],settings={}),lambda s:'sig'))

    def test_delivery_is_confirmed_once_and_respects_interval_after_restart(self):
        self.seed()
        with patch.object(m,'chart',return_value=b'test-chart'):
            first=asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now))
            self.assertEqual(12,first['messageId'])
            self.assertIsNone(asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now+6*m.DAY)))
            asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now+7*m.DAY))
        self.assertEqual(1,self.bot.send_photo.await_count)
        self.assertEqual(1,self.bot.send_message.await_count) # week-old samples have expired

    def test_ambiguous_send_is_not_repeated_next_pass(self):
        self.bot.send_message.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):
            asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now))
        self.assertIsNone(asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now+60)))
        self.bot.send_message.assert_awaited_once()
        self.assertEqual('uncertain',next(iter(self.store.load()['entries'].values()))['status'])

    def test_failed_claim_write_never_sends_and_crashed_claim_is_not_resent(self):
        with patch.object(self.store,'save',side_effect=OSError()):
            with self.assertRaises(OSError):
                asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now))
        self.bot.send_message.assert_not_awaited()
        with patch.object(self.bot,'send_message',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now))
        self.assertIsNone(asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now+60)))

    def test_rate_limit_has_safe_delayed_retry(self):
        from telegram.error import RetryAfter
        self.bot.send_message.side_effect=RetryAfter(120)
        asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now))
        self.assertIsNone(asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now+60)))
        self.bot.send_message.side_effect=None
        self.assertIsNotNone(asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',self.store,self.now+121)))

    def test_png_is_real_and_does_not_include_bids_or_source_text(self):
        self.seed()
        photo=m.chart('Контрольный товар',m.trend({'iphone':'sig'},self.now))
        self.assertEqual(b'\x89PNG\r\n\x1a\n',photo.getvalue()[:8])
        self.assertGreater(len(photo.getvalue()),10000)

    def test_schema1_round_trip_preserves_on_off_interval_and_older_client_omission(self):
        base=Path(self.temp.name)
        cfg=base/'config.json';manifest=base/'app_sync.json'
        cfg.write_text(json.dumps(self.config),encoding='utf8')
        with patch.object(build,'CONFIG_PATH',cfg),patch.object(build,'OUTPUT_PATH',manifest):build.main()
        original=json.loads(manifest.read_text())
        with patch.object(merge,'CONFIG_PATH',cfg),patch.object(merge,'MANIFEST_PATH',manifest):
            merge.main()
            self.assertEqual(['iphone'],json.loads(cfg.read_text())['settings']['median_products'])
            old=copy.deepcopy(original);old['config'].pop('median_products');old['config'].pop('median_interval_days')
            manifest.write_text(json.dumps(old));merge.main()
            self.assertEqual(['iphone'],json.loads(cfg.read_text())['settings']['median_products'])
            original['config'].update(median_products='[]',median_interval_days='1')
            manifest.write_text(json.dumps(original));merge.main()
            settings=json.loads(cfg.read_text())['settings']
            self.assertEqual([],settings['median_products']);self.assertEqual(1,settings['median_interval_days'])

    def test_bad_settings_refuse_to_overwrite_working_configuration(self):
        for settings in [dict(median_products='oops'),dict(median_products=[1]),dict(median_interval_days=0),
                         dict(median_interval_days=31),dict(median_interval_days=True),dict(median_interval_days='1.5')]:
            with self.assertRaises((ValueError,TypeError)):
                m.preferences(settings)

    def test_remote_claim_precedes_telegram_and_does_not_create_untracked_worktree_file(self):
        remote=m.DeliveryStore(Path(self.temp.name)/'untracked.json',remote=True)
        requests=[]
        def request(method,payload=None):
            requests.append((method,payload))
            return None if method=='GET' else {'content':{'sha':'saved'}}
        async def send(**kwargs):
            claim=json.loads(__import__('base64').b64decode(requests[-1][1]['content']))
            self.assertEqual('claimed',next(iter(claim['entries'].values()))['status'])
            self.assertNotIn(self.bot.token,json.dumps(claim))
            return Mock(message_id=77)
        self.bot.send_message.side_effect=send
        with patch.object(remote,'_request',side_effect=request):
            result=asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',remote,self.now))
        self.assertEqual(77,result['messageId']);self.assertFalse(remote.path.exists())
        self.assertEqual(['GET','PUT','PUT'],[x[0] for x in requests])

    def test_remote_compare_and_swap_failure_prevents_send(self):
        remote=m.DeliveryStore(Path(self.temp.name)/'remote.json',remote=True)
        with patch.object(remote,'_request',side_effect=[None,OSError('CAS conflict')]):
            with self.assertRaises(OSError):
                asyncio.run(m.send_due(self.bot,'test-chat',self.config,lambda s:'sig',remote,self.now))
        self.bot.send_message.assert_not_awaited();self.bot.send_photo.assert_not_awaited()

    def test_real_post_description_pipeline_keeps_expensive_seen_quotes_but_not_bad_or_missing_ones(self):
        import config_manager
        with patch.object(config_manager,'CONFIG_PATH',str(Path(self.temp.name)/'config.json')):
            import monitor
            from test_verified_history import VerifiedHistoryTests, HistoryConfig
        cfg=HistoryConfig()
        cfg.get_settings=lambda:dict(user_zip='09648',warn_non_eu=False,median_products=['qa'])
        rows,details=VerifiedHistoryTests().data(True)
        search=dict(id='qa',query='logitech superlight 2',filters=dict(category='mice',listing_type='all',limit_price=45,max_price=150))
        with patch.object(monitor,'config',cfg),patch.object(monitor,'_runtime_errors',[]),patch.object(monitor,'_fetch_item_details',side_effect=lambda i:details[i]):
            asyncio.run(monitor._verified_history(rows,search))
            with price_history._connect() as db:
                observed={r['item_id']:r['total'] for r in db.execute('select item_id,total from median_observations')}
            self.assertEqual({'seen':45,'expensive':95},observed)
            self.assertIsNone(price_history.get_stats_7d('qa')) # whole population is still incomplete

    def test_delivery_status_exposes_uncertain_and_confirmed_counts_without_routes(self):
        self.store.save(dict(schema=1,entries={'x':dict(status='confirmed',confirmedAt=self.now),
                                             'y':dict(status='uncertain'),'z':dict(status='claimed')}))
        status=m.delivery_status(self.store.path)
        self.assertEqual(1,status['confirmed']);self.assertEqual(2,status['held'])
        self.assertNotIn('entries',status);self.assertIsNotNone(status['lastConfirmedAt'])


if __name__=='__main__':unittest.main()
