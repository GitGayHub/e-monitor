import asyncio
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import monitor


class ImportEstimatesTest(unittest.TestCase):
    def test_known_missing_zero_and_selected_sale_prices(self):
        rows = json.loads((Path(__file__).parent / 'qa/fixtures/import_estimates_oct13.json').read_text())
        for case in rows:
            item = {'price': case['price'], 'shipping_cost': case['shipping'], 'location': case['location'],
                    'actual_import_charges': case['actual'], 'buy_now': True, 'auction': False}
            monitor._calculate_total(item, {'warn_non_eu': case['warn']})
            with self.subTest(case=case['name']):
                self.assertAlmostEqual(case['total'], item['total_price'], places=2)
                self.assertEqual(case['estimate'] is not None, item['import_estimated'])
                if case['estimate'] is not None:
                    self.assertAlmostEqual(case['estimate'], item['import_charges'], places=2)
                    self.assertIn('не подтверждена', monitor._import_price_note(item))
                elif case['actual']:
                    self.assertIn('по данным eBay', monitor._import_price_note(item))
                else:
                    self.assertEqual('', monitor._import_price_note(item))

    def test_details_quote_replaces_estimate_and_missing_quote_preserves_known_zero(self):
        item = {'price': 500, 'shipping_cost': 20, 'location': 'GB'}
        settings = {'warn_non_eu': True}
        monitor._calculate_total(item, settings)
        self.assertTrue(item['import_estimated'])
        monitor._calculate_total(item, settings, {'htmlImportCharges': {'value': '0', 'currency': 'EUR'}})
        self.assertFalse(item['import_estimated'])
        self.assertEqual(520, item['total_price'])
        monitor._calculate_total(item, settings, {'title': 'unrelated price refresh'})
        self.assertFalse(item['import_estimated'])
        self.assertEqual(520, item['total_price'])
        monitor._calculate_total(item, settings, {'htmlImportCharges': {'value': '75', 'currency': 'EUR'}})
        self.assertFalse(item['import_estimated'])
        self.assertEqual(595, item['total_price'])

    def test_notification_labels_estimate_and_confirmed_fees(self):
        original = {'item_id':'306294088377', 'title':'Nubia Z70 Ultra', 'price':1175.26, 'shipping_cost':0,
                    'location':'GB','condition':'Neu','seller_name':'qa','buy_now':True,'auction':False,'best_offer':False}
        search = {'id':'isolated-import', 'query':'nubia z70 ultra', 'filters':{'limit_price':325,'category':'phones'}}
        bot = Mock()
        for actual, prefix, note in [(None,'≈1450.57€','не подтверждена'),(126.71,'1301.97€','по данным eBay'),(0,'1175.26€',None)]:
            item = copy.deepcopy(original)
            item['actual_import_charges'] = actual
            monitor._calculate_total(item, {'warn_non_eu':True})
            with patch.object(monitor,'is_outlier',return_value=False), patch.object(monitor,'safe_send_telegram',new=AsyncMock(return_value=Mock(message_id=1))) as sender:
                self.assertTrue(asyncio.run(monitor.send_notification(bot,item,search)))
                caption = sender.await_args.args[2]
            self.assertIn(prefix, caption)
            self.assertNotIn('Пошлина:', caption)
            if note:
                self.assertIn(note, caption)
            else:
                self.assertNotIn('Импортные сборы', caption)

