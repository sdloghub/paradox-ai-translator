#!/usr/bin/env python3
"""Local Workshop inventory, translation workspaces and SQLite backup service."""
import argparse
from datetime import datetime, timezone
from contextlib import contextmanager
from functools import partial
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile

ROOT = Path(__file__).resolve().parent


def default_data_dir(demo=False):
    suffix = 'app_data_demo' if demo else 'app_data'
    if getattr(sys, 'frozen', False):
        if os.name == 'nt':
            base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
        else:
            base = Path.home() / 'Library/Application Support'
        return base / 'WorkshopTranslator' / suffix
    return ROOT / suffix


def open_folder(path):
    if os.name == 'nt':
        os.startfile(str(path))
    else:
        import subprocess
        subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)], check=True)

GAMES = {'281990': ('st', '群星'), '394360': ('hoi4', '钢铁雄心4'),
         '236850': ('eu4', '欧陆风云4'), '1158310': ('ck3', '十字军之王3'),
         '529340': ('vic3', '维多利亚3')}
DEFAULT_CONFIG = {'api_format': 'openai', 'base_url': 'https://api.openai.com/v1',
                  'api_key': '', 'model': 'gpt-4.1-mini', 'batch_size': 10,
                  'concurrency': 3, 'steam_libraries': []}


