"""Developer-only, bounded, read-only Codex CLI jobs (no shell or website keys)."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading


class CodexConsole:
    def __init__(self, data_dir):
        self.directory = Path(data_dir) / 'codex_workspace'
        self.home = Path(data_dir) / 'codex_home'
        self.lock = threading.RLock()
        self.process = None
        self.running = False
        self.output = ''
        self.error = ''
        self.generation = 0

    def environment(self):
        # Never inherit translation API keys or the website login password.
        allowed = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY',
                   'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy', 'SSL_CERT_FILE')
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env['CODEX_HOME'] = str(self.home)
        return env

    def status(self, check_login=False):
        with self.lock:
            result = dict(running=self.running, output=self.output, error=self.error)
        if check_login:
            binary = shutil.which('codex')
            result['installed'] = bool(binary)
            result['logged_in'] = False
            if binary:
                try:
                    result['logged_in'] = subprocess.run(
                        [binary, 'login', 'status'], env=self.environment(),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    pass
        return result

    def start(self, prompt):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
            raise ValueError('请输入 1–12000 字的任务')
        with self.lock:
            if self.running:
                raise ValueError('Codex 正在执行任务，请等待或停止')
            status = self.status(check_login=True)
            if not status['installed'] or not status['logged_in']:
                raise ValueError('服务器 Codex 尚未安装或尚未为网站服务用户登录')
            for directory in (self.directory, self.home):
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.output = self.error = ''
            self.running = True
            self.generation += 1
            generation = self.generation
            try:
                self.process = subprocess.Popen(
                    [shutil.which('codex'), 'exec', '--json', '--ephemeral', '--sandbox', 'read-only',
                     '--skip-git-repo-check', '-C', str(self.directory), '-'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=self.environment(), start_new_session=True)
                self.process.stdin.write(prompt.encode('utf-8'))
                self.process.stdin.close()
            except (OSError, ValueError):
                self.running = False
                raise ValueError('无法启动服务器 Codex') from None
            threading.Thread(target=self._read, args=(self.process, generation), daemon=True).start()
        return self.status()

    def _read(self, process, generation):
        timer = threading.Timer(600, lambda: self.stop(generation))
        timer.daemon = True
        timer.start()
        try:
            for raw in process.stdout:
                try:
                    event = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                item = event.get('item', {})
                if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                    with self.lock:
                        self.output = (self.output + item.get('text', '') + '\n')[-64000:]
                if event.get('type') in ('error', 'turn.failed'):
                    with self.lock:
                        self.error = 'Codex 执行失败，请检查服务器 CLI 登录与连接状态'
            code = process.wait()
            with self.lock:
                if code and not self.error:
                    self.error = '任务已停止或执行失败'
        finally:
            timer.cancel()
            process.stdout.close()
            with self.lock:
                if generation == self.generation:
                    self.running = False
                    self.process = None

    def stop(self, generation=None):
        with self.lock:
            if generation is not None and generation != self.generation:
                return
            if self.process and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return self.status()
