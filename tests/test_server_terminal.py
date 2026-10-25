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
from server_terminal import Terminal


@unittest.skipUnless(os.name == 'posix', 'PTY requires POSIX')
class TerminalTests(unittest.TestCase):
    def wait_output(self, terminal, expected):
        deadline = time.monotonic() + 5
        while expected not in terminal.status()['output'] and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertIn(expected, terminal.status()['output'])

    def test_shell_state_clean_environment_interrupt_and_disconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(directory)
            with patch.dict(os.environ, {'TRANSLATOR_PASSWORD':'secret-not-for-shell', 'OPENAI_API_KEY':'private-key'}):
                terminal.connect()
            try:
                terminal.write("printf 'ENV:%s:%s\\n' \"${TRANSLATOR_PASSWORD-unset}\" \"${OPENAI_API_KEY-unset}\"\n")
                self.wait_output(terminal, 'ENV:unset:unset')
                terminal.write('mkdir child; cd child\n')
                terminal.write("printf 'CWD:'; pwd\n")
                self.wait_output(terminal, 'CWD:' + str(Path(directory).resolve()) + '/child')
                terminal.write('sleep 20\n')
                time.sleep(.1)
                terminal.write('\x03')
                terminal.write("printf 'INTERRUPTED_OK\\n'\n")
                self.wait_output(terminal, '\r\nINTERRUPTED_OK\r\n')
            finally:
                terminal.disconnect()
            deadline = time.monotonic() + 5
            while terminal.status()['connected'] and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertFalse(terminal.status()['connected'])

    def test_http_auth_isolation_and_logout(self):
        with tempfile.TemporaryDirectory() as directory:
            service = app.WorkshopService(Path(directory))
            service.server_mode = True
            with patch.dict(os.environ, {'TRANSLATOR_PASSWORD':'terminal-test-password'}):
                server = app.AppServer(('127.0.0.1', 0), service)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
            def call(action, body=None, cookie=None, token=True):
                headers = {'Content-Type':'application/json'}
                if token: headers['X-App-Token'] = server.token
                if cookie: headers['Cookie'] = cookie
                connection.request('POST', '/api/' + action, json.dumps(body or {}), headers)
                response = connection.getresponse()
                result = json.loads(response.read())
                return response.status, result
            try:
                for action in ('status', 'connect', 'input', 'disconnect'):
                    self.assertEqual(call('terminal-' + action)[0], 403)
                server.sessions.update({'one':time.time()+60, 'two':time.time()+60})
                self.assertEqual(call('terminal-connect', cookie='translator_session=one', token=False)[0], 403)
                self.assertEqual(call('terminal-connect', cookie='translator_session=one')[0], 200)
                self.assertFalse(call('terminal-status', cookie='translator_session=two')[1]['connected'])
                self.assertEqual(call('terminal-input', {'input':'echo nope\n'}, 'translator_session=two')[0], 400)
                terminal = server.terminals['one']
                self.assertEqual(call('dev-logout', cookie='translator_session=one')[0], 200)
                self.assertNotIn('one', server.terminals)
                self.assertEqual(call('terminal-status', cookie='translator_session=one')[0], 403)
            finally:
                for terminal in server.terminals.values(): terminal.disconnect()
                connection.close()
                server.shutdown()
                server.server_close()
