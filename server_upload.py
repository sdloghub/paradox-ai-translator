"""Bounded ZIP import for a personal server accessed through an SSH tunnel."""
import io
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

MAX_UPLOAD = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024


def upload_mod(service, data, appid, uid):
    from workshop_app import GAMES
    if appid not in GAMES or not re.fullmatch(r'[1-9][0-9]{0,19}', uid):
        raise ValueError('请选择游戏并填写原 Mod 的数字工坊 ID')
    if not 0 < len(data) <= MAX_UPLOAD:
        raise ValueError('ZIP 最大为 32 MB')
    library = service.data_dir / 'uploaded_library'
    destination = library / 'steamapps/workshop/content' / appid / uid
    if destination.exists() or destination.is_symlink():
        raise ValueError('此 Mod 已上传；请使用已有条目，避免覆盖译文')
    for parent in destination.parents:
        if parent.is_symlink():
            raise ValueError('上传目录包含符号链接')
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ValueError('请上传有效的 ZIP 压缩包') from error
    with archive, tempfile.TemporaryDirectory(dir=service.data_dir, prefix='upload-') as temporary:
        members = archive.infolist()
        if len(members) > 5000 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise ValueError('ZIP 解压后不得超过 128 MB 或 5000 个条目')
        seen = set()
        for member in members:
            name = member.filename
            path = PurePosixPath(name)
            mode = member.external_attr >> 16
            if (not name or '\\' in name or ':' in name or path.is_absolute()
                    or '..' in path.parts or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    or member.flag_bits & 1):
                raise ValueError('ZIP 含不安全路径、链接或加密文件')
            folded = str(path).casefold()
            if folded in seen:
                raise ValueError('ZIP 含重名路径')
            seen.add(folded)
        extracted = Path(temporary) / 'extracted'
        extracted.mkdir()
        total = 0
        for member in members:
            target = extracted.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open('xb') as output:
                while chunk := source.read(65536):
                    total += len(chunk)
                    if total > MAX_EXPANDED:
                        raise ValueError('ZIP 解压内容过大')
                    output.write(chunk)
        root = extracted
        while True:
            children = [p for p in root.iterdir() if p.name not in ('__MACOSX', '.DS_Store')]
            if len(children) == 1 and children[0].is_dir() and children[0].name not in ('localisation', 'localization'):
                root = children[0]
            else:
                break
        if not any((root / name).is_dir() for name in ('localisation', 'localization')):
            raise ValueError('ZIP 内未找到 localisation 或 localization 目录')
        destination.parent.mkdir(parents=True, exist_ok=True)
        root.rename(destination)
    from server_workshop import remember_source
    remember_source(service, appid, uid, destination)
    service.scan(lambda ids: {})
    return {'ok': True, 'id': f'{appid}:{uid}'}


def saved_translation(service, upload_id):
    """Resolve a developer upload by opaque ID, never by a client-supplied path."""
    import json
    if not isinstance(upload_id, str) or not re.fullmatch(r'[0-9a-f]{32}', upload_id):
        raise ValueError('已保存译文不存在')
    directory = service.data_dir / 'saved_imports' / upload_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(service.data_dir.resolve()):
        raise ValueError('已保存译文路径无效')
    try:
        metadata_path = directory / 'metadata.json'
        if metadata_path.is_symlink():
            raise ValueError('已保存译文路径无效')
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        suffix = Path(metadata['filename']).suffix.lower()
        if metadata.get('id') != upload_id or suffix not in ('.yml', '.yaml', '.json', '.zip'):
            raise ValueError('已保存译文记录无效')
        path = directory / ('upload' + suffix)
        if path.is_symlink() or not path.is_file():
            raise ValueError('已保存译文文件不存在')
        return metadata, path
    except (OSError, KeyError, TypeError) as error:
        raise ValueError('已保存译文不存在') from error


def saved_translations(service):
    result = []
    for directory in (service.data_dir / 'saved_imports').glob('*'):
        try:
            metadata, _ = saved_translation(service, directory.name)
            result.append(metadata)
        except ValueError:
            continue
    return sorted(result, key=lambda item: item['created_at'], reverse=True)


def save_translation(service, data, filename, provider=''):
    import json
    import secrets
    from workshop_app import atomic_bytes, now
    # Store original bytes even if there is no matching Mod or parsing later fails.
    filename = Path(filename.replace('\\', '/')).name[:200]
    suffix = Path(filename).suffix.lower()
    if suffix not in ('.yml', '.yaml', '.json', '.zip') or not 0 < len(data) <= MAX_UPLOAD:
        raise ValueError('译文文件格式或大小无效')
    upload_id = secrets.token_hex(16)
    directory = service.data_dir / 'saved_imports' / upload_id
    directory.mkdir(parents=True, mode=0o700)
    metadata = {'id': upload_id, 'filename': filename, 'size': len(data),
                'provider': str(provider)[:80], 'created_at': now()}
    atomic_bytes(directory / ('upload' + suffix), data, private=True)
    atomic_bytes(directory / 'metadata.json', json.dumps(metadata, ensure_ascii=False).encode(), private=True)
    return metadata, directory / ('upload' + suffix)
