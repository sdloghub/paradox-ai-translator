"""Indexed entry snapshots and source-version-specific human status labels."""
import hashlib
import json
import secrets
import sqlite3

STATUSES = ('translated', 'untranslated', 'cached', 'format_error', 'needs_update')


class EntryBrowser:
    def __init__(self, service):
        self.service = service
        with service.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS entry_snapshots (
                    mod_id TEXT PRIMARY KEY, revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS browsable_entries (
                    mod_id TEXT NOT NULL, entry_id TEXT NOT NULL,
                    source_file TEXT NOT NULL, line INTEGER NOT NULL,
                    entry_key TEXT NOT NULL, english TEXT NOT NULL,
                    chinese TEXT NOT NULL, origin TEXT NOT NULL,
                    auto_status TEXT NOT NULL, original_line TEXT NOT NULL,
                    reason TEXT NOT NULL, historical INTEGER NOT NULL,
                    PRIMARY KEY(mod_id,entry_id));
                CREATE INDEX IF NOT EXISTS entry_order ON browsable_entries(mod_id,source_file,line);
                CREATE TABLE IF NOT EXISTS entry_reviews (
                    mod_id TEXT NOT NULL, entry_id TEXT NOT NULL,
                    status TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(mod_id,entry_id));
            ''')

    def replace(self, identifier, rows):
        # Stable through unrelated inserted lines, distinct for duplicate keys,
        # and invalidated when the English text or malformed raw line changes.
        occurrences = {}
        values = []
        for row in rows:
            key = (row['source_file'], row['key'])
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            content = row['original_line'] if row['auto_status'] == 'format_error' else row['english']
            identity = [*key, occurrence, content, row['auto_status'] == 'format_error']
            entry_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
            values.append((identifier, entry_id, row['source_file'], row['line'], row['key'],
                           row['english'], row['chinese'], row['origin'], row['auto_status'],
                           row['original_line'], row['reason'], int(row['historical'])))
        revision = secrets.token_hex(12)
        with self.service.connect() as db:
            db.execute('DELETE FROM browsable_entries WHERE mod_id=?', (identifier,))
            db.executemany('INSERT INTO browsable_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', values)
            db.execute('INSERT OR REPLACE INTO entry_snapshots VALUES (?,?)', (identifier, revision))
        return revision

    def list(self, identifier, status='all', query='', page=1, page_size=50):
        if status != 'all' and status not in STATUSES:
            raise ValueError('条目状态无效')
        if not isinstance(query, str) or len(query) > 256:
            raise ValueError('搜索内容最多 256 个字符')
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
            raise ValueError('分页参数无效')
        join = '''FROM browsable_entries e LEFT JOIN entry_reviews r
                  ON e.mod_id=r.mod_id AND e.entry_id=r.entry_id WHERE e.mod_id=?'''
        effective = 'COALESCE(r.status,e.auto_status)'
        where = ''
        arguments = [identifier]
        if status != 'all':
            where += f' AND {effective}=?'
            arguments.append(status)
        if query.strip():
            where += ''' AND (instr(lower(e.entry_key),lower(?))>0
                         OR instr(lower(e.english),lower(?))>0
                         OR instr(lower(e.chinese),lower(?))>0
                         OR instr(lower(e.source_file),lower(?))>0)'''
            arguments.extend([query.strip()] * 4)
        with self.service.connect() as db:
            db.row_factory = sqlite3.Row
            snapshot = db.execute('SELECT revision FROM entry_snapshots WHERE mod_id=?', (identifier,)).fetchone()
            counts = dict.fromkeys(STATUSES, 0)
            for row in db.execute(f'SELECT {effective} AS status, COUNT(*) AS n ' + join + ' GROUP BY 1', (identifier,)):
                counts[row['status']] = row['n']
            total = db.execute('SELECT COUNT(*) ' + join + where, arguments).fetchone()[0]
            pages = max(1, (total + page_size - 1) // page_size)
            page = min(page, pages)
            rows = db.execute(f'''SELECT e.*, r.status AS manual_status,
                                  {effective} AS status, r.updated_at AS reviewed_at ''' + join + where +
                              ' ORDER BY e.source_file,e.line LIMIT ? OFFSET ?',
                              arguments + [page_size, (page - 1) * page_size]).fetchall()
            manual = db.execute('SELECT COUNT(*) ' + join + ' AND r.status IS NOT NULL', (identifier,)).fetchone()[0]
        return {'ready': snapshot is not None, 'revision': snapshot[0] if snapshot else None,
                'entries': [dict(row) for row in rows], 'counts': counts, 'manual_count': manual,
                'total': total, 'page': page, 'pages': pages, 'page_size': page_size}

    def mark(self, identifier, entry_id, status):
        if status is not None and status not in STATUSES:
            raise ValueError('条目状态无效')
        if not isinstance(entry_id, str) or len(entry_id) != 64:
            raise ValueError('条目标识无效')
        with self.service.connect() as db:
            if not db.execute('SELECT 1 FROM browsable_entries WHERE mod_id=? AND entry_id=?', (identifier, entry_id)).fetchone():
                raise ValueError('条目已变化，请刷新浏览页后重新标注')
            if status is None:
                db.execute('DELETE FROM entry_reviews WHERE mod_id=? AND entry_id=?', (identifier, entry_id))
            else:
                db.execute('INSERT OR REPLACE INTO entry_reviews(mod_id,entry_id,status) VALUES (?,?,?)',
                           (identifier, entry_id, status))
        return {'ok': True}

    def get(self, identifier, entry_id):
        if not isinstance(entry_id, str) or len(entry_id) != 64:
            raise ValueError('条目标识无效')
        with self.service.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM browsable_entries WHERE mod_id=? AND entry_id=?',
                             (identifier, entry_id)).fetchone()
        if row is None:
            raise ValueError('条目已变化，请刷新后重新编辑')
        return dict(row)
