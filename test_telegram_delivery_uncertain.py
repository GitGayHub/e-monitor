import asyncio,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,AsyncMock,patch
from telegram.error import TimedOut,Forbidden,BadRequest
import monitor
from mobile import feed_writer
from mobile.runtime_status import publish

class TelegramDeliveryUncertainTests(unittest.TestCase):
    def setUp(self):
        state=patch.object(monitor,'_runtime_delivery_warnings',[])
        state.start();self.addCleanup(state.stop)
    def test_interrupted_reserved_request_is_explicitly_held_after_restart(self):
        data={'item':{'initial':True,'deliveryPending':'initial'}}
        restored=monitor._normalize_seen_payload(data)
        self.assertEqual('interrupted_before_confirmation',restored['item']['deliveryUncertain']['initial'])
        self.assertTrue(restored['item']['initial'])
    def test_timeout_never_switches_bot_or_falls_back_to_another_message(self):
        for text_failure in (False,True):
            bot=Mock();bot.send_photo=AsyncMock(side_effect=BadRequest('photo rejected') if text_failure else TimedOut())
            bot.send_message=AsyncMock(side_effect=TimedOut())
            backup=Mock();backup.send_photo=AsyncMock();backup.send_message=AsyncMock()
            with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN_BACKUP':'isolated-test-backup'}),patch('telegram.Bot',return_value=backup):
                with self.assertRaises(monitor.TelegramDeliveryUncertain):
                    asyncio.run(monitor.safe_send_telegram(bot,1,'hello',img='https://example.invalid/a.jpg'))
            backup.send_photo.assert_not_awaited();backup.send_message.assert_not_awaited()
            self.assertEqual(35,bot.send_photo.await_args.kwargs['read_timeout'])
            self.assertEqual(1 if text_failure else 0,bot.send_message.await_count)

    def test_definite_rejection_can_use_existing_backup_and_keeps_its_receipt(self):
        bot=Mock();bot.send_message=AsyncMock(side_effect=Forbidden('bot blocked'))
        receipt=Mock(message_id=2049);backup=Mock();backup.send_message=AsyncMock(return_value=receipt)
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN_BACKUP':'isolated-test-backup'}),patch('telegram.Bot',return_value=backup):
            self.assertIs(receipt,asyncio.run(monitor.safe_send_telegram(bot,1,'hello')))
        backup.send_message.assert_awaited_once()
        self.assertEqual(35,backup.send_message.await_args.kwargs['read_timeout'])

    def test_uncertain_stage_survives_restart_without_feed_confirmation_or_resend(self):
        item={'item_id':'uncertain-control','title':'DualSense','seller_name':'seller','price':30,'total_price':30,'auction':True,'buy_now':False,'time_left':'5 Min'}
        search={'query':'DualSense','filters':{'category':'all','limit_price':40}}
        details={'title':'DualSense','description':'Sony DualSense, fully functional controller.','price':{'value':'30'}}
        with tempfile.TemporaryDirectory() as folder,patch.object(monitor,'seen_state',{}),patch.object(monitor,'SEEN_IDS_FILE',str(Path(folder)/'seen.json')),patch.object(monitor,'_fetch_item_details',return_value=details),patch.object(monitor,'send_notification',new=AsyncMock(side_effect=monitor.TelegramDeliveryUncertain('TimedOut'))) as send,patch.object(feed_writer,'enqueue') as feed:
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(),item,search,None,'initial')))
            self.assertIn('initial',monitor.seen_state['uncertain-control']['deliveryUncertain'])
            monitor.load_seen_ids()
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(),item,search,None,'initial')))
            send.assert_awaited_once();feed.assert_not_called()
            self.assertIn('deliveryUncertain',json.loads(Path(monitor.SEEN_IDS_FILE).read_text())['uncertain-control'])

    def test_confirmed_route_is_optional_feed_metadata_and_runtime_evidence(self):
        entry=feed_writer.build_entry({'item_id':'confirmed','_telegram_bot_id':123,'_telegram_bot_username':'isolated_test_bot','_telegram_delivery_route':'backup','_telegram_confirmed_at':2.0}, {},telegram_message_id=2049,spotted_time=1000)
        self.assertEqual('backup',entry['telegramDeliveryRoute']);self.assertEqual(123,entry['telegramBotId'])
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'feed.json').write_text(json.dumps({'items':[entry]}))
            status=publish({'searches':[]},1,'partial',path=p/'runtime_status.json')
            self.assertEqual('backup',status['lastTelegramDeliveryRoute']);self.assertEqual('isolated_test_bot',status['lastTelegramBotUsername'])
            entry.pop('telegramConfirmedTime')
            (p/'feed.json').write_text(json.dumps({'items':[entry]}))
            unknown=publish({'searches':[]},1,'partial',path=p/'runtime_status.json')
            self.assertNotIn('lastTelegramDeliveryRoute',unknown)
            self.assertNotIn('lastTelegramConfirmedAt',unknown)
