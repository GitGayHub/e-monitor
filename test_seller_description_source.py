"""Synthetic source-binding checks; never contact eBay or use production data."""
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import monitor


class SellerDescriptionSourceTests(unittest.TestCase):
    item_id = '123456789012'
    text = '<p>Complete working synthetic item.</p>'

    def page(self, url):
        return f'<iframe id="desc_ifr" src="{url}"></iframe>'

    def test_foreign_host_or_another_item_is_never_fetched(self):
        for url in ('https://evil.invalid/collect',
                    'https://itm.ebaydesc.com/itmdesc/999999999999',
                    'https://itm.ebaydesc.com.evil.invalid/itmdesc/' + self.item_id,
                    'https://user@itm.ebaydesc.com/itmdesc/' + self.item_id):
            with self.subTest(url=url):
                session = Mock()
                session.get.return_value = Mock(status_code=200, text=self.text, url=url)
                result = monitor._parse_item_details_html(self.page(url), session=session, item_id=self.item_id)
                self.assertFalse(monitor._clean_description(result['description']))
                session.get.assert_not_called()

    def test_redirected_description_is_not_accepted(self):
        url = 'https://itm.ebaydesc.com/itmdesc/' + self.item_id
        for redirected in ('https://evil.invalid/collect', 'https://itm.ebaydesc.com/itmdesc/999999999999'):
            with self.subTest(redirected=redirected):
                session = Mock()
                session.get.return_value = Mock(status_code=200, text=self.text, url=redirected)
                result = monitor._parse_item_details_html(self.page(url), session=session, item_id=self.item_id)
                self.assertFalse(monitor._clean_description(result['description']))
                session.get.assert_called_once()

    def test_same_item_description_is_read(self):
        url = 'https://itm.ebaydesc.com/itmdesc/' + self.item_id
        session = Mock()
        session.get.return_value = Mock(status_code=200, text=self.text, url=url)
        result = monitor._parse_item_details_html(self.page(url), session=session, item_id=self.item_id)
        self.assertIn('Complete working synthetic item', result['description'])
        session.get.assert_called_once()

    def test_redirects_are_followed_only_for_the_same_item_on_trusted_hosts(self):
        url = 'https://itm.ebaydesc.com/itmdesc/' + self.item_id
        safe = 'https://vi.vipr.ebaydesc.com/itmdesc/' + self.item_id
        for target, should_read in ((safe, True), ('https://evil.invalid/collect', False),
                                    ('https://itm.ebaydesc.com/itmdesc/999999999999', False)):
            with self.subTest(target=target):
                redirect = Mock(status_code=302, url=url, headers={'Location': target})
                final = Mock(status_code=200, text=self.text, url=target)
                session = Mock(); session.get.side_effect = [redirect, final]
                result = monitor._parse_item_details_html(self.page(url), session=session, item_id=self.item_id)
                self.assertEqual(should_read, bool(monitor._clean_description(result['description'])))
                self.assertEqual(2 if should_read else 1, session.get.call_count)
                for call in session.get.call_args_list:
                    self.assertFalse(call.kwargs['allow_redirects'])

    def test_http_client_does_not_follow_redirects_automatically(self):
        from curl_cffi.requests import Session
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/untrusted-target')
                self.end_headers()
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with Session() as session:
                result = session.get(f'http://127.0.0.1:{server.server_port}/start',
                                     allow_redirects=False, timeout=3)
            self.assertEqual(302, result.status_code)
            self.assertEqual(['/start'], hits)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
