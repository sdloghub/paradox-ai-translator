#!/usr/bin/env python3
"""Local Workshop inventory, translation workspaces and SQLite backup service."""
import argparse

_STARTUP_STARTED = __import__("time").perf_counter()
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
APP_VERSION = '2026.10.16-aggregate.1'


def program_directory():
    if not getattr(sys, 'frozen', False):
        return ROOT
    executable = Path(sys.executable).resolve()
    if sys.platform == 'darwin' and executable.parent.name == 'MacOS' and executable.parent.parent.name == 'Contents':
        return executable.parent.parent.parent.parent
    return executable.parent


def default_data_dir(demo=False):
    suffix = 'app_data_demo' if demo else 'app_data'
    if getattr(sys, 'frozen', False):
        if os.name == 'nt':
            base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
        else:
            base = Path.home() / 'Library/Application Support'
        return base / 'WorkshopTranslator' / suffix
    return ROOT / suffix


def user_config_dir():
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path.home() / '.config'
    return base / 'WorkshopTranslator/app_data'


def open_folder(path):
    if os.name == 'nt':
        os.startfile(str(path))
    else:
        import subprocess
        subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)], check=True)

GAMES = {'281990': ('st', '群星'), '394360': ('hoi4', '钢铁雄心4'),
         '236850': ('eu4', '欧陆风云4'), '1158310': ('ck3', '十字军之王3'),
         '529340': ('vic3', '维多利亚3')}
