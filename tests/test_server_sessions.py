import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import workshop_app as app
from server_sessions import contributions, share, use_shared, transient_config
from server_workshop import lookup


class GuestPrivacyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = app.WorkshopService(Path(temp.name) / 'data')
        self.root.server_mode = True
        source = self.root.data_dir / 'workshop_sources/281990/123'
        (source / 'localisation/english').mkdir(parents=True)
        (source / 'descriptor.mod').write_text('name="Original"')
        (source / 'localisation/english/test.yml').write_text('l_english:\n key:0 "Hello"\n')
        with patch.dict(os.environ, {'TRANSLATOR_PASSWORD': 'test-password-long-enough'}):
            self.server = app.AppServer(('127.0.0.1', 0), self.root)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, path, body=None, cookie=''):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Cookie': cookie, 'X-App-Token': self.server.token, 'Content-Type': 'application/json'}
        conn.request('GET' if body is None else 'POST', path,
                     None if body is None else json.dumps(body), headers)
        response = conn.getresponse()
        status, new_cookie = response.status, response.getheader('Set-Cookie')
        data = response.read()
        conn.close()
        return status, new_cookie, data

    def guest(self):
        status, cookie, data = self.call('/api/state')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)['profiles'], [])
        cookie = cookie.split(';')[0]
        token = cookie.split('=', 1)[1]
        return cookie, self.server.visitors[token][0]

    def translate(self, guest, key='must-not-persist-api-key'):
        lookup(guest, 'https://steamcommunity.com/sharedfiles/filedetails/?id=123')
        config = {**guest.config(), 'api_key': key, 'provider': 'test-model', 'model': 'test-model'}
        guest.start('translate', lambda: guest.translate('281990:123', translator=app.WorkshopService.demo_translate),
                    '281990:123', config_override=config)
        for _ in range(100):
            if not guest.busy(): break
            time.sleep(.02)
        self.assertFalse(guest.busy())
        self.assertIsNone(guest.jobs['281990:123']['error'])

    def upload_translation(self, cookie, filename, data):
        import urllib.parse
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        query = urllib.parse.urlencode({'id': '281990:123', 'filename': filename})
        conn.request('POST', '/api/upload-import?' + query, data,
                     {'Cookie': cookie, 'X-App-Token': self.server.token})
        response = conn.getresponse()
        status, body = response.status, response.read()
        conn.close()
        return status, body

    def test_browser_translation_upload_yaml_zip_and_private_workspace(self):
        import io
        import zipfile
        cookie, guest = self.guest()
        _, other = self.guest()
        lookup(guest, 'https://steamcommunity.com/sharedfiles/filedetails/?id=123')
        translated = 'l_simp_chinese:\n key:0 "你好"\n'.encode()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as target:
            target.writestr('localisation/test.yaml', translated)
        for filename, data in [('test.yaml', translated), ('test.zip', archive.getvalue())]:
            with self.subTest(filename=filename):
                status, body = self.upload_translation(cookie, filename, data)
                self.assertEqual(status, 202, body)
                for _ in range(100):
                    if not guest.busy(): break
                    time.sleep(.02)
                self.assertIsNone(guest.jobs['281990:123']['error'])
                self.assertIn('281990:123', guest.analyzed_mod_ids)
                self.assertEqual(guest.get_mod('281990:123')['counts']['cached'], 1)
                self.assertFalse(list((guest.data_dir / 'uploads').iterdir()))
        self.assertFalse(other.inventory)
        self.assertFalse(contributions(other))

    def test_empty_translation_reports_error_and_failed_start_cleans_upload(self):
        cookie, guest = self.guest()
        lookup(guest, 'https://steamcommunity.com/sharedfiles/filedetails/?id=123')
        status, _ = self.upload_translation(cookie, 'empty.yml', b'l_simp_chinese:\n')
        self.assertEqual(status, 202)
        for _ in range(100):
            if not guest.busy(): break
            time.sleep(.02)
        self.assertIn('未找到', guest.jobs['281990:123']['error'])
        with patch.object(guest, 'start', side_effect=ValueError('busy')):
            status, _ = self.upload_translation(cookie, 'test.yml', b'content')
        self.assertEqual(status, 400)
        self.assertFalse(list((guest.data_dir / 'uploads').iterdir()))

    def test_guest_workspaces_are_isolated_and_config_save_is_admin_only(self):
        cookie1, first = self.guest()
        cookie2, second = self.guest()
        self.assertNotEqual(first.data_dir, second.data_dir)
        self.translate(first)
        self.assertFalse(second.inventory)
        self.assertFalse(self.root.inventory)
        status, _, _ = self.call('/api/config', {'api_key': 'evil'}, cookie1)
        self.assertEqual(status, 403)
        self.assertFalse(contributions(first))
        for path in first.data_dir.rglob('*'):
            if path.is_file(): self.assertNotIn(b'must-not-persist-api-key', path.read_bytes(), str(path))
        self.assertEqual(first.config()['api_key'], '')
        self.assertEqual(first.profiles(), [])

    def test_opt_in_sharing_records_author_model_and_default_no_publication(self):
        _, first = self.guest()
        _, second = self.guest()
        self.translate(first)
        self.assertFalse(contributions(second))
        share(first, {'id': '281990:123', 'author': '', 'model': 'client-forged'})
        record = contributions(second)[0]
        self.assertEqual((record['author'], record['model'], record['publish_allowed']), ('匿名', 'test-model', 0))
        lookup(second, 'https://steamcommunity.com/sharedfiles/filedetails/?id=123')
        result = use_shared(second, {'id': '281990:123', 'share_id': record['id']})
        self.assertGreater(result['imported'], 0)
        self.assertEqual(result['author'], '匿名')
        self.assertNotEqual(first.inventory['281990:123']['path'], second.inventory['281990:123']['path'])

    def test_explicit_publication_consent_and_hash_mismatch_rejection(self):
        _, first = self.guest()
        _, second = self.guest()
        self.translate(first)
        share(first, {'id': '281990:123', 'author': '译者甲', 'publish_allowed': True})
        record = contributions(second)[0]
        self.assertEqual(record['publish_allowed'], 1)
        lookup(second, 'https://steamcommunity.com/sharedfiles/filedetails/?id=123')
        source = Path(second.inventory['281990:123']['path']) / 'localisation/english/test.yml'
        source.write_text('l_english:\n key:0 "Changed original"\n')
        result = use_shared(second, {'id': '281990:123', 'share_id': record['id']})
        self.assertEqual(result['imported'], 0)

    def test_reject_shared_submission_without_finished_translation_and_private_api_urls(self):
        _, guest = self.guest()
        with self.assertRaises(ValueError): share(guest, {'id': '281990:123'})
        for url in ('http://example.com/v1', 'https://127.0.0.1/v1', 'https://example.com/v1?secret=x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                transient_config(guest, {'base_url': url, 'model': 'test', 'api_key': 'test'})
