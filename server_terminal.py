"""Authenticated developer PTY sessions; never available in desktop mode."""
import codecs
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


class Terminal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self.process = None
        self.fd = None
        self.output = ''
        self.started = 0

    def status(self):
        with self.lock:
            return {'connected': self.process is not None and self.process.poll() is None,
                    'output': self.output, 'user': __import__('getpass').getuser()}

    def connect(self):
        import pty
        import fcntl
        import termios
        import struct
        with self.lock:
            if self.status()['connected']:
                return self.status()
            if self.fd is not None:
                raise ValueError('上一终端正在关闭，请稍后连接')
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 100, 0, 0))
            env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL') if key in os.environ}
            env.update(TERM='dumb', PS1='$ ', HISTFILE='/dev/null')
            try:
                # Acquire the controlling PTY in a fresh interpreter, avoiding preexec_fn
                # in this multithreaded HTTP server. Then replace it with the shell.
                bootstrap = ("import fcntl,termios,os; fcntl.ioctl(0,termios.TIOCSCTTY,0); "
                             "os.execv('/bin/bash',['bash','--noprofile','--norc','-i','+m'])")
                self.process = subprocess.Popen([sys.executable, '-c', bootstrap],
                    cwd=self.directory, env=env, stdin=slave, stdout=slave, stderr=slave,
                    start_new_session=True)
            except Exception:
                os.close(master)
                raise
            finally:
                os.close(slave)
            os.set_blocking(master, False)
            self.fd = master
            self.output = ''
            self.started = time.monotonic()
            threading.Thread(target=self._read, args=(self.process, master), daemon=True).start()
            return self.status()

    def _read(self, process, fd):
        import select
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        try:
            while True:
                if time.monotonic() - self.started > 900:
                    break
                if select.select([fd], [], [], .2)[0]:
                    try:
                        raw = os.read(fd, 8192)
                    except OSError:
                        break
                    if not raw:
                        break
                    with self.lock:
                        self.output = (self.output + decoder.decode(raw))[-128000:]
                elif process.poll() is not None:
                    break
        finally:
            with self.lock:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                process.wait()
                if self.fd == fd:
                    self.fd = None
                os.close(fd)

    def write(self, data):
        if not isinstance(data, str) or not 0 < len(data) <= 8192:
            raise ValueError('终端输入必须为 1–8192 字符')
        with self.lock:
            if not self.status()['connected'] or self.fd is None:
                raise ValueError('请先连接服务器终端')
            encoded = data.encode()
            if len(encoded) > 8192:
                raise ValueError('终端输入最多 8192 字节')
            try:
                count = os.write(self.fd, encoded)
            except (BlockingIOError, OSError):
                raise ValueError('终端暂时无法接收输入，请稍后重试') from None
            if count != len(encoded):
                raise ValueError('输入过长，仅发送了部分内容，请检查终端输出')
        return self.status()

    def disconnect(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        return self.status()


def server_info(directory):
    try:
        data = json.loads((Path(directory) / 'server_info.json').read_text())
    except (OSError, ValueError):
        data = {}
    return {key: str(data.get(key, '未配置'))[:200] for key in ('ip', 'region')}