DEFAULT_CONFIG = {'api_format': 'openai', 'provider': '', 'config_name': '', 'base_url': 'https://api.openai.com/v1',
                  'api_key': '', 'model': 'gpt-4.1-mini', 'batch_size': 10,
                  'concurrency': 3, 'steam_libraries': [], 'aggregate_export': True}


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
    def __init__(self, data_dir=None, demo=False, program_dir=None):
        self.demo = demo
        self.data_dir = Path(data_dir or default_data_dir(demo)).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.chmod(0o700)
        self.completed_path = self.data_dir / 'completed.json'
        bundle = Path(program_dir or program_directory()).resolve()
        self.config_directories = {'portable': bundle, 'user': self.data_dir if data_dir is not None or demo else user_config_dir().resolve()}
        self.storage_marker = self.data_dir / 'config-storage.json'
        self.storage_mode = 'user'
        for marker in (self.storage_marker, bundle / 'config-storage.json'):
            if marker.is_file():
                saved = json.loads(marker.read_text(encoding='utf-8'))
                if marker == self.storage_marker and saved.get('program_dir', str(bundle)) != str(bundle):
                    continue
                choice = saved.get('mode')
                if choice not in self.config_directories:
                    raise ValueError('配置保存模式无效')
                self.storage_mode = choice
                break
        config_dir = self.config_directories[self.storage_mode]
        config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = config_dir / 'config.json'
        self.providers_path = config_dir / 'providers.json'
        # Retain legacy development settings when moving to the user directory.
        if self.storage_mode == 'user' and config_dir != self.data_dir:
            for name in ('config.json', 'providers.json'):
                old = self.data_dir / name
                if old.is_file() and not (config_dir / name).exists():
                    atomic_bytes(config_dir / name, old.read_bytes(), private=True)
        if not self.providers_path.exists() and not demo and (bundle / 'providers.json').is_file():
            atomic_bytes(self.providers_path, (bundle / 'providers.json').read_bytes(), private=True)
        if not self.config_path.exists():
            template = bundle / 'config.json'
            self.save_config(json.loads(template.read_text(encoding='utf-8')) if template.is_file() and not demo else DEFAULT_CONFIG)
        if not self.providers_path.exists():
            atomic_bytes(self.providers_path, json.dumps({'format': 'workshop-providers-v1', 'profiles': {}}).encode(), private=True)
        self.database = self.data_dir / 'translations.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS mods (
                    id TEXT PRIMARY KEY, uid TEXT NOT NULL, appid TEXT NOT NULL,
                    title TEXT NOT NULL, path TEXT NOT NULL, url TEXT NOT NULL,
                    seen_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scan_snapshots (
                    mod_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    metadata_ok INTEGER NOT NULL, item_json TEXT NOT NULL);
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
        with self.connect() as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(versions)')}
            if 'provider' not in columns:
                db.execute("ALTER TABLE versions ADD COLUMN provider TEXT NOT NULL DEFAULT ''")
            if 'origins' not in columns:
                db.execute("ALTER TABLE versions ADD COLUMN origins TEXT NOT NULL DEFAULT '[]'")
            db.execute('CREATE TABLE IF NOT EXISTS seed_imports (path TEXT PRIMARY KEY, signature TEXT NOT NULL)')
            db.execute("CREATE TABLE IF NOT EXISTS source_runs (id INTEGER PRIMARY KEY, kind TEXT, name TEXT, created_at TEXT)")
        self.database.chmod(0o600)
        from translation_cache import ModCache
        self.cache = ModCache(self)
        self.load_completed_seed()
        if demo:
            self.setup_demo()
        with self.connect() as db:
            self.inventory = {row[0]: json.loads(row[1]) for row in
                              db.execute('SELECT mod_id,item_json FROM scan_snapshots')}
        for item in self.inventory.values():
            item.setdefault('scan_state', '待复查' if item.get('counts') else '未扫描')
        self.job = {'running': False, 'kind': '', 'messages': [], 'result': None, 'error': None}
        self.lock = threading.Lock()

    def setup_demo(self):
        mod = self.data_dir / 'demo_steam/steamapps/workshop/content/394360/1000000001'
        if not mod.exists():
            atomic_bytes(mod / 'descriptor.mod', b'name="Workshop Translation Demo"\n')
            atomic_bytes(mod / 'localisation/english/demo_l_english.yml',
                         b'\xef\xbb\xbfl_english:\n demo_title:0 "A new beginning"\n demo_desc:0 "Gain $VALUE$ political power."\n')
        manifest = mod.parents[1].parent / 'appworkshop_394360.acf'
        if not manifest.exists():
            atomic_bytes(manifest, b'"AppWorkshop" { "appid" "394360" "WorkshopItemsInstalled" { "1000000001" { "size" "100" "timeupdated" "1" "manifest" "1" } } "WorkshopItemDetails" { "1000000001" { "latest_manifest" "1" "latest_timeupdated" "1" } } }')
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

    def config_storage(self):
        return {'mode': self.storage_mode, 'path': str(self.config_path),
                'directories': {mode: str(path) for mode, path in self.config_directories.items()}}

    def switch_config_storage(self, mode):
        if mode not in self.config_directories:
            raise ValueError('请选择程序文件夹或用户文件夹')
        with self.lock:
            if self.job['running']:
                raise ValueError('请等待任务结束后切换配置保存位置')
            if mode == self.storage_mode:
                return self.config_storage()
            current = self.config()
            registry = json.loads(self.providers_path.read_text(encoding='utf-8'))
            target = self.config_directories[mode]
            try:
                target.mkdir(parents=True, exist_ok=True)
                old_registry = json.loads((target / 'providers.json').read_text(encoding='utf-8')) if (target / 'providers.json').is_file() else {}
                profiles = dict(old_registry.get('profiles', {}))
                old_config = json.loads((target / 'config.json').read_text(encoding='utf-8')) if (target / 'config.json').is_file() else {}
                if old_config.get('api_key') or old_config.get('config_name'):
                    old_name = old_config.get('config_name') or '原目标配置'
                    profiles.setdefault(old_name, old_config)
                for name, profile in registry.get('profiles', {}).items():
                    existing = profiles.get(name)
                    if existing and {k: v for k, v in existing.items() if k != 'saved_at'} != {k: v for k, v in profile.items() if k != 'saved_at'}:
                        number = 1
                        while f'{name}（保留 {number}）' in profiles:
                            number += 1
                        alias = f'{name}（保留 {number}）'
                        profiles[alias] = {**existing, 'config_name': alias}
                    profiles[name] = profile
                merged = {**old_registry, **registry, 'profiles': profiles,
                          'sources': {**old_registry.get('sources', {}), **registry.get('sources', {})}}
                atomic_bytes(target / 'providers.json', json.dumps(merged, ensure_ascii=False, indent=2).encode(), private=True)
                atomic_bytes(target / 'config.json', json.dumps(current, ensure_ascii=False, indent=2).encode(), private=True)
                marker = json.dumps({'mode': mode, 'program_dir': str(self.config_directories['portable'])}, ensure_ascii=False).encode()
                # Portable mode follows the program folder when copied to another PC.
                if mode == 'portable':
                    atomic_bytes(target / 'config-storage.json', marker, private=True)
                atomic_bytes(self.storage_marker, marker, private=True)
                if mode == 'user' and (self.config_directories['portable'] / 'config-storage.json').exists():
                    try:
                        atomic_bytes(self.config_directories['portable'] / 'config-storage.json', marker, private=True)
                    except OSError:
                        pass
            except PermissionError as error:
                raise ValueError('无法写入所选文件夹，请选择有写入权限的位置，或使用用户文件夹模式') from error
            self.storage_mode = mode
            self.config_path = target / 'config.json'
            self.providers_path = target / 'providers.json'
            return self.config_storage()

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
        if type(cfg['aggregate_export']) is not bool:
            raise ValueError('聚合汉化开关必须为开启或关闭')
        for key, maximum in [('batch_size', 50), ('concurrency', 10)]:
            cfg[key] = int(cfg[key])
            if not 1 <= cfg[key] <= maximum:
                raise ValueError(f'{key} 必须在 1 到 {maximum} 之间')
        if not isinstance(cfg.get('provider', ''), str) or len(cfg.get('provider', '')) > 120:
            raise ValueError('提供商名称需为 120 字以内的文字')
        cfg['provider'] = cfg.get('provider', '').strip()
        if not isinstance(cfg.get('config_name', ''), str) or len(cfg.get('config_name', '')) > 120:
            raise ValueError('配置名称需为 120 字以内的文字')
        cfg['config_name'] = cfg.get('config_name', '').strip()
        atomic_bytes(self.config_path, json.dumps(cfg, ensure_ascii=False, indent=2).encode(), private=True)
        if self.providers_path.exists():
            registry = json.loads(self.providers_path.read_text(encoding='utf-8'))
        else:
            registry = {'format': 'workshop-providers-v1', 'profiles': {}}
        if cfg['config_name'] or cfg['provider'] or cfg['api_key']:
            label = cfg['config_name'] or cfg['provider'] or registry.get('active') or f"翻译-{datetime.now().date()}-1"
            registry['active'] = label
            registry['profiles'][label] = {**cfg, 'config_name': label, 'provider': cfg['provider'] or label, 'saved_at': now()}
        atomic_bytes(self.providers_path, json.dumps(registry, ensure_ascii=False, indent=2).encode(), private=True)
        return self.public_config()

    def profiles(self):
        registry = json.loads(self.providers_path.read_text(encoding='utf-8'))
        return [{'name': name, 'provider': profile.get('provider', name),
                 'base_url': profile.get('base_url', ''), 'model': profile.get('model', ''),
                 'has_api_key': bool(profile.get('api_key'))}
                for name, profile in registry.get('profiles', {}).items()]

    def switch_profile(self, name):
        if self.status()['running']:
            raise ValueError('请等待任务结束后切换配置')
        registry = json.loads(self.providers_path.read_text(encoding='utf-8'))
        profile = registry.get('profiles', {}).get(name)
        if not isinstance(profile, dict):
            raise ValueError('未找到已保存的 API 配置')
        # Profile changes API settings only; keep this computer's Steam directories.
        fields = ('api_format', 'provider', 'config_name', 'api_key', 'base_url', 'model', 'batch_size', 'concurrency')
        changes = {key: profile[key] for key in fields if key in profile}
        changes['config_name'] = name
        changes['provider'] = profile.get('provider') or name
        changes.setdefault('api_key', '')
        return self.save_config(changes)

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
                from paradox import LocalisationError
                detail = f'：{error}' if isinstance(error, LocalisationError) else ''
                self.log(f'任务停止：{type(error).__name__}{detail}')
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
        found, fingerprints = {}, {}
        libraries = ([self.data_dir / 'demo_steam'] if self.demo else steam_libraries(self.config()['steam_libraries']))
        for library in libraries:
            content = library / 'steamapps/workshop/content'
            for appid, (game, game_title) in GAMES.items():
                folder = content / appid
                if not folder.is_dir() or folder.is_symlink():
                    continue
                installed, reason = installed_workshop_items(library, appid)
                if installed is None:
                    self.log(f'{game_title}：{reason}，使用目录回退')
                    paths = sorted(folder.iterdir())
                else:
                    paths = [folder / uid for uid in sorted(installed)]
                for path in paths:
                    if path.is_dir() and not path.is_symlink() and re.fullmatch(r'[0-9]+', path.name):
                        uid = path.name
                        identifier = f'{appid}:{uid}'
                        record = installed[uid] if installed is not None else {}
                        fingerprints[identifier] = (installed_stamp(record) if installed is not None
                                                     else directory_stamp(path))
                        found[identifier] = {'id': identifier, 'uid': uid, 'appid': appid, 'game': game,
                                             'game_title': game_title, 'title': f'Mod {uid}',
                                             'path': str(path.resolve()),
                                             'url': f'https://steamcommunity.com/sharedfiles/filedetails/?id={uid}',
                                             'name_source': '本地描述文件', 'translated': False,
                                             'discovery_source': 'Steam ACF' if installed is not None else '目录回退',
                                             'workshop': record,
                                             'steam_update_pending': workshop_update_pending(record)}
        with self.connect() as db:
            snapshots = {row[0]: row[1:] for row in db.execute(
                'SELECT mod_id,fingerprint,metadata_ok,item_json FROM scan_snapshots')}
        pending = []
        for identifier, item in found.items():
            cached = snapshots.get(identifier)
            old = json.loads(cached[2]) if cached else {}
            unchanged = cached and cached[0] == fingerprints[identifier] and old['path'] == item['path']
            if old and old['path'] == item['path']:
                # Keep prior counts/title, but always use this refresh's ACF data.
                fresh = dict(item)
                item.update(old)
                item.update({key: value for key, value in fresh.items()
                             if key not in ('title', 'name_source', 'translated')})
                if not unchanged:
                    item['scan_state'] = '待复查' if old.get('counts') else '未扫描'
            else:
                item['scan_state'] = '未扫描'
            if not unchanged or not cached[1]:
                if not old:
                    item['title'] = local_title(Path(item['path']), item['uid'])
                pending.append(identifier)
        self.log(f'清单刷新：发现 {len(found)} 个本机 Mod，优先读取 Steam ACF；未读取翻译内容')
        try:
            details = fetch(list(dict.fromkeys(found[key]['uid'] for key in pending))) if pending and not self.demo else {}
        except Exception:
            details = {}
            self.log('Steam 查询暂不可用，保留历史名称；下次扫描重试')
        with self.connect() as db:
            for identifier, item in found.items():
                existing = db.execute('SELECT title FROM mods WHERE id=?', (identifier,)).fetchone()
                detail = details.get(item['uid'])
                valid = bool(detail and detail.get('title') and
                             str(detail.get('consumer_app_id', item['appid'])) == item['appid'])
                item['_metadata_ok'] = self.demo or valid or (identifier not in pending)
                if valid:
                    item['title'], item['name_source'] = detail['title'], 'Steam 创意工坊'
                elif existing and identifier in pending:
                    item['title'], item['name_source'] = existing[0], '历史记录'
                db.execute('INSERT OR REPLACE INTO mods VALUES (?,?,?,?,?,?,?)',
                           (identifier, item['uid'], item['appid'], item['title'], item['path'], item['url'], now()))
                item['translated'] = bool(db.execute('SELECT 1 FROM versions WHERE mod_id=? LIMIT 1', (identifier,)).fetchone())
        self.inventory = found
        with self.connect() as db:
            db.execute('DELETE FROM scan_snapshots')
            for identifier, item in found.items():
                self.persist_item(item, fingerprints[identifier], db)
        self.log('目录刷新完成，未扫描的 Mod 请进入工作台扫描')
        return list(found.values())

    def persist_item(self, item, fingerprint=None, db=None):
        if db is None:
            with self.connect() as connection:
                self.persist_item(item, fingerprint, connection)
            return
        # Only a scan validates the file fingerprint. Other actions update stats
        # without acknowledging unseen changes in the Mod directory.
        cached = db.execute('SELECT fingerprint,metadata_ok FROM scan_snapshots WHERE mod_id=?', (item['id'],)).fetchone()
        db.execute('INSERT OR REPLACE INTO scan_snapshots VALUES (?,?,?,?)',
                   (item['id'], fingerprint if fingerprint is not None else (cached[0] if cached else ''),
                    int(item.get('_metadata_ok', cached[1] if cached else False)),
                    json.dumps(item, ensure_ascii=False)))

    def source_label(self, kind, provider=''):
        if not isinstance(provider, str) or len(provider) > 120:
            raise ValueError('来源名称需为 120 字以内的文字')
        with self.connect() as db:
            date = str(datetime.now().date())
            revision = db.execute('SELECT COUNT(*) FROM source_runs WHERE created_at LIKE ?', (date + '%',)).fetchone()[0] + 1
            label = provider.strip() or f'翻译-{date}-{revision}'
            db.execute('INSERT INTO source_runs(kind,name,created_at) VALUES (?,?,?)', (kind, label, datetime.now().isoformat()))
        registry = json.loads(self.providers_path.read_text(encoding='utf-8'))
        if kind == 'AI':
            profile_name = self.config().get('config_name') or label
            registry.setdefault('profiles', {})[profile_name] = {**self.config(), 'config_name': profile_name, 'provider': self.config().get('provider') or label, 'saved_at': now()}
            registry['active'] = profile_name
        registry.setdefault('sources', {})[label] = {'kind': kind, 'name': label, 'updated_at': now()}
        atomic_bytes(self.providers_path, json.dumps(registry, ensure_ascii=False, indent=2).encode(), private=True)
        return label

    def save_completed(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute('SELECT * FROM translation_entries')]
        atomic_bytes(self.completed_path, json.dumps({'format': 'workshop-completed-v1', 'entries': rows}, ensure_ascii=False, indent=2).encode(), private=True)

    def load_completed_seed(self):
        bundle = program_directory()
        if not self.providers_path.exists():
            atomic_bytes(self.providers_path, b'{"format":"workshop-providers-v1","profiles":{}}', private=True)
        seed = bundle / 'completed.json'
        if not seed.is_file() or self.demo:
            return
        stat = seed.stat()
        signature = f'{stat.st_size}:{stat.st_mtime_ns}'
        with self.connect() as db:
            existing = db.execute('SELECT signature FROM seed_imports WHERE path=?', (str(seed.resolve()),)).fetchone()
        if existing and existing[0] == signature:
            return
        payload = json.loads(seed.read_text(encoding='utf-8'))
        if payload.get('format') != 'workshop-completed-v1':
            raise ValueError('完成标记文件格式错误')
        from translation_cache import digest
        imported = 0
        with self.connect() as db:
            for row in payload.get('entries', []):
                if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ('mod_id','source_file','entry_key','source_hash','chinese','chinese_hash','origin')):
                    continue
                if not re.fullmatch(r'[0-9a-f]{64}', row['source_hash']) or digest(row['chinese']) != row['chinese_hash']:
                    continue
                imported += db.execute('INSERT OR IGNORE INTO translation_entries(mod_id,source_file,entry_key,source_hash,chinese,chinese_hash,origin) VALUES (?,?,?,?,?,?,?)', tuple(row[key] for key in ('mod_id','source_file','entry_key','source_hash','chinese','chinese_hash','origin'))).rowcount
            db.execute('INSERT OR REPLACE INTO seed_imports VALUES (?,?)', (str(seed.resolve()), signature))
        if imported:
            self.save_completed()

    def history(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('''
                SELECT v.id AS version_id, v.mod_id, m.uid, m.appid, v.title, m.path,
                       m.url, v.created_at, v.status, v.provider, v.origins FROM versions v JOIN mods m ON m.id=v.mod_id
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

    def edit_entry(self, identifier, entry_id, replacement):
        if not isinstance(replacement, str) or len(replacement) > 16000:
            raise ValueError('原文件行最多 16000 个字符')
        if any(char in replacement for char in '\r\n\x00\x85\u2028\u2029\ufeff'):
            raise ValueError('一次只能修改一行，请勿包含换行符或文件头标记')
        item = self.get_mod(identifier)
        row = self.cache.browser.get(identifier, entry_id)
        relative = PurePosixPath(row['source_file'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in row['source_file'] or relative.suffix.lower() != '.yml':
            raise ValueError('原文件路径无效')
        root = Path(item['path']).resolve()
        source = root.joinpath(*relative.parts)
        if not source.resolve().is_relative_to(root) or any(path.is_symlink() for path in (source, *source.parents) if path != root and root in path.parents):
            raise ValueError('不能修改符号链接或 Mod 目录之外的文件')
        before = source.read_bytes()
        # EU4 deployments replace English files. Never mistake deployed Chinese
        # for the source snapshot and overwrite it while editing an English row.
        if item['game'] == 'eu4' and self.original_sources(item).get(row['source_file']) != before:
            raise ValueError('该文件目前是回写后的中文，请先恢复英文原文件后再编辑原行')
        text = before.decode('utf-8-sig')
        lines = text.splitlines(keepends=True)
        number = row['line']
        if not 1 <= number <= len(lines) or lines[number - 1].rstrip('\r\n') != row['original_line']:
            raise ValueError('原文件已在其他位置修改，请重新扫描后再编辑，避免覆盖新内容')
        old_line = lines[number - 1]
        ending = old_line[len(old_line.rstrip('\r\n')):]
        lines[number - 1] = replacement + ending
        updated = ''.join(lines).encode('utf-8')
        if before.startswith(b'\xef\xbb\xbf'):
            updated = b'\xef\xbb\xbf' + updated
        backup = None
        if updated != before:
            backup = self.data_dir / 'source_backups' / item['appid'] / item['uid'] / (str(time.time_ns()) + '-' + secrets.token_hex(4))
            backup = backup.joinpath(*relative.parts)
            atomic_bytes(backup, before, private=True)
            if source.is_symlink() or not source.resolve().is_relative_to(root) or source.read_bytes() != before:
                raise ValueError('保存前原文件发生变化，已取消覆盖，请重新扫描')
            mode = source.stat().st_mode & 0o777
            atomic_bytes(source, updated)
            source.chmod(mode)
            self.log(f'已修改原文件：{source}，第 {number} 行；原文件备份：{backup}')
        counts = self.analyze(identifier)
        issue = next((issue for issue in counts['issues'] if issue['file'] == row['source_file'] and issue['line'] == number), None)
        self.log(f"保存后复查：第 {number} 行{'仍有格式错误' if issue else '未发现格式错误'}；当前 Mod 格式错误 {counts['parse_errors']} 行")
        return {'file': row['source_file'], 'line': number, 'parse_error': bool(issue),
                'reason': issue['reason'] if issue else '', 'backup_path': str(backup) if backup else '', 'counts': counts}

    def analyze(self, identifier):
        from translation_cache import candidates
        item = self.get_mod(identifier)
        sources = self.original_sources(item)
        imported = self.cache.import_candidates(item, sources, candidates(item['path'], item['game']), '本机中文')
        self.cache.sync_workspace(item, sources)
        item['counts'] = self.cache.stats(item, sources)
        item['scan_state'] = '已扫描'
        self.log(f"{item['title']}：已翻译 {item['counts']['deployed']} / 已缓存 {item['counts']['cached']} / 待翻译 {item['counts']['untranslated']} / 格式报错 {item['counts']['parse_errors']} 行")
        for problem in item['counts']['issues']:
            self.log(f"原文件：{Path(item['path']) / problem['file']}，第 {problem['line']} 行\n原因：{problem['reason']}\n原文：{problem['original_line']}")
        self.persist_item(item)
        self.save_completed()
        return {**item['counts'], **imported}

    def import_cache(self, identifier, path, provider=""):
        from translation_cache import candidates
        item = self.get_mod(identifier)
        chosen = Path(path).expanduser()
        if not chosen.exists():
            raise ValueError('所选文件或目录不存在')
        sources = self.original_sources(item)
        translations = candidates(chosen, item['game'])
        label = self.source_label('导入', provider)
        result = self.cache.import_candidates(item, sources, translations, '导入 · ' + label)
        self.cache.sync_workspace(item, sources)
        item['counts'] = self.cache.stats(item, sources)
        item['scan_state'] = '已扫描'
        self.log(f"导入完成：新增 {result['imported']} 条，跳过不匹配或冲突 {result['rejected']} 条")
        warning = '导入缓存无法检查 Steam 上尚未安装的原文更新；仅校验本机英文。无原文哈希的中文文件无法判断是否需要更新，请确认来源版本。'
        self.log(warning)
        self.persist_item(item)
        self.save_completed()
        return {**result, **item['counts'], 'provider': label, 'warning': warning}

    def translate(self, identifier, translator=None, deploy=True, provider=None):
        item = self.get_mod(identifier)
        self.analyze(identifier)
        config = self.config()
        if self.demo and translator is None:
            translator = self.demo_translate
        if translator is None and not config['api_key'] and item['counts']['untranslated']:
            raise ValueError('请先在设置中保存 API Key')
        try:
            import paradox
            import request
        except ImportError as error:
            raise RuntimeError('请先运行启动脚本安装依赖，或安装 requirements.txt') from error
        if translator is None:
            translator = partial(request.request_deepseek_batch, config=config,
                                 batch_size=config['batch_size'], pool_size=config['concurrency'], progress=self.log)
        label = self.source_label('AI', config.get('provider', '') if provider is None else provider) if item['counts']['untranslated'] else '缓存复用'
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
        issues = []
        translated = {}
        with tempfile.TemporaryDirectory(prefix='output-', dir=workspace) as staging_dir:
            staging = Path(staging_dir)
            for index, name in enumerate(sources, 1):
                self.log(f'文件 {index}/{len(sources)}：{name}')
                relative = Path(item['game']) / name
                file_issues = []
                failures += paradox.translate_para(relative, item['game'], staging, project_root=workspace, translator=translator, issues=file_issues)
                issues.extend({**problem, 'file': name, 'original_file': str(Path(item['path']) / name)} for problem in file_issues)
                output = staging / paradox.output_name(relative, item['game'])
                data = output.read_bytes()
                if not data.startswith(b'\xef\xbb\xbf'):
                    data = b'\xef\xbb\xbf' + data
                translated[target_path(name, item['game'])] = data
            self.cache.sync_workspace(item, sources, origin='AI · ' + label)
            item['counts'] = self.cache.stats(item, sources)
            item['scan_state'] = '已扫描'
            self.persist_item(item)
            self.save_completed()
            atomic_bytes(workspace / 'translation-report.json', json.dumps({'error_lines': len(issues), 'issues': issues}, ensure_ascii=False, indent=2).encode('utf-8'))
            digest = hashlib.sha256(b''.join(name.encode() + b'\0' + hashlib.sha256(data).digest() for name, data in sorted(sources.items()))).hexdigest()
            with self.connect() as db:
                cursor = db.execute('INSERT INTO versions(mod_id,created_at,title,source_hash,status,originals,chinese,provider,origins) VALUES (?,?,?,?,?,?,?,?,?)',
                                    (identifier, now(), item['title'], digest, '已备份', archive(sources), archive(translated), label, json.dumps(item['counts']['origins'], ensure_ascii=False)))
                version = cursor.lastrowid
        self.log(f'中文文件与英文原文已备份到 SQLite，版本 {version}')
        aggregate = {'enabled':False, 'pending_deployment':True}
        if deploy:
            aggregate = self.restore(version, identifier)['aggregate']
        if issues:
            with self.connect() as db:
                db.execute('UPDATE versions SET status=? WHERE id=?', (f'{"已回写" if deploy else "已备份"}（{len(issues)} 行保留英文）', version))
        item['translated'] = True
        self.persist_item(item)
        self.save_completed()
        self.log('翻译完成 · 来源：' + label)
        for problem in issues:
            self.log(f"原文件：{problem['original_file']}，第 {problem['line']} 行\n原因：{problem['reason']}\n原文：{problem['original_line']}")
        self.log(f'任务结束：报错 {len(issues)} 行，已将对应英文原行保留在翻译文件中；完整明细：{workspace / "translation-report.json"}')
        return {'version_id': version, 'files': len(translated), 'path': item['path'], 'workspace': str(workspace), 'provider': label, 'error_lines': len(issues), 'issues': issues, 'aggregate':aggregate}

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
        item['counts'] = self.cache.stats(item, self.original_sources(item))
        item['scan_state'] = '已扫描'
        self.persist_item(item)
        self.log(f'已将 {len(files)} 个中文文件复制到 {mod}')
        try:
            from aggregate_export import export
            aggregate = export(self, item, files, version_id)
            if aggregate['enabled']:
                self.log(f"已复制 {aggregate['files']} 个文件到聚合汉化目录：{aggregate['path']}")
                for warning in aggregate['warnings']:
                    self.log(warning)
        except Exception as error:
            aggregate = {'enabled':True, 'error':f'{type(error).__name__}: {error}'}
            self.log('原 Mod 已完成回写；聚合汉化复制失败：' + aggregate['error'])
        return {'files': len(files), 'path': str(mod), 'version_id': int(version_id), 'aggregate':aggregate}


def parse_keyvalues(text):
    """Parse nested Steam text KeyValues without losing 64-bit manifest strings."""
    token = re.compile(r'\s+|//[^\r\n]*|"(?:\\.|[^"\\])*"|[{}]')
    tokens, offset = [], 0
    text = text.lstrip('\ufeff')
    while offset < len(text):
        match = token.match(text, offset)
        if not match:
            raise ValueError('ACF 包含无效内容')
        value = match.group()
        offset = match.end()
        if value.isspace() or value.startswith('//'):
            continue
        tokens.append(value)
    index = 0

    def string(value):
        return re.sub(r'\\(["\\])', r'\1', value[1:-1])

    def block(nested=False, depth=0):
        nonlocal index
        if depth > 32:
            raise ValueError('ACF 嵌套过深')
        result = {}
        while index < len(tokens):
            key = tokens[index]
            index += 1
            if key == '}':
                if nested:
                    return result
                raise ValueError('ACF 大括号不匹配')
            if not key.startswith('"') or index >= len(tokens):
                raise ValueError('ACF 键值不完整')
            key = string(key)
            if key in result:
                raise ValueError('ACF 包含重复键')
            value = tokens[index]
            index += 1
            if value == '{':
                result[key] = block(True, depth + 1)
            elif value.startswith('"'):
                result[key] = string(value)
            else:
                raise ValueError('ACF 键值不完整')
        if nested:
            raise ValueError('ACF 文件未写完整')
        return result

    return block()


def installed_workshop_items(library, appid):
    """Read each game's ACF once. None means fallback; an empty dict is authoritative."""
    manifest = library / 'steamapps/workshop' / f'appworkshop_{appid}.acf'
    if not manifest.is_file() or manifest.is_symlink():
        return None, 'ACF 清单缺失'
    try:
        root = parse_keyvalues(manifest.read_text(encoding='utf-8-sig'))['AppWorkshop']
        if not isinstance(root, dict) or root.get('appid', appid) != appid:
            raise ValueError('ACF 游戏 ID 不匹配')
        installed = root['WorkshopItemsInstalled']
        details = root.get('WorkshopItemDetails', {})
        if not isinstance(installed, dict) or not isinstance(details, dict):
            raise ValueError('ACF 安装清单格式错误')
        records = {}
        for uid, item in installed.items():
            if not re.fullmatch(r'[0-9]+', uid) or not isinstance(item, dict):
                raise ValueError('ACF 物品格式错误')
            record = {}
            for field in ('manifest', 'timeupdated', 'size'):
                value = item.get(field, '')
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
                    raise ValueError('ACF 安装信息不完整')
                record[field] = value
            latest = details.get(uid, {})
            if not isinstance(latest, dict):
                raise ValueError('ACF 详情格式错误')
            for field in ('latest_manifest', 'latest_timeupdated'):
                value = latest.get(field, '')
                if not isinstance(value, str) or (value and not re.fullmatch(r'[0-9]+', value)):
                    raise ValueError('ACF 最新版本信息错误')
                record[field] = value
            records[uid] = record
        return records, ''
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        # Steam may currently be rewriting the file. Do not treat it as uninstall.
        return None, 'ACF 暂不可读或格式不完整'


def installed_stamp(record):
    # latest/touched/subscriber changes do not mean the local content changed.
    values = ['acf-installed-v1', record['manifest'], record['timeupdated'], record['size']]
    return hashlib.sha256('\0'.join(values).encode()).hexdigest()


def workshop_update_pending(record):
    return bool((record.get('latest_manifest') and record['latest_manifest'] != record.get('manifest'))
                or (record.get('latest_timeupdated') and record.get('timeupdated')
                    and int(record['latest_timeupdated']) > int(record['timeupdated'])))


def directory_stamp(root, manifest=''):
    values = [str(root.stat().st_mtime_ns), manifest]
    descriptor = root / 'descriptor.mod'
    if descriptor.is_file() and not descriptor.is_symlink():
        stat = descriptor.stat()
        values.extend([str(stat.st_size), str(stat.st_mtime_ns)])
    return hashlib.sha256('\0'.join(values).encode()).hexdigest()


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
        if self.path in ('/assets/app-icon.svg', '/favicon.ico'):
            name = 'assets/app-icon.ico' if self.path == '/favicon.ico' else 'assets/app-icon.svg'
            return self.send(200, (ROOT / name).read_bytes(), 'image/x-icon' if self.path == '/favicon.ico' else 'image/svg+xml')
        if self.path in ('/vendor/gsap.min.js', '/vendor/ScrollTrigger.min.js'):
            return self.send(200, (ROOT / self.path.lstrip('/')).read_bytes(), 'text/javascript; charset=utf-8')
        if self.path == '/entry_browser_ui.js':
            return self.send(200, (ROOT / 'entry_browser_ui.js').read_bytes(), 'text/javascript; charset=utf-8')
        if not self.authorized():
            return self.send(403, {'error': '访问令牌无效'})
        if self.path == '/api/state':
            service = self.server.service
            return self.send(200, {'config': service.public_config(), 'profiles': service.profiles(), 'mods': list(service.inventory.values()),
                                   'history': service.history(), 'job': service.status(), 'data_dir': str(service.data_dir), 'config_storage': service.config_storage(), 'demo': service.demo,
                                   'app_version': APP_VERSION, 'program_dir': str(program_directory()),
                                   'aggregate_directory':str(service.data_dir / 'aggregate_mods')})
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
            if self.path == '/api/entries':
                item = service.get_mod(body['id'])
                result = service.cache.browser.list(item['id'], body.get('status', 'all'), body.get('query', ''),
                                                    body.get('page', 1), body.get('page_size', 50))
                return self.send(200, {**result, 'scan_state': item.get('scan_state', '未扫描'),
                                       'busy': service.status()['running']})
            if self.path == '/api/entry-status':
                with service.lock:
                    if service.job['running']:
                        raise ValueError('请等待任务结束后标注条目')
                    service.get_mod(body['id'])
                    return self.send(200, service.cache.browser.mark(body['id'], body['entry_id'], body['status']))
            if self.path == '/api/entry-edit':
                identifier, entry_id, replacement = body['id'], body['entry_id'], body['text']
                service.get_mod(identifier)
                service.cache.browser.get(identifier, entry_id)
                service.start('edit-entry', lambda: service.edit_entry(identifier, entry_id, replacement))
                return self.send(202, {'ok': True})
            if self.path == '/api/profile':
                return self.send(200, service.switch_profile(body['name']))
            if self.path == '/api/aggregate-config':
                with service.lock:
                    if service.job['running']:
                        raise ValueError('请等待任务结束后切换聚合汉化开关')
                    result = service.save_config({'aggregate_export':body['enabled']})
                return self.send(200, result)
            if self.path == '/api/open-aggregate':
                folder = service.data_dir / 'aggregate_mods'
                folder.mkdir(parents=True, exist_ok=True)
                open_folder(folder)
                return self.send(200, {'ok':True})
            if self.path == '/api/config-storage':
                return self.send(200, service.switch_config_storage(body['mode']))
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
            elif self.path == '/api/analyze':
                identifier = body['id']
                service.get_mod(identifier)
                service.start('analyze', lambda: service.analyze(identifier))
            elif self.path == '/api/import':
                identifier, chosen, provider = body['id'], body['path'], body.get('provider', '')
                service.get_mod(identifier)
                service.start('import', lambda: service.import_cache(identifier, chosen, provider))
            elif self.path == '/api/export':
                item = service.get_mod(body['id'])
                return self.send(200, service.cache.export(item))
            elif self.path == '/api/submit':
                return self.send(501, {'error': 'Steam 创意工坊投稿接口尚未启用'})
            elif self.path == '/api/pick':
                if service.status()['running']:
                    raise ValueError('请等待任务结束后选择文件')
                return self.send(200, {'path': pick_import_path(body.get('kind', 'file'))})
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


def pick_import_path(kind):
    import subprocess
    if kind not in ('file', 'folder'):
        raise ValueError('选择类型错误')
    command = [sys.executable, '--choose-import', kind] if getattr(sys, 'frozen', False) else [sys.executable, str(ROOT / 'workshop_app.py'), '--choose-import', kind]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=180,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
    if result.returncode:
        raise ValueError('无法打开系统选择框，请使用路径输入导入')
    return result.stdout.strip()


def choose_import(kind):
    import tkinter as tk
    from tkinter import filedialog
    window = tk.Tk()
    window.withdraw()
    try:
        chosen = (filedialog.askdirectory(title='选择中文文件夹或缓存目录', parent=window)
                  if kind == 'folder' else filedialog.askopenfilename(title='选择中文 YML 或缓存 JSON', parent=window,
                    filetypes=[('Translation files', '*.yml *.json'), ('All files', '*.*')]))
        print(chosen or '', flush=True)
    finally:
        window.destroy()


def self_test():
    # Run on the actual packaged executable, without Steam, credentials or network.
    import request
    request.load_sdk()
    request.findrule('hoi4')
    page = (ROOT / 'workshop_ui.html').read_text(encoding='utf-8')
    assert '__APP_TOKEN__' in page
    for name in ('gsap.min.js', 'ScrollTrigger.min.js'):
        assert (ROOT / 'vendor' / name).is_file()
    with tempfile.TemporaryDirectory() as directory:
        service = WorkshopService(Path(directory), demo=True)
        item = service.scan()[0]
        assert item['discovery_source'] == 'Steam ACF' and item['workshop']['manifest'] == '1'
        result = service.translate(item['id'])
        output = Path(item['path']) / 'localisation/simp_chinese/demo_l_simp_chinese.yml'
        assert '新的开始' in output.read_text(encoding='utf-8-sig')
        output.unlink()
        service.restore(result['version_id'], item['id'])
        assert output.is_file() and len(service.history()) == 1
        counts = service.analyze(item['id'])
        assert counts['translated'] == 2 and counts['untranslated'] == 0
        exported = service.cache.export(item)
        cache_path = Path(directory) / 'export.cache.json'
        cache_path.write_text(json.dumps(exported), encoding='utf-8')
        service.import_cache(item['id'], cache_path)
        assert service.config()['api_key'] == ''
        service.scan()
        service.analyze(item['id'])
        restarted = WorkshopService(Path(directory), demo=True)
        assert restarted.inventory[item['id']]['counts']['translated'] == 2
        restarted.scan(lambda ids: (_ for _ in ()).throw(AssertionError('unchanged metadata query')))
        assert restarted.inventory[item['id']]['scan_state'] == '已扫描'
        assert (ROOT / 'assets/app-icon.ico').is_file()
        assert service.history()[0]['provider']
        assert service.completed_path.is_file()
        assert service.providers_path.is_file()
        browser = service.cache.browser
        page = browser.list(item['id'])
        assert page['ready'] and len(page['entries']) == 2
        assert page['counts']['translated'] == 2
        entry_id = page['entries'][0]['entry_id']
        browser.mark(item['id'], entry_id, 'untranslated')
        assert browser.list(item['id'], 'untranslated')['total'] == 1
        browser.mark(item['id'], entry_id, None)
        assert (ROOT / 'entry_browser_ui.js').is_file()
    print('WORKSHOP_TRANSLATOR_SELF_TEST_OK', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Workshop 翻译程序 · Windows / macOS')
    parser.add_argument('--choose-import', choices=['file', 'folder'], help=argparse.SUPPRESS)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--demo', action='store_true', help='模拟 Mod 与模型回复，不调用 Steam 或付费接口')
    parser.add_argument('--startup-check', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--self-test', action='store_true', help='离线检查打包资源、翻译、数据库和文件恢复')
    args = parser.parse_args()
    if args.choose_import:
        choose_import(args.choose_import)
        return
    if args.self_test:
        self_test()
        return
    service = WorkshopService(args.data_dir, demo=args.demo)
    if args.startup_check:
        print(json.dumps({'python_ready_seconds': round(time.perf_counter()-_STARTUP_STARTED, 4), 'sdk_loaded': 'openai' in sys.modules}), flush=True)
        return
    server = AppServer(('127.0.0.1', args.port), service)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Workshop 翻译程序：{url}\n版本：{APP_VERSION}\n程序目录：{program_directory()}\n数据目录：{service.data_dir}\n按 Ctrl+C 停止', flush=True)
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
