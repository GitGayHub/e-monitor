import asyncio,copy,json,sqlite3,tempfile,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import monitor,price_history
from test_search_intent_rules import item

class HistoryConfig:
    def get_settings(self):return {'user_zip':'09648','warn_non_eu':False}
    def get_global_banned_sellers(self):return []
    def get_banned_item_ids(self):return set()
    def get_item_hashes(self):return {monitor._item_hash('seller','Logitech Superlight 2 Gaming-Maus',40)}

class VerifiedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=patch.object(price_history,'DB_PATH',str(Path(self.folder.name)/'history.db'));self.db.start()
        self.cfg=patch.object(monitor,'config',HistoryConfig());self.cfg.start()
        self.errors=patch.object(monitor,'_runtime_errors',[]);self.errors.start()
        self.search={'id':'qa','query':'logitech superlight 2','filters':{'category':'mice','listing_type':'all','limit_price':45,'max_price':150}}
    def tearDown(self):
        self.errors.stop();self.cfg.stop();self.db.stop();self.folder.cleanup()
    def snapshot(self,values,**kwargs):
        price_history.record_snapshot('qa',values,[],[],len(values),**kwargs)
    def test_real_legacy_schema_migrates_without_reclassifying_or_deleting_rows(self):
        c=sqlite3.connect(price_history.DB_PATH)
        c.execute('CREATE TABLE price_snapshots(id INTEGER PRIMARY KEY,search_id TEXT NOT NULL,recorded_at TEXT NOT NULL,min_sofort REAL,min_pv REAL,min_auction REAL,median_sofort REAL,total_results INTEGER NOT NULL DEFAULT 0)')
        c.execute('INSERT INTO price_snapshots VALUES(17,?,?,?,?,?,?,?)',('qa',datetime.now().strftime('%Y-%m-%d %H:%M'),9000,None,None,9000,30));c.commit();c.close()
        self.assertIsNone(price_history.get_stats_7d('qa'))
        self.assertFalse(price_history.is_outlier(100,'qa'))
        c=sqlite3.connect(price_history.DB_PATH);row=c.execute('SELECT id,median_sofort,total_results,history_version,validation_complete FROM price_snapshots').fetchone();c.close()
        self.assertEqual((17,9000,30,0,0),row)
    def test_unverified_and_partial_rows_cannot_move_valid_median(self):
        self.snapshot([1]);self.snapshot([9],verified=True,validation_complete=False,filter_signature='scope')
        self.snapshot([100,110],verified=True,validation_complete=True,filter_signature='scope')
        self.assertEqual(105,price_history.get_median_7d('qa','scope'))
        self.assertEqual(1,price_history.get_stats_7d('qa','scope')['snapshots'])
        self.assertIsNone(price_history.get_stats_7d('qa','another-model'))
    def test_auction_snapshots_do_not_inflate_purchase_confidence(self):
        self.snapshot([1000],verified=True,validation_complete=True)
        for _ in range(3):price_history.record_snapshot('qa',[],[],[5],1,verified=True,validation_complete=True)
        self.assertEqual(4,price_history.get_stats_7d('qa')['snapshots'])
        self.assertEqual(1,price_history.get_stats_7d('qa')['purchase_snapshots'])
        self.assertFalse(price_history.is_outlier(100,'qa'))
    def test_structural_edit_changes_cohort_but_notify_limit_does_not(self):
        initial=monitor._history_filter_signature(self.search)
        same=copy.deepcopy(self.search);same['filters']['limit_price']=120;same['notify']=False
        self.assertEqual(initial,monitor._history_filter_signature(same))
        for key,value in [('condition','new'),('max_price',2500),('location','eu')]:
            changed=copy.deepcopy(same);changed['filters'][key]=value
            self.assertNotEqual(initial,monitor._history_filter_signature(changed))
        changed=copy.deepcopy(same);changed['query']='logitech superlight 2 dex'
        self.assertNotEqual(initial,monitor._history_filter_signature(changed))
    def data(self,unavailable=False):
        title='Logitech Superlight 2 Gaming-Maus'
        rows=[item(title,item_id='seen',price=40,shipping_cost=5,total_price=45,seller_name='seller'),
              item(title,item_id='expensive',price=90,shipping_cost=5,total_price=95,seller_name='seller'),
              item(title,item_id='wrong-mpn',price=70,shipping_cost=5,total_price=75,seller_name='seller'),
              item(title,item_id='damaged',price=60,shipping_cost=5,total_price=65,seller_name='seller')]
        details={x['item_id']:{'title':title,'description':title+' Voll funktionsfähig.','price':{'value':str(x['price'])},'buyingOptions':['FIXED_PRICE']} for x in rows}
        details['wrong-mpn']['localizedAspects']=[{'name':'Herstellernummer','value':'910-007539'}]
        details['damaged']['description']='Logitech Superlight 2. Der Sensor ist defekt.'
        if unavailable:
            rows.append(item(title,item_id='unavailable',price=80,seller_name='seller'));details['unavailable']=None
        return rows,details
    def test_complete_pipeline_checks_expensive_seen_and_excludes_wrong_mpn_and_damage(self):
        rows,details=self.data();events=[]
        def fetch(i):events.append(i);return details[i]
        with patch.object(monitor,'_fetch_item_details',side_effect=fetch):
            verified=asyncio.run(monitor._verified_history(rows,self.search))
        self.assertEqual({'seen','expensive'},{r['item_id'] for r in verified})
        self.assertEqual(set(details),set(events))
        self.assertEqual(70,price_history.get_median_7d('qa',monitor._history_filter_signature(self.search)))
        # Seen state and the45EUR notification limit still suppress actual alerts.
        self.assertEqual([],monitor.filter_results(verified,self.search,monitor.config))
    def test_unavailable_description_preserves_verified_rows_but_withholds_median(self):
        rows,details=self.data(True)
        with patch.object(monitor,'_fetch_item_details',side_effect=lambda i:details[i]):
            verified=asyncio.run(monitor._verified_history(rows,self.search))
        self.assertEqual(2,len(verified));self.assertIsNone(price_history.get_stats_7d('qa'))
        self.assertIn('история неполная',monitor._runtime_errors[0])
        c=sqlite3.connect(price_history.DB_PATH);self.assertEqual((1,0),c.execute('SELECT history_version,validation_complete FROM price_snapshots').fetchone());c.close()
    def test_refreshed_price_must_still_obey_hard_ceiling(self):
        rows,details=self.data();details['expensive']['price']['value']='300'
        with patch.object(monitor,'_fetch_item_details',side_effect=lambda i:details[i]):
            verified=asyncio.run(monitor._verified_history(rows,self.search))
        self.assertEqual(['seen'],[r['item_id'] for r in verified])
    def test_context_change_during_network_read_cannot_confirm_another_population(self):
        rows,details=self.data();cfg=HistoryConfig();settings=cfg.get_settings()
        cfg.get_settings=lambda:settings
        def fetch(i):
            settings['user_zip']='10115'
            return details[i]
        with patch.object(monitor,'config',cfg),patch.object(monitor,'_fetch_item_details',side_effect=fetch):
            asyncio.run(monitor._verified_history(rows,self.search))
        self.assertIsNone(price_history.get_stats_7d('qa'))
    def test_hybrid_history_keeps_known_prices_separate_and_enforces_each_ceiling(self):
        raw=item('Logitech Superlight 2 Gaming-Maus',item_id='hybrid',price=80,shipping_cost=6,buy_now=True,auction=True,bin_price=1000,auc_price=80,seller_name='seller')
        sides=monitor._history_price_sides(raw,self.search)
        self.assertEqual([(False,True,86)],[(r['buy_now'],r['auction'],r['total_price']) for r in sides])
        self.search['filters']['max_price']=1500
        sides=monitor._history_price_sides(raw,self.search)
        self.assertEqual([1006,86],[r['total_price'] for r in sides])
        raw['bin_price']=None
        self.assertEqual([86],[r['total_price'] for r in monitor._history_price_sides(raw,self.search)])
    def test_missing_hybrid_purchase_price_cannot_confirm_a_complete_median(self):
        title='Logitech Superlight 2 Gaming-Maus'
        raw=item(title,item_id='hybrid',price=80,shipping_cost=6,buy_now=True,auction=True,bin_price=None,auc_price=80,seller_name='seller')
        details={'title':title,'description':title+' Voll funktionsfähig.','buyingOptions':['FIXED_PRICE','AUCTION'],'currentBidPrice':{'value':'80'}}
        with patch.object(monitor,'_fetch_item_details',return_value=details):
            asyncio.run(monitor._verified_history([raw],self.search))
        self.assertIsNone(price_history.get_stats_7d('qa'))
        c=sqlite3.connect(price_history.DB_PATH);self.assertEqual((86,0),c.execute('SELECT min_auction,validation_complete FROM price_snapshots').fetchone());c.close()
