import asyncio
import copy
import unittest
import contextlib,io,os
from unittest.mock import AsyncMock, Mock,patch
from qa.live_price_probe import deliver_once, validate_snapshot, fingerprint, quote_candidate, correct_caption_once,main,require_verified_details


class DurableStore:
    def __init__(self):
        self.rows = {}
        self.fail_claim = False

    def receipts(self):
        return copy.deepcopy(self.rows), 'sha'

    def write(self, rows, sha):
        if self.fail_claim:
            raise TimeoutError('unknown commit result')
        self.rows = copy.deepcopy(rows)
        return 'updated'


class PriceProbeTests(unittest.TestCase):
    def test_missing_body_price_and_filter_rejection_are_distinct_without_raw_description(self):
        for details,complete,accepted,error in [(None,False,False,'listing details unavailable'),({},False,False,'listing details unavailable'),({'description':''},False,False,'seller description unavailable'),({'description':'private seller body'},False,False,'live price unavailable'),({'description':'private seller body','price':{'value':'405'},'estimatedAvailabilities':None},True,False,'rejected by common filters')]:
            fake=Mock();fake._clean_description.side_effect=lambda s:s;fake._provider_details_complete.return_value=complete;fake._details_match_contract.return_value=accepted
            output=io.StringIO()
            with contextlib.redirect_stdout(output),self.assertRaisesRegex(ValueError,error):require_verified_details(fake,details,{}, {})
            self.assertNotIn('private seller body',output.getvalue())
    def test_restarted_workflow_stops_before_config_or_ebay_for_an_existing_claim(self):
        store=DurableStore();store.rows={'lg-price-case':{'status':'photo_confirmed_caption_corrected','correction':{'status':'confirmed'},'messageId':987}}
        store.snapshot=Mock(side_effect=AssertionError('No fresh config or eBay request needed for duplicate'))
        with patch.dict(os.environ,{'QA_REQUEST_ID':'lg-price-case','QA_SETTINGS_REVISION':'old','QA_EXPECTED_LIMIT':'429','QA_CORRECT_EXISTING':'true'}),patch('qa.live_price_probe.GitHubStore',return_value=store),contextlib.redirect_stdout(io.StringIO()) as out:
            asyncio.run(main())
        store.snapshot.assert_not_called()
        self.assertIn('"duplicateSuppressed": true',out.getvalue())
    def test_missing_shipping_cannot_be_seeded_as_free_delivery(self):
        row={'item_id':'800366377085','price':405,'shipping_cost':18.99}
        self.assertEqual(row,quote_candidate([row],row['item_id'],18.99))
        for rows in [[],[{**row,'shipping_cost':0}],[{**row,'is_pickup_only':True}]]:
            with self.assertRaises(ValueError):quote_candidate(rows,row['item_id'],18.99)

    def test_correction_edits_the_existing_photo_once_and_preserves_original_evidence(self):
        for timeout in [False,True]:
            store=DurableStore();store.rows={'lg-price-case':{'messageId':987,'status':'photo_confirmed','total':405}}
            edit=AsyncMock(side_effect=TimeoutError()) if timeout else AsyncMock(return_value=Mock(message_id=987))
            if timeout:
                with self.assertRaises(TimeoutError):asyncio.run(correct_caption_once(store,'lg-price-case',{'total':423.99},edit))
            else:
                result=asyncio.run(correct_caption_once(store,'lg-price-case',{'total':423.99},edit))
                self.assertEqual('photo_confirmed_caption_corrected',result['status'])
            self.assertEqual(405,store.rows['lg-price-case']['initialDelivery']['total'])
            again=asyncio.run(correct_caption_once(store,'lg-price-case',{'total':423.99},edit))
            self.assertTrue(again['duplicateCorrectionSuppressed']);edit.assert_awaited_once_with(987)
    def test_actual_applied_revision_and_both_variants_are_required(self):
        revision = '48b8e24e-2e4e-46cf-a9f2-bd666dce8fb6'
        ids = ['lg_ultragear_oled_480hz_buy', 'lg_ultragear_oled_480hz_auc']
        cfg = {'mobile_settings_revision': revision, 'searches': [{'id': i, 'filters': {'limit_price': 429}} for i in ids]}
        manifest = {'settingsRevision': revision, 'searches': [{'id': i, 'maxPrice': 429} for i in ids]}
        runtime = {'settingsRevision': revision, 'logicVersion': 123, 'configFingerprint': fingerprint(cfg)}
        meta = {'logicVersion': 123}
        self.assertEqual(ids[0], validate_snapshot(cfg, runtime, manifest, meta, 'normal', revision, 429)['id'])
        for target, key, value in [(runtime, 'settingsRevision', 'old'), (runtime, 'configFingerprint', 'old'),
                                   (runtime, 'logicVersion', 122), (manifest['searches'][1], 'maxPrice', 430)]:
            old = target[key]; target[key] = value
            with self.assertRaises(ValueError):
                validate_snapshot(cfg, runtime, manifest, meta, 'normal', revision, 429)
            target[key] = old

    def test_confirmed_photo_is_not_resent_after_a_fresh_runner(self):
        store = DurableStore()
        send = AsyncMock(return_value=Mock(message_id=987, photo=['photo']))
        first = asyncio.run(deliver_once(store, 'lg-price-case', {'limit': 429}, send))
        self.assertEqual('photo_confirmed', first['status'])
        again = DurableStore(); again.rows = copy.deepcopy(store.rows)
        repeat = asyncio.run(deliver_once(again, 'lg-price-case', {'limit': 429}, send))
        self.assertTrue(repeat['duplicateSuppressed']); send.assert_awaited_once()

    def test_failed_durable_claim_never_calls_telegram(self):
        store = DurableStore(); store.fail_claim = True
        send = AsyncMock()
        with self.assertRaises(TimeoutError):
            asyncio.run(deliver_once(store, 'lg-price-case', {}, send))
        send.assert_not_awaited()

    def test_ambiguous_or_incomplete_acknowledgement_cannot_send_again(self):
        for no_photo in [False, True]:
            store = DurableStore()
            send = AsyncMock(return_value=Mock(message_id=987, photo=[])) if no_photo else AsyncMock(side_effect=TimeoutError())
            with self.assertRaises((TimeoutError, RuntimeError)):
                asyncio.run(deliver_once(store, 'lg-price-case', {}, send))
            self.assertEqual('uncertain_do_not_retry', store.rows['lg-price-case']['status'])
            self.assertTrue(asyncio.run(deliver_once(store, 'lg-price-case', {}, send))['duplicateSuppressed'])
            send.assert_awaited_once()
