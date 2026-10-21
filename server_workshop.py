"""Workshop link lookup and bounded, asynchronous server import."""
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import threading
from urllib.parse import urlsplit, parse_qs

DOWNLOAD_LOCK = threading.Lock()


def cached_source(service, uid):
    from workshop_app import GAMES
    root = getattr(service, 'server_root', service)
    for appid in GAMES:
        path = root.data_dir / 'workshop_sources' / appid / uid
        if path.is_dir():
            return appid, path
    return None


def remember_source(service, appid, uid, source):
    root = getattr(service, 'server_root', service)
    target = root.data_dir / 'workshop_sources' / appid / uid
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=root.data_dir) as temp:
            staged = Path(temp) / 'source'
            copy_translation_files(source, staged)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                staged.rename(target)
            except FileExistsError:
                pass
    return target


def attach_cached(service, appid, uid, source):
    target = service.data_dir / 'uploaded_library/steamapps/workshop/content' / appid / uid
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=service.data_dir) as temp:
            staged = Path(temp) / 'copy'
            copy_translation_files(source, staged)
            target.parent.mkdir(parents=True, exist_ok=True)
            staged.rename(target)
        service.scan(lambda ids: {})


def workshop_uid(link):
    if not isinstance(link, str) or len(link) > 2048:
        raise ValueError('请粘贴 Steam 创意工坊 Mod 链接')
    url = urlsplit(link.strip())
    ids = parse_qs(url.query).get('id', [])
    if (url.scheme not in ('https', 'http') or url.hostname not in
            ('steamcommunity.com', 'www.steamcommunity.com') or url.username or url.password
            or url.path not in ('/sharedfiles/filedetails/', '/sharedfiles/filedetails',
                                '/workshop/filedetails/', '/workshop/filedetails')
            or len(ids) != 1 or not re.fullmatch(r'[1-9][0-9]{0,19}', ids[0])):
        raise ValueError('请输入有效的 Steam 创意工坊 Mod 链接（含 id=数字）')
    return ids[0]


def lookup(service, link):
    from workshop_app import GAMES, workshop_details
    uid = workshop_uid(link)
    cached = cached_source(service, uid)
    if cached:
        attach_cached(service, cached[0], uid, cached[1])
    for item in service.inventory.values():
        if item['uid'] == uid:
            return {**{k: item[k] for k in ('id', 'uid', 'appid', 'title')}, 'downloaded': True}
    try:
        detail = workshop_details([uid]).get(uid)
    except Exception as error:
        raise ValueError('Steam 查询暂时失败，请稍后重试') from error
    if not detail or str(detail.get('consumer_app_id')) not in GAMES or detail.get('file_type', 0) != 0:
        raise ValueError('未找到支持的 P 社游戏 Mod；请勿使用合集或私有条目链接')
    appid = str(detail['consumer_app_id'])
    return {'id': f'{appid}:{uid}', 'uid': uid, 'appid': appid,
            'title': detail['title'], 'downloaded': False}


def copy_translation_files(source, destination):
    """Copy only localisation YML, descriptor and local cover; reject links."""
    source, destination = Path(source), Path(destination)
    selected = []
    for folder in ('localisation', 'localization'):
        root = source / folder
        if root.is_dir() and not root.is_symlink():
            selected.extend(p for p in root.rglob('*') if p.suffix.lower() == '.yml' and p.is_file())
    if not selected:
        raise ValueError('下载完成，但未找到本地化 YML 文件')
    descriptor = source / 'descriptor.mod'
    if descriptor.is_file() and not descriptor.is_symlink():
        selected.append(descriptor)
        match = re.search(r'^\s*picture\s*=\s*"([^"]+)"', descriptor.read_text(errors='replace'), re.M)
        if match:
            picture = source / match[1]
            if picture.resolve().is_relative_to(source.resolve()) and picture.is_file():
                selected.append(picture)
    selected.extend(p for p in source.glob('thumbnail.*') if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif'))
    selected = list(dict.fromkeys(selected))
    total = 0
    for path in selected:
        relative = path.relative_to(source)
        if any(source.joinpath(*relative.parts[:i]).is_symlink() for i in range(1, len(relative.parts) + 1)) or not path.is_file():
            raise ValueError('下载内容包含不安全的文件链接')
        total += path.stat().st_size
        if total > 128 * 1024 * 1024 or len(selected) > 5000:
            raise ValueError('本地化内容超过导入上限（128 MB / 5000 文件）')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return len(selected), total


def download(service, item):
    service.log('等待下载通道…')
    with DOWNLOAD_LOCK:
        cached = cached_source(service, item['uid'])
        if cached:
            attach_cached(service, cached[0], item['uid'], cached[1])
            return {'id': item['id']}
        return _download(service, item)


def _download(service, item):
    appid, uid = item['appid'], item['uid']
    destination = service.data_dir / 'uploaded_library/steamapps/workshop/content' / appid / uid
    if destination.exists():
        service.scan(lambda ids: {})
        return {'id': item['id']}
    executable = os.environ.get('TRANSLATOR_STEAMCMD', '/usr/local/bin/steamcmd')
    service.log(f'正在匿名下载：{item["title"]}。SteamCMD 先下载完整 Mod，完成后仅保留本地化、描述和封面。')
    with tempfile.TemporaryDirectory(prefix='workshop-download-', dir=service.data_dir) as temp:
        library = Path(temp) / 'library'
        command = [executable, '-skipinitialbootstrap', '-inhibitbootstrap',
                   '+@ShutdownOnFailedCommand', '1', '+@NoPromptForPassword', '1',
                   '+force_install_dir', str(library), '+login', 'anonymous',
                   '+workshop_download_item', appid, uid, 'validate', '+quit']
        with (Path(temp) / 'steamcmd.log').open('w+') as log:
            try:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + 600
                try:
                    while process.poll() is None:
                        if time.monotonic() > deadline:
                            raise ValueError('Steam 下载超过 10 分钟，已停止并清理临时文件，请重试')
                        if shutil.disk_usage(temp).free < 512 * 1024 * 1024:
                            raise ValueError('服务器剩余空间不足，已停止下载并清理临时文件')
                        if sum(p.stat().st_size for p in Path(temp).rglob('*') if p.is_file() and not p.is_symlink()) > 2 * 1024**3:
                            raise ValueError('Mod 下载超过 2 GB 上限，已停止并清理临时文件')
                        time.sleep(2)
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            except FileNotFoundError as error:
                raise ValueError('服务器尚未配置 SteamCMD 下载程序') from error
            log.seek(0)
            output = log.read()
        if process.returncode or f'Success. Downloaded item {uid} ' not in output:
            reason = next((line.strip() for line in output.splitlines() if 'ERROR!' in line or 'Fatal Error' in line), '')
            raise ValueError('匿名下载失败：' + (reason[:300] or 'Steam 连接失败或该 Mod 不允许匿名下载，请稍后重试或上传 ZIP'))
        source = library / 'steamapps/workshop/content' / appid / uid
        staged = Path(temp) / 'retained'
        count, size = copy_translation_files(source, staged)
        remember_source(service, appid, uid, staged)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged.rename(destination)
    service.scan(lambda ids: {})
    service.log(f'已保留 {count} 个翻译所需文件（{size:,} 字节），其他下载文件已清理。请扫描此 Mod，再配置自己的 API 开始翻译。')
    return {'id': item['id'], 'files': count, 'bytes': size}