def atomic_bytes(path, data, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = Path(stream.name)
            stream.write(data)
        if private:
            name.chmod(0o600)
        os.replace(name, path)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as target:
        for name, data in sorted(files.items()):
            target.writestr(name, data)
    return stream.getvalue()


def unarchive(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as source:
        result = {}
        for name in source.namelist():
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name:
                raise ValueError('备份包含不安全的文件路径')
            result[name] = source.read(name)
        return result


def steam_libraries(extra=()):
    candidates = [Path.home() / 'Library/Application Support/Steam']
    if os.name == 'nt':
        candidates = [Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Steam']
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                candidates.insert(0, Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
        except OSError:
            pass
    candidates.extend(Path(p).expanduser() for p in extra)
    libraries = []
    for candidate in list(candidates):
        # Accept either a library root or the workshop/content folder.
        if candidate.name == 'content' and candidate.parent.name == 'workshop':
            candidate = candidate.parent.parent.parent
        candidates_vdf = [candidate / 'steamapps/libraryfolders.vdf', candidate / 'config/libraryfolders.vdf']
        libraries.append(candidate)
        for vdf in candidates_vdf:
            if vdf.is_file():
                text = vdf.read_text(encoding='utf-8', errors='replace')
                for value in re.findall(r'"path"\s*"((?:\\.|[^"\\])*)"', text):
                    libraries.append(Path(value.replace('\\\\', '\\')))
    return list(dict.fromkeys(path.resolve() for path in libraries if path.is_dir()))


def workshop_details(ids):
    details = {}
    for offset in range(0, len(ids), 50):
        batch = ids[offset:offset + 50]
        fields = {'itemcount': str(len(batch))}
        fields.update({f'publishedfileids[{i}]': uid for i, uid in enumerate(batch)})
        req = urllib.request.Request(
            'https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/',
            data=urllib.parse.urlencode(fields).encode(),
            headers={'User-Agent': 'WorkshopTranslator/0.1', 'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.load(response)
        for item in payload.get('response', {}).get('publishedfiledetails', []):
            if item.get('result') == 1:
                details[str(item['publishedfileid'])] = item
    return details


def local_title(path, uid):
    descriptor = path / 'descriptor.mod'
    if descriptor.is_file():
        match = re.search(r'^\s*name\s*=\s*"([^"]+)"', descriptor.read_text(errors='replace'), re.M)
        if match:
            return match[1]
    return f'Mod {uid}'


def english_files(mod_path):
    files = {}
    for folder_name in ('localisation', 'localization'):
        folder = mod_path / folder_name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob('*.yml')):
            if path.is_symlink() or not path.resolve().is_relative_to(mod_path.resolve()):
                continue
            data = path.read_bytes()
            text = data.decode('utf-8-sig')
            if re.search(r'^\s*l_english\s*:', text, re.M):
                files[path.relative_to(mod_path).as_posix()] = data
    return files


def target_path(name, game):
    path = PurePosixPath(name)
    if game == 'eu4':
        return path.as_posix()
    parts = ['simp_chinese' if part == 'english' else part for part in path.parts]
    parts[-1] = parts[-1].replace('l_english', 'l_simp_chinese')
    return PurePosixPath(*parts).as_posix()


class WorkshopService:
    def __init__(self, data_dir=None, demo=False):
        self.demo = demo
        self.data_dir = Path(data_dir or default_data_dir(demo)).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.chmod(0o700)
        self.config_path = self.data_dir / 'config.json'
        if not self.config_path.exists():
            self.save_config(DEFAULT_CONFIG)
        self.database = self.data_dir / 'translations.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS mods (
                    id TEXT PRIMARY KEY, uid TEXT NOT NULL, appid TEXT NOT NULL,
                    title TEXT NOT NULL, path TEXT NOT NULL, url TEXT NOT NULL,
                    seen_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS versions (
                    id INTEGER PRIMARY KEY, mod_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, title TEXT NOT NULL,
                    source_hash TEXT NOT NULL, status TEXT NOT NULL,
                    originals BLOB NOT NULL, chinese BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS deployments (
                    id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL,
                    path TEXT NOT NULL, created_at TEXT NOT NULL,
                    previous_files BLOB NOT NULL);
            ''')
        self.database.chmod(0o600)
        if demo:
            self.setup_demo()
        self.inventory = {}
        self.job = {'running': False, 'kind': '', 'messages': [], 'result': None, 'error': None}
        self.lock = threading.Lock()

    def setup_demo(self):
        mod = self.data_dir / 'demo_steam/steamapps/workshop/content/394360/1000000001'
        if not mod.exists():
            atomic_bytes(mod / 'descriptor.mod', b'name="Workshop Translation Demo"\n')
            atomic_bytes(mod / 'localisation/english/demo_l_english.yml',
                         b'\xef\xbb\xbfl_english:\n demo_title:0 "A new beginning"\n demo_desc:0 "Gain $VALUE$ political power."\n')
        self.save_config({'steam_libraries': [str(self.data_dir / 'demo_steam')]})

    @staticmethod
    def demo_translate(texts, game, already, total):
        known = {'A new beginning': '新的开始', 'Gain $VALUE$ political power.': '获得 $VALUE$ 政治点数。'}
        return [{'text': known.get(text, '演示译文：' + text), 'success': True, 'error': None} for text in texts]

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def config(self):
        return {**DEFAULT_CONFIG, **json.loads(self.config_path.read_text(encoding='utf-8'))}

    def public_config(self):
        cfg = self.config()
        cfg['has_api_key'] = bool(cfg.pop('api_key', ''))
        return cfg

    def save_config(self, changes):
        cfg = self.config() if self.config_path.exists() else dict(DEFAULT_CONFIG)
        allowed = set(DEFAULT_CONFIG)
        cfg.update({key: value for key, value in changes.items() if key in allowed})
        if cfg['api_format'] != 'openai':
            raise ValueError('试运行版支持 OpenAI 兼容的 Chat Completions 格式')
        url = urllib.parse.urlparse(cfg['base_url'])
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
            raise ValueError('API 地址必须是有效的 HTTP(S) URL')
        if not isinstance(cfg['api_key'], str) or not isinstance(cfg['model'], str) or not cfg['model'].strip():
            raise ValueError('请填写有效的模型名称')
        if not isinstance(cfg['steam_libraries'], list) or not all(isinstance(p, str) for p in cfg['steam_libraries']):
            raise ValueError('Steam 库目录格式错误')
        for key, maximum in [('batch_size', 50), ('concurrency', 10)]:
            cfg[key] = int(cfg[key])
            if not 1 <= cfg[key] <= maximum:
                raise ValueError(f'{key} 必须在 1 到 {maximum} 之间')
        atomic_bytes(self.config_path, json.dumps(cfg, ensure_ascii=False, indent=2).encode(), private=True)
        return self.public_config()

    def log(self, message):
        with self.lock:
            self.job['messages'] = (self.job['messages'] + [str(message)])[-300:]

    def start(self, kind, action):
        with self.lock:
            if self.job['running']:
                raise ValueError('已有任务正在运行，请等待完成')
            self.job = {'running': True, 'kind': kind, 'messages': [], 'result': None, 'error': None}
        def run():
            try:
                result = action()
                with self.lock:
                    self.job['result'] = result
            except Exception as error:
                # Avoid exposing API provider exception bodies or credentials.
                self.log(f'任务停止：{type(error).__name__}')
                with self.lock:
                    self.job['error'] = str(error) if isinstance(error, (ValueError, FileNotFoundError, RuntimeError, ImportError)) else type(error).__name__
            finally:
                with self.lock:
                    self.job['running'] = False
        threading.Thread(target=run, daemon=True).start()

    def status(self):
        with self.lock:
            return dict(self.job)

    def scan(self, fetch=workshop_details):
        found = {}
        libraries = ([self.data_dir / 'demo_steam'] if self.demo else steam_libraries(self.config()['steam_libraries']))
        for library in libraries:
            content = library / 'steamapps/workshop/content'
            for appid, (game, game_title) in GAMES.items():
                folder = content / appid
                if not folder.is_dir():
                    continue
                for path in sorted(folder.iterdir()):
                    if path.is_dir() and not path.is_symlink() and path.name.isdigit():
                        uid = path.name
                        identifier = f'{appid}:{uid}'
                        found[identifier] = {'id': identifier, 'uid': uid, 'appid': appid, 'game': game,
                                             'game_title': game_title, 'title': local_title(path, uid),
                                             'path': str(path.resolve()),
                                             'url': f'https://steamcommunity.com/sharedfiles/filedetails/?id={uid}',
                                             'name_source': '本地描述文件', 'translated': False}
        self.log(f'发现 {len(found)} 个 Mod，正在查询创意工坊名称')
        try:
            details = fetch(list(dict.fromkeys(item['uid'] for item in found.values()))) if found and not self.demo else {}
        except Exception:
            details = {}
            self.log('Steam 查询暂不可用，使用本地名称或历史记录')
        with self.connect() as db:
            for identifier, item in found.items():
                existing = db.execute('SELECT title FROM mods WHERE id=?', (identifier,)).fetchone()
                detail = details.get(item['uid'])
                if detail and str(detail.get('consumer_app_id', item['appid'])) == item['appid']:
                    item['title'], item['name_source'] = detail['title'], 'Steam 创意工坊'
                elif existing and item['title'] == f"Mod {item['uid']}":
                    item['title'], item['name_source'] = existing[0], '历史记录'
                db.execute('INSERT OR REPLACE INTO mods VALUES (?,?,?,?,?,?,?)',
                           (identifier, item['uid'], item['appid'], item['title'], item['path'], item['url'], now()))
                item['translated'] = bool(db.execute('SELECT 1 FROM versions WHERE mod_id=? LIMIT 1', (identifier,)).fetchone())
        self.inventory = found
        self.log('扫描完成')
        return list(found.values())

    def history(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('''
                SELECT v.id AS version_id, v.mod_id, m.uid, m.appid, v.title, m.path,
                       m.url, v.created_at, v.status FROM versions v JOIN mods m ON m.id=v.mod_id
                ORDER BY v.id DESC''')]

    def get_mod(self, identifier):
        item = self.inventory.get(identifier)
        if item is None:
            raise ValueError('请先扫描并选择当前已安装的 Mod')
        path = Path(item['path'])
        if not path.is_dir() or path.is_symlink():
            raise ValueError('Mod 目录已不存在，请重新扫描')
        return item

    def original_sources(self, item):
        files = english_files(Path(item['path']))
        # EU4 output replaces English files: use original backups only if disk still
        # matches the last deployed translation. Changed upstream files are re-read.
        if item['game'] == 'eu4':
            with self.connect() as db:
                row = db.execute('''SELECT v.originals,v.chinese FROM deployments d JOIN versions v
                                    ON v.id=d.version_id WHERE v.mod_id=? AND d.path=?
                                    ORDER BY d.id DESC LIMIT 1''', (item['id'], item['path'])).fetchone()
            if row:
                originals, translated = unarchive(row[0]), unarchive(row[1])
                for name, original in originals.items():
                    if files.get(name) == translated.get(name):
                        files[name] = original
        return files

    def translate(self, identifier, translator=None, deploy=True):
        item = self.get_mod(identifier)
        config = self.config()
        if self.demo and translator is None:
            translator = self.demo_translate
        if translator is None and not config['api_key']:
            raise ValueError('请先在设置中保存 API Key')
        try:
            import paradox
            import request
        except ImportError as error:
            raise RuntimeError('请先运行启动脚本安装依赖，或安装 requirements.txt') from error
        if translator is None:
            translator = partial(request.request_deepseek_batch, config=config,
                                 batch_size=config['batch_size'], pool_size=config['concurrency'], progress=self.log)
        sources = self.original_sources(item)
        if not sources:
            raise ValueError('该 Mod 没有可识别的英文 localisation/localization YML 文件')
        workspace = self.data_dir / 'workspaces' / item['appid'] / item['uid']
        inputs = workspace / 'localisation' / item['game']
        if inputs.exists():
            shutil.rmtree(inputs)
        targets = set()
        for name, data in sources.items():
            target = target_path(name, item['game']).casefold()
            if target in targets:
                raise ValueError(f'输出文件名冲突：{name}')
            targets.add(target)
            atomic_bytes(inputs / name, data)
        self.log(f"已复制 {len(sources)} 个英文文件到工作目录；开始翻译（复用匹配缓存）")
        failures = 0
        translated = {}
        with tempfile.TemporaryDirectory(prefix='output-', dir=workspace) as staging_dir:
            staging = Path(staging_dir)
            for index, name in enumerate(sources, 1):
                self.log(f'文件 {index}/{len(sources)}：{name}')
                relative = Path(item['game']) / name
                failures += paradox.translate_para(relative, item['game'], staging, project_root=workspace, translator=translator)
                output = staging / paradox.output_name(relative, item['game'])
                data = output.read_bytes()
                if not data.startswith(b'\xef\xbb\xbf'):
                    data = b'\xef\xbb\xbf' + data
                translated[target_path(name, item['game'])] = data
            if failures:
                raise ValueError(f'{failures} 条翻译失败，成功缓存已保存；未修改 Workshop 文件，点击补充翻译可重试')
            digest = hashlib.sha256(b''.join(name.encode() + b'\0' + hashlib.sha256(data).digest() for name, data in sorted(sources.items()))).hexdigest()
            with self.connect() as db:
                cursor = db.execute('INSERT INTO versions(mod_id,created_at,title,source_hash,status,originals,chinese) VALUES (?,?,?,?,?,?,?)',
                                    (identifier, now(), item['title'], digest, '已备份', archive(sources), archive(translated)))
                version = cursor.lastrowid
        self.log(f'中文文件与英文原文已备份到 SQLite，版本 {version}')
        if deploy:
            self.restore(version, identifier)
        item['translated'] = True
        self.log('翻译完成')
        return {'version_id': version, 'files': len(translated), 'path': item['path'], 'workspace': str(workspace)}

    def restore(self, version_id, identifier):
        item = self.get_mod(identifier)
        with self.connect() as db:
            row = db.execute('SELECT chinese FROM versions WHERE id=? AND mod_id=?', (int(version_id), identifier)).fetchone()
        if not row:
            raise ValueError('未找到对应 Mod 的中文备份')
        files = unarchive(row[0])
        mod = Path(item['path'])
        previous = {}
        missing = []
        destinations = {}
        # Validate every path before any writes; reject symlink escapes.
        for name in files:
            destination = mod / name
            if destination.is_symlink() or not destination.resolve().is_relative_to(mod.resolve()):
                raise ValueError('目标路径包含符号链接或超出 Mod 目录')
            if destination.exists() and not destination.is_file():
                raise ValueError('目标文件被同名目录占用')
            destinations[name] = destination
            if destination.is_file():
                previous[name] = destination.read_bytes()
            else:
                missing.append(name)
        # Persist rollback data before copying into Steam-managed files.
        with self.connect() as db:
            cursor = db.execute('INSERT INTO deployments(version_id,path,created_at,previous_files) VALUES (?,?,?,?)',
                                (int(version_id), item['path'], now(), archive(previous)))
            deployment = cursor.lastrowid
        written = []
        try:
            for name, data in files.items():
                atomic_bytes(destinations[name], data)
                written.append(name)
        except BaseException:
            for name in reversed(written):
                if name in previous:
                    atomic_bytes(destinations[name], previous[name])
                else:
                    destinations[name].unlink(missing_ok=True)
            with self.connect() as db:
                db.execute('DELETE FROM deployments WHERE id=?', (deployment,))
            raise
        with self.connect() as db:
            db.execute("UPDATE versions SET status='已回写' WHERE id=?", (int(version_id),))
        self.log(f'已将 {len(files)} 个中文文件复制到 {mod}')
        return {'files': len(files), 'path': str(mod), 'version_id': int(version_id)}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, service):
        self.service, self.token = service, secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body, content_type='application/json; charset=utf-8'):
        data = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, (dict, list)) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return self.headers.get('Host') == expected and secrets.compare_digest(self.headers.get('X-App-Token', ''), self.server.token)

    def do_GET(self):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            return self.send(403, {'error': '仅支持本机访问'})
        if self.path == '/':
            page = (ROOT / 'workshop_ui.html').read_text(encoding='utf-8').replace('__APP_TOKEN__', self.server.token)
            return self.send(200, page.encode(), 'text/html; charset=utf-8')
        if not self.authorized():
            return self.send(403, {'error': '访问令牌无效'})
        if self.path == '/api/state':
            service = self.server.service
            return self.send(200, {'config': service.public_config(), 'mods': list(service.inventory.values()),
                                   'history': service.history(), 'job': service.status(), 'data_dir': str(service.data_dir), 'demo': service.demo})
        self.send(404, {'error': '未找到'})

    def do_POST(self):
        if not self.authorized():
            return self.send(403, {'error': '访问令牌无效'})
        service = self.server.service
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('请求大小错误')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('请求格式错误')
            if self.path == '/api/config':
                if service.status()['running']:
                    raise ValueError('请等待任务结束后修改配置')
                return self.send(200, service.save_config(body))
            if self.path == '/api/scan':
                service.start('scan', service.scan)
            elif self.path == '/api/translate':
                identifier = body['id']
                service.get_mod(identifier)
                service.start('translate', lambda: service.translate(identifier))
            elif self.path == '/api/restore':
                identifier, version = body['id'], int(body['version_id'])
                service.get_mod(identifier)
                service.start('restore', lambda: service.restore(version, identifier))
            elif self.path == '/api/open':
                identifier = body['id']
                item = service.get_mod(identifier)
                open_folder(item['path'])
                return self.send(200, {'ok': True})
            else:
                return self.send(404, {'error': '未找到'})
            self.send(202, {'ok': True})
        except (ValueError, KeyError, TypeError) as error:
            self.send(400, {'error': str(error)})
        except Exception as error:
            self.send(500, {'error': type(error).__name__})


def self_test():
    # Run on the actual packaged executable, without Steam, credentials or network.
    import request
    if request.OpenAI is None:
        raise RuntimeError('打包缺少 openai 依赖')
    request.findrule('hoi4')
    page = (ROOT / 'workshop_ui.html').read_text(encoding='utf-8')
    assert '__APP_TOKEN__' in page
    with tempfile.TemporaryDirectory() as directory:
        service = WorkshopService(Path(directory), demo=True)
        item = service.scan()[0]
        result = service.translate(item['id'])
        output = Path(item['path']) / 'localisation/simp_chinese/demo_l_simp_chinese.yml'
        assert '新的开始' in output.read_text(encoding='utf-8-sig')
        output.unlink()
        service.restore(result['version_id'], item['id'])
        assert output.is_file() and len(service.history()) == 1
        assert service.config()['api_key'] == ''
    print('WORKSHOP_TRANSLATOR_SELF_TEST_OK', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Workshop 翻译程序 · Windows / macOS')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--demo', action='store_true', help='模拟 Mod 与模型回复，不调用 Steam 或付费接口')
    parser.add_argument('--self-test', action='store_true', help='离线检查打包资源、翻译、数据库和文件恢复')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    service = WorkshopService(args.data_dir, demo=args.demo)
    server = AppServer(('127.0.0.1', args.port), service)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Workshop 翻译程序：{url}\n数据目录：{service.data_dir}\n按 Ctrl+C 停止', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        main()
    except Exception as error:
        print(f'启动失败：{type(error).__name__}: {error}', file=sys.stderr)
        if getattr(sys, 'frozen', False) and '--self-test' not in sys.argv and sys.stdin is not None and sys.stdin.isatty():
            input('按 Enter 退出。')
        raise SystemExit(1)
