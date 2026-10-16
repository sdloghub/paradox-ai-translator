"""Collect deployed localisation files into one publishable content tree per game."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import time


def export(service, item, files, version_id):
    from workshop_app import atomic_bytes, now
    if not service.config()['aggregate_export']:
        return {'enabled': False}
    if not all(re.fullmatch(r'[0-9]+', str(item[key])) for key in ('appid', 'uid')):
        raise ValueError('聚合导出的游戏或 Mod UID 无效')
    base = service.data_dir / 'aggregate_mods'
    root = base / item['appid']

    def safe_path(relative):
        relative = PurePosixPath(relative)
        if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):
            raise ValueError('聚合文件路径无效')
        destination = root.joinpath(*relative.parts)
        if not destination.resolve().is_relative_to(root.resolve()):
            raise ValueError('聚合文件超出输出目录')
        for path in (destination, *destination.parents):
            if path == service.data_dir:
                break
            if path.is_symlink():
                raise ValueError('聚合目录包含符号链接')
        return destination

    manifest_path = safe_path('translation-manifest.json')
    manifest = {'format':'workshop-aggregate-v1', 'appid':item['appid'],
                'game':item['game'], 'game_title':item['game_title'], 'mods':{}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or manifest.get('format') != 'workshop-aggregate-v1' or manifest.get('appid') != item['appid'] or not isinstance(manifest.get('mods'), dict):
            raise ValueError('聚合来源清单无效，请保留原文件并检查 translation-manifest.json')
    writes, records = {}, []
    for name, content in sorted(files.items()):
        path = PurePosixPath(name)
        if not path.parts or path.parts[0] not in ('localisation', 'localization') or path.suffix.lower() != '.yml':
            raise ValueError('聚合仅接收本地化 YML 文件')
        relative = (path.parent / (item['uid'] + '_' + path.name)).as_posix()
        destination = safe_path(relative)
        writes[destination] = content
        records.append({'source_file':name, 'file':relative, 'sha256':hashlib.sha256(content).hexdigest()})
    stale, warnings = [], []
    current_names = {record['file'] for record in records}
    previous_mod = manifest['mods'].get(item['uid'], {})
    if not isinstance(previous_mod, dict) or not isinstance(previous_mod.get('files', []), list):
        raise ValueError('聚合来源清单的 Mod 记录无效')
    for previous in previous_mod.get('files', []):
        name = previous['file']
        if name in current_names:
            continue
        path = safe_path(name)
        if not path.name.startswith(item['uid'] + '_'):
            raise ValueError('聚合来源清单含有其他 Mod 的文件')
        if path.is_file():
            if hashlib.sha256(path.read_bytes()).hexdigest() == previous['sha256']:
                stale.append(path)
            else:
                warnings.append('保留已被手动修改的旧聚合文件：' + name)
    manifest['mods'][item['uid']] = {
        'uid':item['uid'], 'name':item['title'], 'workshop_url':item['url'],
        'version_id':int(version_id), 'updated_at':now(), 'files':records,
        'origins':item.get('counts', {}).get('origins', []),
        'format_errors':item.get('counts', {}).get('parse_errors', 0),
        'untranslated':item.get('counts', {}).get('untranslated', 0)}
    writes[manifest_path] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    previous_files = {}
    for path in [*writes, *stale]:
        if path.exists() and not path.is_file():
            raise ValueError('聚合文件被同名目录占用')
        previous_files[path] = path.read_bytes() if path.exists() else None
    changed = [path for path, content in writes.items() if previous_files[path] != content]
    backup_root = service.data_dir / 'aggregate_backups' / (str(time.time_ns()) + '-' + secrets.token_hex(4)) / item['appid']
    for path in [*changed, *stale]:
        if previous_files[path] is not None:
            atomic_bytes(backup_root / path.relative_to(root), previous_files[path], private=True)
    touched = []
    try:
        for path in changed:
            # Recheck for links immediately before each generated-file write.
            safe_path(path.relative_to(root).as_posix())
            touched.append(path)
            atomic_bytes(path, writes[path])
        for path in stale:
            safe_path(path.relative_to(root).as_posix())
            touched.append(path)
            path.unlink()
    except Exception:
        for path in reversed(touched):
            content = previous_files[path]
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_bytes(path, content)
        raise
    return {'enabled':True, 'path':str(root), 'files':len(records), 'warnings':warnings}
