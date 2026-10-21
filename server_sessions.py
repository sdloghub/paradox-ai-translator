"""Anonymous browser workspaces and explicit public translation contributions."""
from http.cookies import SimpleCookie, CookieError
import ipaddress
import json
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
from urllib.parse import urlsplit


def forget_saved_keys(service):
    from workshop_app import atomic_bytes
    def clean(value):
        if isinstance(value, dict):
            return {key: '' if key == 'api_key' else clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    for path in (service.config_path, service.providers_path):
        if path.is_file():
            old = json.loads(path.read_text())
            new = clean(old)
            if old != new:
                atomic_bytes(path, json.dumps(new, ensure_ascii=False, indent=2).encode(), private=True)


def workspace(handler):
    root = handler.server.service
    if not getattr(root, 'server_mode', False) or handler.is_dev_logged_in():
        return root
    if hasattr(handler, '_visitor_service'):
        return handler._visitor_service
    try:
        value = SimpleCookie(handler.headers.get('Cookie', '')).get('workshop_visitor')
        token = value.value if value else ''
    except CookieError:
        token = ''
    server = handler.server
    with server.visitor_lock:
        # Inactive workspaces expire after a day. Active tasks are never removed.
        for key, (service, seen) in list(server.visitors.items()):
            if time.time() - seen > 86400 and not service.busy() and not any(s.busy() for s in getattr(service, 'language_workspaces', {}).values()):
                shutil.rmtree(service.data_dir)
                del server.visitors[key]
        if token not in server.visitors:
            if len(server.visitors) >= 64:
                raise ValueError('当前访客较多，请稍后重试')
            from workshop_app import WorkshopService
            token = secrets.token_hex(32)
            directory = root.data_dir / 'visitors' / token
            service = WorkshopService(directory, program_dir=directory / 'defaults')
            service.server_mode = True
            service.server_root = root
            service.visitor_id = token
            service.documents_dir = directory / 'Documents'
            server.visitors[token] = service, time.time()
            secure = '; Secure' if handler.headers.get('X-Forwarded-Proto') == 'https' else ''
            handler._visitor_cookie = f'workshop_visitor={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400{secure}'
        service = server.visitors[token][0]
        server.visitors[token] = service, time.time()
        handler._visitor_service = service
        return service


def transient_config(service, body):
    """Never pass a visitor key through save_config or a profile registry."""
    if not isinstance(body, dict) or not isinstance(body.get('base_url', ''), str):
        raise ValueError('API 配置格式无效')
    cfg = service.config()
    cfg.update({k: body.get(k, cfg[k]) for k in ('base_url', 'model', 'batch_size', 'concurrency')})
    cfg['api_key'] = body.get('api_key', '')
    if not isinstance(cfg['api_key'], str) or len(cfg['api_key']) > 4096:
        raise ValueError('API Key 格式无效')
    if not isinstance(cfg['model'], str) or not 0 < len(cfg['model'].strip()) <= 120:
        raise ValueError('请填写有效的模型名称')
    url = urlsplit(cfg['base_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment or url.query:
        raise ValueError('网页版 API 地址需为不含账号或查询参数的 HTTPS 地址')
    try:
        addresses = socket.getaddrinfo(url.hostname, url.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('API 地址必须指向公网服务')
    except socket.gaierror as error:
        raise ValueError('无法解析 API 地址') from error
    for key, maximum in [('batch_size', 50), ('concurrency', 10)]:
        if type(cfg[key]) is not int or not 1 <= cfg[key] <= maximum:
            raise ValueError(f'{key} 超出有效范围')
    cfg.update(provider=cfg['model'], developer_mode=False, aggregate_export=False)
    return cfg


def public_database(service):
    root = getattr(service, 'server_root', service)
    language = getattr(service, 'target_language', 'zh-CN')
    filename = 'shared-translations.sqlite3' if language == 'zh-CN' else f'shared-translations-{language}.sqlite3'
    db = sqlite3.connect(root.data_dir / filename, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS contributions (
        id INTEGER PRIMARY KEY, mod_id TEXT NOT NULL, title TEXT NOT NULL,
        author TEXT NOT NULL, model TEXT NOT NULL, publish_allowed INTEGER NOT NULL,
        created_at TEXT NOT NULL, owner TEXT NOT NULL, version_id INTEGER NOT NULL,
        package BLOB NOT NULL, UNIQUE(owner,mod_id,version_id))''')
    return db


def contributions(service, identifier=None):
    db = public_database(service)
    try:
        sql = 'SELECT id,mod_id,title,author,model,publish_allowed,created_at FROM contributions'
        args = ()
        if identifier:
            sql += ' WHERE mod_id=?'
            args = (identifier,)
        return [dict(row) for row in db.execute(sql + ' ORDER BY id DESC', args)]
    finally:
        db.close()


def share(service, body):
    from workshop_app import now
    identifier = body['id']
    job = service.jobs.get(identifier, {})
    result = job.get('result') or {}
    if job.get('running') or job.get('kind') != 'translate' or job.get('error') or not result.get('version_id'):
        raise ValueError('请先完成此 Mod 的翻译，再自愿共享')
    author = body.get('author', '')
    allowed = body.get('publish_allowed', False)
    if not isinstance(author, str) or len(author) > 80 or type(allowed) is not bool:
        raise ValueError('署名最多 80 字，发布许可需为勾选或不勾选')
    with service.operation('share-translation', identifier):
        package = service.export_package(identifier)
        db = public_database(service)
        try:
            with db:
                db.execute('''INSERT INTO contributions
                    (mod_id,title,author,model,publish_allowed,created_at,owner,version_id,package)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (identifier, service.get_mod(identifier)['title'], author.strip() or '匿名',
                     result.get('model', '未知模型'), int(allowed), now(),
                     getattr(service, 'visitor_id', 'developer'), result['version_id'], package))
        except sqlite3.IntegrityError as error:
            raise ValueError('此翻译版本已共享，请勿重复提交') from error
        finally:
            db.close()
    return {'ok': True}


def use_shared(service, body):
    identifier = body['id']
    db = public_database(service)
    try:
        row = db.execute('SELECT * FROM contributions WHERE id=? AND mod_id=?',
                         (int(body['share_id']), identifier)).fetchone()
    finally:
        db.close()
    if not row:
        raise ValueError('未找到此 Mod 的共享翻译')
    with service.operation('use-shared', identifier), tempfile.TemporaryDirectory(dir=service.data_dir) as temp:
        path = Path(temp) / 'shared.zip'
        path.write_bytes(row['package'])
        result = service.import_cache(identifier, str(path), f'{row["author"]} · {row["model"]}'[:120])
        item = service.get_mod(identifier)
        credits = item.setdefault('shared_credits', [])
        credit = {'author': row['author'], 'model': row['model'], 'publish_allowed': bool(row['publish_allowed'])}
        if credit not in credits:
            credits.append(credit)
        service.persist_item(item)
    return {**result, 'author': row['author'], 'model': row['model']}
