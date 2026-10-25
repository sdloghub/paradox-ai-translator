"""Versioned source/translation mappings shared by scan, import and translation."""
import hashlib
import io
import zipfile
import json
from pathlib import Path
import re

import paradox
import request

FORMAT = 'workshop-translator-cache-v1'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def entries(files, game, strict=True, issues=None):
    result = []
    for filename, data in files.items():
        for number, line in enumerate(data.decode('utf-8-sig').splitlines(keepends=True), 1):
            try:
                match = paradox.checked_line(line, filename, number) if strict else paradox.parse_line(line)
            except paradox.LocalisationError:
                if issues is None:
                    raise
                issues.append({'file': filename, 'line': number, 'original_line': line.rstrip('\r\n'), 'reason': '无法解析；翻译时保留英文原行'})
                continue
            if match:
                result.append({'source_file': filename, 'key': match['prefix'].lstrip(),
                               'text': paradox.source_text(match, game), 'line': number,
                               'original_line': line.rstrip('\r\n')})
    return result


def canonical_key(key):
    return key.split(':', 1)[0].strip()


def duplicate_issues(rows):
    """Only repeated keys with conflicting English are errors."""
    groups = {}
    for row in rows:
        groups.setdefault(canonical_key(row['key']), []).append(row)
    result = []
    for key, group in groups.items():
        if len({row['text'] for row in group}) < 2:
            continue
        locations = '、'.join(f"{row['source_file']} 第 {row['line']} 行" for row in group)
        for row in group:
            result.append({'file': row['source_file'], 'line': row['line'], 'key': key,
                           'english': row['text'], 'original_line': row['original_line'],
                           'reason': f'重复键值「{key}」；出现位置：{locations}。请修改键值后重新扫描。'})
    return result


def aligned_texts(originals, translations):
    """Pair repeated keys by occurrence, never let the last occurrence replace all."""
    source_groups, target_groups = {}, {}
    for entry in originals:
        source_groups.setdefault(canonical_key(entry['key']), []).append(entry)
    for entry in translations:
        target_groups.setdefault(canonical_key(entry['key']), []).append(entry)
    result = {}
    for key, group in source_groups.items():
        targets = target_groups.get(key, [])
        if len(group) == len(targets):
            for source, target in zip(group, targets):
                result[source['line']] = target['text']
    return result


def comparable_file(name):
    parts = Path(name).as_posix().split('/')
    while parts and parts[0] not in ('localisation', 'localization'):
        parts.pop(0)
    if parts:
        parts.pop(0)
    from localization import LANGUAGES
    slots = {item['slot'] for item in LANGUAGES.values()}
    parts = [part for part in parts if part not in {'english', 'replace', *slots}]
    result = '/'.join(parts)
    for slot in slots:
        result = result.replace('l_' + slot, 'l_english')
    return result


def _parse_json_candidates(raw_text):
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError('缓存 JSON 必须是对象')
    if payload.get('format') == FORMAT:
        return [{**entry, 'target_language': payload.get('target_language', 'zh-CN'), 'mod_id': payload.get('mod_id')} for entry in payload.get('entries', []) if isinstance(entry, dict)]
    result = []
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(value.get('source_hash'), str):
            result.append({'key': value.get('key', key.split('\x1f', 1)[0]), 'text': value.get('text'), 'source_hash': value['source_hash']})
    return result


def _parse_yml_candidates(filename, data, game):
    text = data.decode('utf-8-sig')
    from localization import current_language, slot
    language = current_language()
    target_header = slot()
    headers = re.findall(r'^\s*l_([A-Za-z_]+)\s*:', text, re.M)
    if headers and target_header not in headers and game != 'eu4':
        return []
    chinese_header = bool(re.search(r'^\s*l_' + target_header + r'\s*:', text, re.M))
    result = []
    for entry in entries({str(filename): data}, game, strict=False):
        if not entry['text'].strip():
            continue
        if re.search(request.target_pattern(language), entry['text']) or (chinese_header and request.is_token_only(entry['text'])):
            if chinese_header or game == 'eu4' or not re.search(r'[A-Za-z]{2,}', request.TOKENS.sub('', entry['text'])):
                result.append({**entry, 'target_language': language})
    return result


