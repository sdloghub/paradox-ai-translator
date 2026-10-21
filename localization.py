"""Explicit UI/translation languages and isolated per-language workspaces."""
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import copy
import inspect
import threading

LANGUAGES = {
    'zh-CN': {'name': '简体中文', 'slot': 'simp_chinese'},
    # Paradox has no Traditional Chinese slot; use its Chinese language slot.
    'zh-TW': {'name': '繁體中文', 'slot': 'simp_chinese'},
    'ru': {'name': 'Русский', 'slot': 'russian'},
}
_language = ContextVar('translation_language', default='zh-CN')


def normalize(language):
    if language not in LANGUAGES:
        raise ValueError('Unsupported language / 不支持的语言')
    return language


def current_language():
    return _language.get()


def slot():
    return LANGUAGES[current_language()]['slot']


def language_bound(cls):
    """Bind core helpers to a service, including jobs running on worker threads."""
    def bind(function):
        @wraps(function)
        def wrapped(self, *args, **kwargs):
            token = _language.set(getattr(self, 'target_language', 'zh-CN'))
            try:
                return function(self, *args, **kwargs)
            finally:
                _language.reset(token)
        return wrapped
    for name, value in list(vars(cls).items()):
        if inspect.isfunction(value) and name != '__init__':
            setattr(cls, name, bind(value))
    return cls


def workspace(base, language):
    """Never mix caches/history/exports across target languages or visitors."""
    language = normalize(language)
    if not hasattr(base, 'language_lock'):
        # All HTTP servers initialize this before accepting requests.
        base.language_lock = threading.RLock()
    with base.language_lock:
        family = getattr(base, 'language_workspaces', {})
        if language == 'zh-CN':
            sync_catalog(base, base, family)
            return base
        if language not in family:
            from workshop_app import WorkshopService
            root = base.data_dir / 'languages' / language
            service = WorkshopService(root, program_dir=root / 'defaults', target_language=language)
            service.language_base = base
            service.config_path = base.config_path
            service.providers_path = base.providers_path
            service.config_directories = base.config_directories
            service.demo = base.demo
            service.demo_library = base.data_dir / 'demo_steam'
            for attr in ('server_mode', 'server_root', 'visitor_id', 'documents_dir'):
                if hasattr(base, attr):
                    setattr(service, attr, getattr(base, attr))
            if getattr(base, 'server_mode', False):
                service.server_root = getattr(base, 'server_root', base)
            family[language] = service
            base.language_workspaces = family
        service = family[language]
        sync_catalog(base, service, family)
        return service


def sync_catalog(base, service, family):
    # Only Mod metadata/originals are shared within this visitor's family.
    from workshop_app import now
    for sibling in [base, *family.values()]:
        for identifier, original in list(sibling.inventory.items()):
            if identifier in service.inventory:
                continue
            item = copy.deepcopy(original)
            for key in ('counts', 'cache_selection', 'shared_credits', 'translated'):
                item.pop(key, None)
            item['scan_state'] = '未扫描'
            if getattr(service, 'server_mode', False):
                from server_workshop import copy_translation_files
                destination = service.data_dir / 'uploaded_library/steamapps/workshop/content' / item['appid'] / item['uid']
                if not destination.exists():
                    copy_translation_files(Path(item['path']), destination)
                item['path'] = str(destination)
            service.inventory[identifier] = item
            with service.connect() as db:
                db.execute('INSERT OR REPLACE INTO mods VALUES (?,?,?,?,?,?,?)',
                           (identifier, item['uid'], item['appid'], item['title'], item['path'], item['url'], now()))
                service.persist_item(item, db=db)
