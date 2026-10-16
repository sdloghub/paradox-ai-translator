"""Keep startup diagnostics available when launched from Finder."""
import os
from pathlib import Path
import sys

if sys.stdout is None or sys.stderr is None:
    folder = Path(os.environ.get('WORKSHOP_LOG_DIR',
                                 str(Path.home() / 'Library/Logs/WorkshopTranslator')))
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / 'application.log'
    if log.exists() and log.stat().st_size > 2 * 1024 * 1024:
        log.replace(folder / 'application.previous.log')
    stream = log.open('a', encoding='utf-8', buffering=1)
    os.chmod(log, 0o600)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