def candidates(path, game):
    path = Path(path).expanduser().resolve()
    paths = sorted(list(path.rglob('*.yml')) + list(path.rglob('*.yaml')) + list(path.rglob('*.cache.json')) + list(path.rglob('*.zip'))) if path.is_dir() else [path]
    json_entries = []
    yml_entries = []
    for file in paths:
        if file.is_symlink() or not file.is_file():
            continue
        if path.is_dir() and not file.resolve().is_relative_to(path):
            continue
        suffix = file.suffix.lower()
        if suffix == '.json':
            json_entries.extend(_parse_json_candidates(file.read_text(encoding='utf-8-sig')))
        elif suffix in ('.yml', '.yaml'):
            yml_entries.extend(_parse_yml_candidates(file, file.read_bytes(), game))
        elif suffix == '.zip':
            from workshop_app import unarchive
            blob = file.read_bytes()
            try:
                with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                    infos = archive.infolist()
                    if len(infos) > 5000 or sum(info.file_size for info in infos) > 128 * 1024 * 1024:
                        raise ValueError('译文 ZIP 解压后不得超过 128 MB 或 5000 个条目')
                members = unarchive(blob)
            except zipfile.BadZipFile as error:
                raise ValueError('请上传有效的译文 ZIP 压缩包') from error
            for name, content in sorted(members.items()):
                lower = name.lower()
                if lower.endswith('.json'):
                    json_entries.extend(_parse_json_candidates(content.decode('utf-8-sig')))
                elif lower.endswith(('.yml', '.yaml')):
                    yml_entries.extend(_parse_yml_candidates(name, content, game))
    if json_entries and yml_entries:
        hash_by_file_key = {}
        hash_by_key = {}
        for item in json_entries:
            sh = item.get('source_hash')
            if isinstance(sh, str):
                ck = canonical_key(str(item.get('key', '')))
                if item.get('source_file'):
                    hash_by_file_key[(comparable_file(item['source_file']), ck)] = (sh, item.get('mod_id'), item.get('target_language', 'zh-CN'))
                hash_by_key.setdefault(ck, set()).add((sh, item.get('mod_id'), item.get('target_language', 'zh-CN')))
        for item in yml_entries:
            if not item.get('source_hash'):
                ck = canonical_key(str(item.get('key', '')))
                cf = comparable_file(item.get('source_file', ''))
                match = hash_by_file_key.get((cf, ck))
                if not match and len(hash_by_key.get(ck, ())) == 1:
                    match = next(iter(hash_by_key[ck]))
                if match:
                    item['source_hash'] = match[0]
                    item['target_language'] = match[2]
                    if match[1] and not item.get('mod_id'):
                        item['mod_id'] = match[1]
    return json_entries + yml_entries


