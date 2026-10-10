"""Versioned source/translation mappings shared by scan, import and translation."""
import hashlib
import json
from pathlib import Path
import re

import paradox
import request

FORMAT = 'workshop-translator-cache-v1'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def entries(files, game):
    result = []
    for filename, data in files.items():
        for line in data.decode('utf-8-sig').splitlines(keepends=True):
            match = paradox.parse_line(line)
            if match:
                result.append({'source_file': filename, 'key': match['prefix'].lstrip(),
                               'text': paradox.source_text(match, game)})
    return result


def canonical_key(key):
    return key.split(':', 1)[0].strip()


def comparable_file(name):
    parts = Path(name).as_posix().split('/')
    while parts and parts[0] not in ('localisation', 'localization'):
        parts.pop(0)
    if parts:
        parts.pop(0)
    parts = [part for part in parts if part not in ('english', 'simp_chinese', 'replace')]
    return '/'.join(parts).replace('l_simp_chinese', 'l_english')


def candidates(path, game):
    path = Path(path).expanduser().resolve()
    paths = sorted(list(path.rglob('*.yml')) + list(path.rglob('*.cache.json'))) if path.is_dir() else [path]
    result = []
    for file in paths:
        if file.is_symlink() or not file.is_file():
            continue
        if path.is_dir() and not file.resolve().is_relative_to(path):
            continue
        if file.suffix.lower() == '.json':
            payload = json.loads(file.read_text(encoding='utf-8-sig'))
            if not isinstance(payload, dict):
                raise ValueError('缓存 JSON 必须是对象')
            if payload.get('format') == FORMAT:
                result.extend({**entry, 'mod_id': payload.get('mod_id')} for entry in payload.get('entries', []) if isinstance(entry, dict))
            else:
                # Old per-file cache: source_hash is mandatory to accept it.
                for key, value in payload.items():
                    if isinstance(value, dict) and isinstance(value.get('source_hash'), str):
                        result.append({'key': key, 'text': value.get('text'), 'source_hash': value['source_hash']})
        elif file.suffix.lower() == '.yml':
            data = file.read_bytes()
            text = data.decode('utf-8-sig')
            chinese_header = bool(re.search(r'^\s*l_simp_chinese\s*:', text, re.M))
            for entry in entries({str(file): data}, game):
                if re.search(r'[\u3400-\u9fff]', entry['text']):
                    # English-headed files may already contain fully localized Chinese.
                    if chinese_header or game == 'eu4' or not re.search(r'[A-Za-z]{2,}', request.TOKENS.sub('', entry['text'])):
                        result.append(entry)
    return result


class ModCache:
    def __init__(self, service):
        self.service = service
        with service.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS translation_entries (
                mod_id TEXT NOT NULL, source_file TEXT NOT NULL, entry_key TEXT NOT NULL,
                source_hash TEXT NOT NULL, chinese TEXT NOT NULL, chinese_hash TEXT NOT NULL,
                origin TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(mod_id,source_file,entry_key,source_hash))''')
            db.execute('CREATE INDEX IF NOT EXISTS cache_chinese ON translation_entries(mod_id,chinese_hash)')

    def put(self, db, identifier, entry, text, origin):
        db.execute('''INSERT OR REPLACE INTO translation_entries
            (mod_id,source_file,entry_key,source_hash,chinese,chinese_hash,origin)
            VALUES (?,?,?,?,?,?,?)''', (identifier, entry['source_file'], entry['key'], digest(entry['text']), text, digest(text), origin))

    def import_candidates(self, item, sources, translations, origin):
        source_entries = entries(sources, item['game'])
        imported = rejected = 0
        source_counts = {}
        for entry in source_entries:
            key = canonical_key(entry['key'])
            source_counts[key] = source_counts.get(key, 0) + 1
        by_key = {}
        for translated in translations:
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
                    # Preserve existing validated translation for this exact source version.
                    existing = db.execute('''SELECT chinese FROM translation_entries WHERE
                        mod_id=? AND source_file=? AND entry_key=? AND source_hash=?''',
                        (item['id'], entry['source_file'], entry['key'], digest(entry['text']))).fetchone()
                    if not existing:
                        self.put(db, item['id'], entry, valid[0], origin)
                        imported += 1
                elif valid:
                    rejected += 1
        return {'imported': imported, 'rejected': rejected}

    def sync_workspace(self, item, sources, origin='翻译缓存'):
        workspace = self.service.data_dir / 'workspaces' / item['appid'] / item['uid']
        with self.service.connect() as db:
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
                for entry in entries({name: sources[name]}, item['game']):
                    h = digest(entry['text'])
                    row = db.execute('''SELECT chinese FROM translation_entries WHERE
                        mod_id=? AND source_file=? AND entry_key=? AND source_hash=?''',
                        (item['id'], name, entry['key'], h)).fetchone()
                    cached = existing.get(entry['key'], {})
                    if row:
                        existing[entry['key']] = {'source_hash': h, 'text': row[0]}
                    elif isinstance(cached, dict) and cached.get('source_hash') == h and request.valid_translation(entry['text'], cached.get('text')):
                        self.put(db, item['id'], entry, cached['text'], origin)
                paradox.atomic_write(path, json.dumps(existing, ensure_ascii=False, indent=2))
        return workspace

    def stats(self, item, sources):
        current = entries(sources, item['game'])
        translated = needs_update = 0
        origins = {}
        with self.service.connect() as db:
            for entry in current:
                row = db.execute('''SELECT chinese,origin FROM translation_entries WHERE
                    mod_id=? AND source_file=? AND entry_key=? AND source_hash=?''',
                    (item['id'], entry['source_file'], entry['key'], digest(entry['text']))).fetchone()
                if row and request.valid_translation(entry['text'], row[0]):
                    translated += 1
                    origins[row[1]] = origins.get(row[1], 0) + 1
                elif db.execute('SELECT 1 FROM translation_entries WHERE mod_id=? AND source_file=? AND entry_key=? LIMIT 1', (item['id'], entry['source_file'], entry['key'])).fetchone():
                    needs_update += 1
        return {'total': len(current), 'translated': translated, 'untranslated': len(current) - translated, 'files': len(sources), 'needs_update': needs_update, 'origins': [{'name': name, 'count': count} for name, count in sorted(origins.items())]}

    def export(self, item):
        with self.service.connect() as db:
            rows = db.execute('''SELECT source_file,entry_key,source_hash,chinese,origin FROM translation_entries WHERE mod_id=?''', (item['id'],)).fetchall()
        return {'format': FORMAT, 'mod_id': item['id'], 'title': item['title'],
                'entries': [{'source_file': f, 'key': k, 'source_hash': h, 'text': t, 'origin': o} for f, k, h, t, o in rows]}
