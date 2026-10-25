import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from server_codex import CodexConsole
import workshop_app as app


class CodexTests(unittest.TestCase):
    def test_fake_cli_stdin_output_and_clean_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'codex'
            binary.write_text('#!/usr/bin/env python3\nimport sys,json\nif sys.argv[1] == "login": sys.exit(0)\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":sys.stdin.read()}}))\n')
            binary.chmod(0o700)
            console = CodexConsole(Path(directory) / 'data')
            with patch.dict(os.environ, {'PATH':directory + os.pathsep + os.environ['PATH'], 'OPENAI_API_KEY':'private', 'TRANSLATOR_PASSWORD':'private'}):
                self.assertNotIn('OPENAI_API_KEY', console.environment())
                self.assertNotIn('TRANSLATOR_PASSWORD', console.environment())
                console.start('hello; $(touch never-run)')
                deadline = time.monotonic() + 5
                while console.status()['running'] and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(console.status()['running'])
                self.assertEqual(console.status()['output'].strip(), 'hello; $(touch never-run)')
                self.assertFalse((console.directory / 'never-run').exists())

    def test_guest_cannot_call_any_console_action(self):
        with tempfile.TemporaryDirectory() as directory:
            service = app.WorkshopService(Path(directory))
            service.server_mode = True
            with patch.dict(os.environ, {'TRANSLATOR_PASSWORD':'test-password-long-enough'}):
                server = app.AppServer(('127.0.0.1', 0), service)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                for action in ('status', 'start', 'stop'):
                    connection.request('POST', '/api/codex-' + action, json.dumps({'prompt':'test'}), {'X-App-Token':server.token})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 403)
                    response.read()
                connection.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_stop_releases_running_job(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'codex'
            binary.write_text('#!/usr/bin/env python3\nimport sys,time\nif sys.argv[1] == "login": sys.exit(0)\ntime.sleep(30)\n')
            binary.chmod(0o700)
            console = CodexConsole(Path(directory) / 'data')
            with patch.dict(os.environ, {'PATH':directory + os.pathsep + os.environ['PATH']}):
                console.start('test')
                try:
                    with self.assertRaises(ValueError):
                        console.start('second')
                finally:
                    console.stop()
                deadline = time.monotonic() + 5
                while console.status()['running'] and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(console.status()['running'])

    def test_invalid_prompt_and_no_login(self):
        with tempfile.TemporaryDirectory() as directory:
            console = CodexConsole(directory)
            for prompt in (None, '', 'x' * 12001):
                with self.assertRaises(ValueError):
                    console.start(prompt)
            with patch('server_codex.shutil.which', return_value=None), self.assertRaises(ValueError):
                console.start('test')