class ModCache:
    def __init__(self, service):
        self.service = service
        from entry_browser import EntryBrowser
        self.browser = EntryBrowser(service)
        with service.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS translation_entries (
                mod_id TEXT NOT NULL, source_file TEXT NOT NULL, entry_key TEXT NOT NULL,
                source_hash TEXT NOT NULL, chinese TEXT NOT NULL, chinese_hash TEXT NOT NULL,
                origin TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(mod_id,source_file,entry_key,source_hash))''')
            db.execute('CREATE INDEX IF NOT EXISTS cache_chinese ON translation_entries(mod_id,chinese_hash)')
            db.execute('''CREATE TABLE IF NOT EXISTS cache_scan_snapshots (
                mod_id TEXT PRIMARY KEY, sources BLOB NOT NULL, local_entries TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS mod_cache_preferences (
                mod_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, version_id INTEGER)''')

    def selection(self, identifier):
        with self.service.connect() as db:
            row = db.execute('SELECT enabled,version_id FROM mod_cache_preferences WHERE mod_id=?', (identifier,)).fetchone()
            versions = [{'id': v, 'created_at': date, 'provider': provider} for v, date, provider in db.execute(
                'SELECT id,created_at,provider FROM versions WHERE mod_id=? ORDER BY id DESC', (identifier,))]
            count = db.execute('SELECT COUNT(*) FROM translation_entries WHERE mod_id=?', (identifier,)).fetchone()[0]
        return {'enabled': bool(row[0]) if row else True, 'version_id': row[1] if row else None,
                'versions': versions, 'entries': count}

    def select(self, identifier, enabled, version_id=None):
        if type(enabled) is not bool or (version_id is not None and type(version_id) is not int):
            raise ValueError('缓存选项无效')
        with self.service.connect() as db:
            if version_id is not None and not db.execute('SELECT 1 FROM versions WHERE id=? AND mod_id=?', (version_id, identifier)).fetchone():
                raise ValueError('缓存版本不存在或不属于此 Mod')
            db.execute('INSERT OR REPLACE INTO mod_cache_preferences VALUES (?,?,?)', (identifier, int(enabled), version_id))

    def active_rows(self, item, local_entries=None, sources=None):
        """Resolve selected cache without modifying the stored latest translations."""
        choice = self.selection(item['id'])
        with self.service.connect() as db:
            stored = db.execute('SELECT source_file,entry_key,source_hash,chinese,origin FROM translation_entries WHERE mod_id=? ORDER BY updated_at,rowid', (item['id'],)).fetchall()
            version = db.execute('SELECT originals,chinese,provider FROM versions WHERE id=? AND mod_id=?', (choice['version_id'], item['id'])).fetchone() if choice['enabled'] and choice['version_id'] is not None else None
        stored = [(f,k,h,request.output_text(text),origin) for f,k,h,text,origin in stored]
        rows = list(stored) if choice['enabled'] and choice['version_id'] is None else []
        if version:
            from workshop_app import unarchive, target_path
            originals, chinese = unarchive(version[0]), unarchive(version[1])
            for name, data in originals.items():
                target = chinese.get(target_path(name, item['game']))
                if not target:
                    continue
                original = entries({name:data}, item['game'], strict=False)
                translated = aligned_texts(original, entries({name:target}, item['game'], strict=False))
                for entry in original:
                    text = translated.get(entry['line'])
                    if request.valid_translation(entry['text'], text) and (text != entry['text'] or request.is_token_only(entry['text'])):
                        rows.append((name, entry['key'], digest(entry['text']), text, version[2] or '历史备份'))
        # Cache opt-out must never hide valid Chinese already deployed in the Mod.
        if local_entries:
            known = {}
            stored_origins = {(f,k,h,text): origin for f,k,h,text,origin in stored}
            for f,k,h,text,origin in stored:
                known.setdefault((f, canonical_key(k), text), set()).add(h)
            present = {(f,k,h) for f,k,h,text,origin in rows}
            for entry in entries(sources if sources is not None else self.service.original_sources(item), item['game'], strict=False):
                name, key, h = entry['source_file'], entry['key'], digest(entry['text'])
                text = local_entries.get(name, {}).get(entry['line'])
                if (request.valid_translation(entry['text'], text)
                        and request.valid_translation(entry['text'], text)
                        and h in known.get((name, canonical_key(key), text), set() if self.service.target_language == 'zh-TW' else {h})):
                    if (name,key,h) not in present:
                        rows.append((name,key,h,text,stored_origins.get((name,key,h,text), '本机中文')))
                        present.add((name,key,h))
        return rows

    def delete_version(self, identifier, version_id):
        from workshop_app import unarchive, target_path, GAMES
        # Resolve game using SQL metadata; deleting an uninstalled Mod's version is allowed.
        with self.service.connect() as db:
            mod = db.execute('SELECT appid FROM mods WHERE id=?', (identifier,)).fetchone()
            version = db.execute('SELECT originals,chinese FROM versions WHERE mod_id=? AND id=?', (identifier,version_id)).fetchone()
            if not mod or not version:
                raise ValueError('缓存版本不存在或不属于此 Mod')
            game = GAMES[mod[0]][0]
            def mappings(blobs):
                originals, chinese = map(unarchive, blobs)
                result = set()
                for name,data in originals.items():
                    output = chinese.get(target_path(name,game))
                    if output is None:
                        continue
                    original = entries({name:data},game,strict=False)
                    texts = aligned_texts(original, entries({name:output},game,strict=False))
                    for entry in original:
                        text = texts.get(entry['line'])
                        if request.valid_translation(entry['text'],text) and (text != entry['text'] or request.is_token_only(entry['text'])):
                            result.add((name,entry['key'],digest(entry['text']),text))
                return result
            deleted = mappings(version)
            shared = set()
            remaining = {}
            for original,chinese,origin in db.execute('SELECT originals,chinese,provider FROM versions WHERE mod_id=? AND id<>? ORDER BY id', (identifier,version_id)):
                for name,key,h,text in mappings((original,chinese)):
                    shared.add((name,key,h,text))
                    remaining[(name,key,h)] = (text,origin or '历史备份')
            # Keep deployment recovery independent of user-visible cache versions (EU4 overwrites English).
            if game == 'eu4':
                db.execute('''INSERT OR IGNORE INTO deployment_recovery
                    SELECT d.id,v.mod_id,v.originals,v.chinese FROM deployments d JOIN versions v ON v.id=d.version_id
                    WHERE v.mod_id=? AND v.id=?''', (identifier,version_id))
            else:
                db.execute('DELETE FROM deployments WHERE version_id=?', (version_id,))
            removed = 0
            for name,key,source_hash,text in deleted - shared:
                removed += db.execute('''DELETE FROM translation_entries WHERE mod_id=? AND source_file=?
                    AND entry_key=? AND source_hash=? AND chinese=?''', (identifier,name,key,source_hash,text)).rowcount
            for (name,key,h),(text,origin) in remaining.items():
                db.execute('''INSERT OR IGNORE INTO translation_entries
                    (mod_id,source_file,entry_key,source_hash,chinese,chinese_hash,origin) VALUES (?,?,?,?,?,?,?)''',
                    (identifier,name,key,h,text,digest(text),origin))
            db.execute('INSERT INTO deleted_cache_versions VALUES (?,?)', (version_id,identifier))
            db.execute('DELETE FROM versions WHERE mod_id=? AND id=?', (identifier,version_id))
            db.execute('UPDATE mod_cache_preferences SET version_id=NULL WHERE mod_id=? AND version_id=?', (identifier,version_id))
            db.execute("DELETE FROM entry_reviews WHERE mod_id=? AND status IN ('cached','needs_update')", (identifier,))
        return removed

    def put(self, db, identifier, entry, text, origin):
        text = request.output_text(text)
        db.execute('''INSERT OR REPLACE INTO translation_entries
            (mod_id,source_file,entry_key,source_hash,chinese,chinese_hash,origin)
            VALUES (?,?,?,?,?,?,?)''', (identifier, entry['source_file'], entry['key'], digest(entry['text']), text, digest(text), origin))

    def import_candidates(self, item, sources, translations, origin):
        source_entries = [entry for entry in entries(sources, item['game'], strict=False) if entry['text'].strip()]
        imported = rejected = accepted = 0
        source_counts = {}
        for entry in source_entries:
            key = canonical_key(entry['key'])
            source_counts[key] = source_counts.get(key, 0) + 1
        by_key = {}
        from localization import current_language
        for translated in translations:
            if translated.get('target_language', 'zh-CN') != current_language():
                continue
            by_key.setdefault(canonical_key(str(translated.get('key', ''))), []).append(translated)
        with self.service.connect() as db:
            for entry in source_entries:
                options = by_key.get(canonical_key(entry['key']), [])
                exact = [candidate for candidate in options if candidate.get('source_file') and comparable_file(candidate['source_file']) == comparable_file(entry['source_file'])]
                if exact:
                    options = exact
                elif source_counts[canonical_key(entry['key'])] > 1:
                    options = []
                valid = []
                for candidate in options:
                    if candidate.get('mod_id') and candidate['mod_id'] != item['id']:
                        rejected += 1
                        continue
                    text = candidate.get('text')
                    if not request.valid_translation(entry['text'], text):
                        rejected += 1
                        continue
                    if candidate.get('source_hash') and candidate['source_hash'] != digest(entry['text']):
                        rejected += 1
                        continue
                    # Never re-label unchanged old Chinese as a translation of changed English.
                    historical = db.execute('''SELECT source_hash,entry_key FROM translation_entries
                        WHERE mod_id=? AND source_file=? AND chinese_hash=?''',
                        (item['id'], entry['source_file'], digest(text))).fetchall()
                    historical = [row for row in historical if canonical_key(row[1]) == canonical_key(entry['key'])]
                    if not candidate.get('source_hash') and historical and all(row[0] != digest(entry['text']) for row in historical):
                        rejected += 1
                        continue
                    valid.append(text)
                if len(set(valid)) == 1:
                    accepted += 1
                    # Preserve existing validated translation for this exact source version.
                    existing = db.execute('''SELECT chinese FROM translation_entries WHERE
                        mod_id=? AND source_file=? AND entry_key=? AND source_hash=?''',
                        (item['id'], entry['source_file'], entry['key'], digest(entry['text']))).fetchone()
                    if not existing or not request.valid_translation(entry['text'], existing[0]):
                        self.put(db, item['id'], entry, valid[0], origin)
                        imported += 1
                elif valid:
                    rejected += 1
        return {'imported': imported, 'rejected': rejected, 'accepted': accepted}

    def sync_workspace(self, item, sources, origin='翻译缓存', collect=True):
        workspace = self.service.data_dir / 'workspaces' / item['appid'] / item['uid']
        selected_rows = self.active_rows(item)
        with self.service.connect() as db:
            cached_rows = {(f, k, h): t for f, k, h, t, origin_name in selected_rows}
            stored_rows = {(f,k,h):t for f,k,h,t in db.execute('SELECT source_file,entry_key,source_hash,chinese FROM translation_entries WHERE mod_id=?', (item['id'],))}
            for name in sources:
                path = workspace / 'already' / item['game'] / (name + '.cache.json')
                existing = {}
                if path.exists():
                    try:
                        existing = json.loads(path.read_text(encoding='utf-8'))
                    except (ValueError, OSError):
                        pass
                if not isinstance(existing, dict):
                    existing = {}
                before = json.dumps(existing, ensure_ascii=False, indent=2)
                old_cache = existing
                existing = {}
                for entry in entries({name: sources[name]}, item['game'], strict=False):
                    if not entry['text'].strip():
                        continue
                    h = digest(entry['text'])
                    text = cached_rows.get((name, entry['key'], h))
                    cached = paradox.cached_entry(old_cache, entry['key'], entry['text'])
                    if collect and isinstance(cached, dict) and cached.get('source_hash') == h and request.valid_translation(entry['text'], cached.get('text')):
                        text = cached['text']
                        if stored_rows.get((name, entry['key'], h)) != text:
                            self.put(db, item['id'], entry, text, origin)
                    if text is not None:
                        paradox.store_cached_entry(existing, entry['key'], entry['text'], text)
                    elif request.is_token_only(entry['text']):
                        paradox.store_cached_entry(existing, entry['key'], entry['text'], entry['text'])
                        self.put(db, item['id'], entry, entry['text'], '自动保留（纯标识符）')
                after = json.dumps(existing, ensure_ascii=False, indent=2)
                if not path.exists() or before != after:
                    paradox.atomic_write(path, after)
        return workspace

    def stats(self, item, sources, local_entries=None):
        issues = []
        current = entries(sources, item['game'], issues=issues)
        duplicates = duplicate_issues(current)
        issues.extend(duplicates)
        invalid = {(issue['file'], issue['line']) for issue in duplicates}
        current = [entry for entry in current if (entry['source_file'], entry['line']) not in invalid]
        # One logical entry per key and exact English, across source files.
        current = list({(canonical_key(e['key']), e['text']): e for e in reversed(current)}.values())
        skipped_blank = sum(not entry['text'].strip() for entry in current)
        current = [entry for entry in current if entry['text'].strip()]
        translated = needs_update = 0
        deployed = 0
        if local_entries is None:
            local_entries = {}
            from workshop_app import target_path, archive
            for filename in sources:
                path = Path(item['path']) / target_path(filename, item['game'])
                if path.is_file():
                    try:
                        local_entries[filename] = aligned_texts(entries({filename:sources[filename]}, item['game'], strict=False),
                            entries({filename:path.read_bytes()}, item['game'], strict=False))
                    except (UnicodeError, OSError):
                        pass
            with self.service.connect() as db:
                db.execute('INSERT OR REPLACE INTO cache_scan_snapshots VALUES (?,?,?)',
                           (item['id'], archive(sources), json.dumps(local_entries, ensure_ascii=False)))
        origins = {}
        browser_rows = []
        with self.service.connect() as db:
            history = {}
            cached_rows = {}
            latest = {}
            for filename, key, source_hash, chinese, origin in self.active_rows(item, local_entries, sources):
                history.setdefault((filename, canonical_key(key)), set()).add(source_hash)
                cached_rows[(filename, key, source_hash)] = (chinese, origin)
                latest[(filename, canonical_key(key))] = (chinese, origin)
            for entry in current:
                h = digest(entry['text'])
                row = cached_rows.get((entry['source_file'], entry['key'], h))
                if not row and request.is_token_only(entry['text']):
                    row = (entry['text'], '自动保留（纯标识符）')
                    cached_rows[(entry['source_file'], entry['key'], h)] = row
                status = 'untranslated'
                chinese, origin = '', ''
                historical = False
                if row and request.valid_translation(entry['text'], row[0]):
                    translated += 1
                    chinese, origin = row
                    status = 'cached'
                    if local_entries.get(entry['source_file'], {}).get(entry['line']) == row[0]:
                        deployed += 1
                        status = 'translated'
                    origins[row[1]] = origins.get(row[1], 0) + 1
                elif history.get((entry['source_file'], canonical_key(entry['key'])), set()) - {digest(entry['text'])}:
                    needs_update += 1
                    status = 'needs_update'
                    chinese, origin = latest[(entry['source_file'], canonical_key(entry['key']))]
                    historical = True
                browser_rows.append({'source_file': entry['source_file'], 'line': entry['line'],
                                     'key': canonical_key(entry['key']), 'english': entry['text'],
                                     'chinese': chinese, 'origin': origin, 'auto_status': status,
                                     'original_line': entry['original_line'], 'reason': '', 'historical': historical})
        for issue in issues:
            raw = issue['original_line']
            key = raw.split(':', 1)[0].strip()
            browser_rows.append({'source_file': issue['file'], 'line': issue['line'], 'key': key,
                                 'english': issue.get('english', raw), 'chinese': '', 'origin': '', 'auto_status': 'format_error',
                                 'original_line': raw, 'reason': issue['reason'], 'historical': False})
        browser_rows.sort(key=lambda row: (row['source_file'], row['line']))
        revision = self.browser.replace(item['id'], browser_rows)
        effective = self.browser.list(item['id'], page_size=1)['counts']
        deployed = effective['translated']
        cached = effective['cached']
        translated = deployed + cached
        needs_update = effective['needs_update']
        untranslated = effective['untranslated'] + needs_update
        parse_errors = effective['format_error']
        return {'total': len(current) + len(issues), 'skipped_blank': skipped_blank, 'translated': translated, 'deployed': deployed, 'cached': cached, 'parse_errors': parse_errors, 'issues': issues, 'untranslated': untranslated, 'files': len(sources), 'needs_update': needs_update, 'entry_revision': revision, 'origins': [{'name': name, 'count': count} for name, count in sorted(origins.items())]}

    def refresh_selection(self, item):
        """Re-evaluate just this Mod using its last SQL scan, without filesystem I/O."""
        from workshop_app import unarchive
        with self.service.connect() as db:
            row = db.execute('SELECT sources,local_entries FROM cache_scan_snapshots WHERE mod_id=?',
                             (item['id'],)).fetchone()
        if row is None:
            return None
        local = {name: {int(line): text for line, text in lines.items()}
                 for name, lines in json.loads(row[1]).items()}
        return self.stats(item, unarchive(row[0]), local_entries=local)

    def export(self, item):
        with self.service.connect() as db:
            rows = db.execute('''SELECT source_file,entry_key,source_hash,chinese,origin FROM translation_entries WHERE mod_id=?''', (item['id'],)).fetchall()
        return {'format': FORMAT, 'target_language': self.service.target_language, 'mod_id': item['id'], 'title': item['title'],
                'entries': [{'source_file': f, 'key': k, 'source_hash': h, 'text': t, 'origin': o} for f, k, h, t, o in rows]}

    def export_package(self, item):
        from workshop_app import archive, target_path
        sources = self.service.original_sources(item)
        invalid_keys = {issue["key"] for issue in duplicate_issues(entries(sources,item["game"],strict=False))}
        # Ensure any local Chinese files in the Mod directory are indexed before exporting.
        if sources and self.service.target_language != 'zh-TW':
            self.import_candidates(item, sources, candidates(item['path'], item['game']), '本机中文')
        cache_payload = self.export(item)
        cache_filename = f"{item['id'].replace(':', '-')}.cache.json"
        package_files = {
            cache_filename: json.dumps(cache_payload, ensure_ascii=False, indent=2).encode('utf-8')
        }
        with self.service.connect() as db:
            cached_rows = {(f, k, h): t for f, k, h, t in db.execute(
                'SELECT source_file,entry_key,source_hash,chinese FROM translation_entries WHERE mod_id=?', (item['id'],))}
        for name, data in sorted(sources.items()):
            lines = []
            for line in data.decode('utf-8').splitlines(keepends=True):
                match = paradox.parse_line(line)
                if match:
                    key = match['prefix'].lstrip()
                    src_text = paradox.source_text(match, item['game'])
                    translated = cached_rows.get((name, key, digest(src_text)))
                    if canonical_key(key) not in invalid_keys and translated is not None and request.valid_translation(src_text, translated):
                        text = translated.replace('\n', r'\n')
                        if item['game'] == 'eu4':
                            text = paradox.special_escape(text, True, True)
                        text = re.sub(r'(?<!\\)((?:\\\\)*)"', r'\1\\"', text)
                        line = match['prefix'] + '"' + text + '"' + match['suffix'] + (match['newline'] or '')
                elif item['game'] != 'eu4' and line.lstrip('\ufeff \t').startswith('l_english:'):
                    line = line.replace('l_english:', 'l_' + __import__('localization').slot() + ':', 1)
                lines.append(line)
            rendered = ''.join(lines).encode('utf-8')
            if not rendered.startswith(b'\xef\xbb\xbf'):
                rendered = b'\xef\xbb\xbf' + rendered
            package_files[target_path(name, item['game'])] = rendered
        return archive(package_files)
