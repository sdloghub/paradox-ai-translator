import http.client
import hashlib
import io
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
import urllib.parse
from unittest.mock import patch
import zipfile

import workshop_app as app
from server_upload import upload_mod


def package(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in files:
            archive.writestr(name, content)
    return buffer.getvalue()


class ServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.service = app.WorkshopService(Path(temporary.name) / 'data')
        self.service.server_mode = True
        self.zip = package([('Original/descriptor.mod', 'name="Original"'),
                            ('Original/localisation/english/test_l_english.yml', 'l_english:\n key:0 "Hello"\n')])

    def test_upload_scan_and_restart_persistence_without_api(self):
        result = upload_mod(self.service, self.zip, '281990', '123')
        self.assertEqual(result['id'], '281990:123')
        item = self.service.get_mod(result['id'])
        self.assertEqual(item['title'], 'Original')
        self.assertEqual(self.service.analyze(item['id'])['total'], 1)
        self.assertIn(item['id'], app.WorkshopService(self.service.data_dir).inventory)
        with self.assertRaisesRegex(ValueError, '已上传'):
            upload_mod(self.service, self.zip, '281990', '123')

    def test_reject_traversal_symlink_invalid_zip_and_missing_localisation(self):
        link = zipfile.ZipInfo('link')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for data in [package([('../outside', 'bad')]), package([('/absolute', 'bad')]),
                     package([('a\\b', 'bad')]), package([(link, '/etc/passwd')]),
                     package([('readme.txt', 'no source')]), b'not zip']:
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                upload_mod(self.service, data, '281990', '123')
        self.assertFalse((self.service.data_dir / 'uploaded_library').exists())

    def test_reject_wrong_game_id_and_oversized_expansion(self):
        for appid, uid in [('0', '123'), ('281990', '../123'), ('281990', '')]:
            with self.assertRaises(ValueError):
                upload_mod(self.service, self.zip, appid, uid)
        with patch('server_upload.MAX_EXPANDED', 5), self.assertRaises(ValueError):
            upload_mod(self.service, self.zip, '281990', '123')

    def test_http_opens_directly_and_supports_dev_login_then_uploads(self):
        with patch.dict(os.environ, {'TRANSLATOR_PASSWORD': 'test-password-long-enough'}):
            server = app.AppServer(('127.0.0.1', 0), self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
        self.addCleanup(connection.close)
        connection.request('GET', '/')
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIsNone(response.getheader('WWW-Authenticate'))
        self.assertIn(b'/server_ui.js', response.read())
        connection.request('POST', '/api/login', urllib.parse.urlencode({'username':'translator', 'password':'wrong'}))
        response = connection.getresponse()
        self.assertEqual(response.status, 401)
        self.assertIsNone(response.getheader('Set-Cookie'))
        response.read()
        connection.request('POST', '/api/login', urllib.parse.urlencode({'username':'translator', 'password':'test-password-long-enough'}))
        response = connection.getresponse()
        self.assertEqual(response.status, 303)
        cookie = response.getheader('Set-Cookie')
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        response.read()
        headers = {'Cookie': cookie.split(';')[0]}
        connection.request('GET', '/', headers=headers)
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b'/server_ui.js', response.read())
        path = '/api/upload-mod?appid=281990&uid=123'
        connection.request('POST', path, self.zip, headers)
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        # Reopen because a rejected request need not consume its body.
        connection.close()
        headers['X-App-Token'] = server.token
        connection.request('POST', path, self.zip, headers)
        response = connection.getresponse()
        self.assertEqual(response.status, 200, response.read())
        # The same session survives page refreshes and repeated background requests.
        for _ in range(3):
            connection.request('GET', '/api/state', headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIsNone(response.getheader('WWW-Authenticate'))
            body = response.read()
            self.assertIn(b'"dev_logged_in": true', body)
        server.sessions = {key: 0 for key in server.sessions}
        connection.request('GET', '/api/state', headers=headers)
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b'"dev_logged_in": false', response.read())

    def test_server_requires_strong_password(self):
        with patch.dict(os.environ, {'TRANSLATOR_PASSWORD': ''}), self.assertRaises(ValueError):
            app.AppServer(('127.0.0.1', 0), self.service)

    def test_admin_https_login_origin_secure_cookie_and_rate_limit(self):
        salt = bytes.fromhex('01' * 16)
        digest = hashlib.pbkdf2_hmac('sha256', b'admin-test-password', salt, 310000).hex()
        config = {'TRANSLATOR_PASSWORD':'test-password-long-enough',
                  'TRANSLATOR_ADMIN_USERNAME':'donmaid',
                  'TRANSLATOR_ADMIN_PASSWORD_HASH':salt.hex() + ':' + digest,
                  'TRANSLATOR_PUBLIC_ORIGIN':'https://paradox-ai-translator.com'}
        with patch.dict(os.environ, config):
            server = app.AppServer(('127.0.0.1', 0), self.service)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
        self.addCleanup(connection.close)
        form = urllib.parse.urlencode({'username':'donmaid', 'password':'admin-test-password'})
        headers = {'Origin':'https://wrong.example', 'X-Forwarded-Proto':'https'}
        connection.request('POST', '/api/login', form, headers)
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        headers['Origin'] = config['TRANSLATOR_PUBLIC_ORIGIN']
        connection.request('POST', '/api/login', form, headers)
        response = connection.getresponse()
        self.assertEqual(response.status, 303)
        self.assertIn('; Secure', response.getheader('Set-Cookie'))
        response.read()
        import time
        server.login_attempts = [time.time()] * 10
        connection.request('POST', '/api/login', form, headers)
        response = connection.getresponse()
        self.assertEqual(response.status, 429)
        response.read()
