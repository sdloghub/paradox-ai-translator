import os
import re
from pathlib import Path
from typing import Dict, List

import request

def cp1252_utf8(char,type):
    # CP1252 到 UTF-8 的映射表
    escape_map = {
        0x80: 0x20AC, 0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E,
        0x85: 0x2026, 0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02C6,
        0x89: 0x2030, 0x8A: 0x0160, 0x8B: 0x2039, 0x8C: 0x0152,
        0x8E: 0x017D, 0x91: 0x2018, 0x92: 0x2019, 0x93: 0x201C,
        0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014,
        0x98: 0x02DC, 0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A,
        0x9C: 0x0153, 0x9E: 0x017E, 0x9F: 0x0178
    }
    reverse_escape_map = {
        0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84,
        0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88,
        0x2030: 0x89, 0x0160: 0x8A, 0x2039: 0x8B, 0x0152: 0x8C,
        0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93,
        0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
        0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B,
        0x0153: 0x9C, 0x017E: 0x9E, 0x0178: 0x9F
    }
    if type=="cp1252":
        return escape_map.get(char, char)  # 返回映射值或原值
    elif type=="utf8":
        return reverse_escape_map.get(char, char)
    else:
        return char
def special_escape(s, to_utf8, new_version):
    """
    处理整个字符串的特殊转义
    :param s: 输入字符串
    :param to_utf8: 是否转换为UTF-8
    :param new_version: 是否使用新版本规则
    :return: 转义后的字符串
    """
    result = []
    for char in s:
        # 如果字符码点小于256，直接使用原字符
        code_point = ord(char)
        if code_point < 256:
            result.append(char)
            continue
        
        # 获取十六进制表示并分割高低字节
        hex_str = hex(code_point)[2:]
        low = int(hex_str[-2:], 16)  # 低字节（最后两位）
        high = int(hex_str[:2], 16) if len(hex_str) > 2 else 0  # 高字节（前两位）
        
        # 定义需要转义的内部字符列表
        internal_chars = [
            0x00, 0x0A, 0x0D, 0x20, 0x22, 0x24, 0x40, 0x5B, 0x5C, 0x7B, 0x7D, 0x7E, 0x80,
            0xA3, 0xA4, 0xA7, 0xBD, 0x3B, 0x5D, 0x5F, 0x3D, 0x23
        ]
        
        # 根据参数调整字符列表和偏移量
        low_byte_offset = 15
        high_byte_offset = -9
        
        if to_utf8:
            internal_chars.append(0x2F)  # 添加斜杠字符
            if not new_version:
                if 0x20 in internal_chars:
                    internal_chars.remove(0x20)  # 旧版本移除空格
        
        if new_version:
            low_byte_offset = 14  # 新版本调整低字节偏移量
        
        # 确定转义字符值
        escape_chr = 0x10
        if high in internal_chars:
            escape_chr += 2
        if low in internal_chars:
            escape_chr += 1
        
        # 应用偏移量调整
        if escape_chr == 0x11:
            low += low_byte_offset
        elif escape_chr == 0x12:
            high += high_byte_offset
        elif escape_chr == 0x13:
            low += low_byte_offset
            high += high_byte_offset
        
        # 转换为UTF-8编码
        if to_utf8:
            low = cp1252_utf8(low,"cp1252")
            high = cp1252_utf8(high,"cp1252")
        
        # 添加转义后的字符序列
        result.append(chr(escape_chr))
        result.append(chr(low))
        result.append(chr(high))
    
    return ''.join(result)
    
def special_unescape(s, to_utf8, new_version):
    """
    将转义后的字符串还原为原始字符串
    :param s: 转义后的字符串
    :param to_utf8: 是否从 UTF-8 转换
    :param new_version: 是否使用新版本规则
    :return: 原始字符串
    """
    result = []
    i = 0
    n = len(s)
    
    # 定义偏移量
    low_byte_offset = 15
    if new_version:
        low_byte_offset = 14
    
    while i < n:
        # 检查是否是转义序列
        if ord(s[i]) in [0x10, 0x11, 0x12, 0x13] and i + 2 < n:
            escape_chr = ord(s[i])
            low = ord(s[i+1])
            high = ord(s[i+2])
            
            # 从 UTF-8 转换回 CP1252
            if to_utf8:
                low = cp1252_utf8(low,"utf8")
                high = cp1252_utf8(high,"utf8")
            
            # 应用反向偏移
            if escape_chr == 0x11:
                low -= low_byte_offset
            elif escape_chr == 0x12:
                high -= -9  # 注意：-9 的反向是 +9
            elif escape_chr == 0x13:
                low -= low_byte_offset
                high -= -9  # 注意：-9 的反向是 +9
            
            # 组合原始字符
            code_point = (high << 8) | low
            result.append(chr(code_point))
            i += 3  # 跳过转义序列
        else:
            # 普通字符直接添加
            result.append(s[i])
            i += 1
    
    return ''.join(result)

ROOT = Path(__file__).resolve().parent

class LocalisationError(ValueError):
    """A local file diagnostic safe to show without provider response bodies."""

class Paradox_data:
    def __init__(self, key_w, word, vis):
        self.key_w, self.word, self.vis = key_w, word, vis

# Preserve indentation, key/version, trailing comments and original line endings.
ENTRY = re.compile(r'^(?P<prefix>\s*[^#\s][^"\r\n]*?:\s*\d*\s*)"(?P<text>(?:\\.|[^"\\])*)"(?P<extra_quotes>"*)(?P<suffix>[ \t]*(?:#[^\r\n]*)?)(?P<newline>\r?\n)?$')

def parse_line(line):
    return ENTRY.fullmatch(line)

def checked_line(line, path, number):
    match = parse_line(line)
    if not match and not line.lstrip().startswith('#') and ':' in line and '"' in line:
        raise LocalisationError(f"无法解析本地化条目：{path}:{number}；请检查闭合引号、转义和行尾内容")
    return match

def source_text(match, game):
    text = match['text']
    return special_unescape(text, True, True) if game == 'eu4' else text

def output_name(local_path, game):
    path = Path(local_path)
    return path if game == 'eu4' else path.with_name(path.name.replace('l_english', 'l_simp_chinese'))

def extract(path, mde, issues=None):
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        entries = []
        for number, line in enumerate(source, 1):
            try:
                match = checked_line(line, path, number)
            except LocalisationError:
                if issues is None:
                    raise
                issues.append({'file': str(path), 'line': number, 'reason': '无法解析；已保留英文原行'})
                continue
            if match:
                if match['extra_quotes']:
                    import logging
                    logging.warning('多余闭合引号将在中文输出中规范化：%s:%s', path, number)
                entries.append((match['prefix'].lstrip(), source_text(match, mde)))
        return entries

def atomic_write(path, text):
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

def outputs(local_path, dic, mde, output_root=None, project_root=None):
    project_root = Path(project_root) if project_root is not None else ROOT
    src = project_root / 'localisation' / local_path
    dst = (Path(output_root) if output_root is not None else project_root / 'chn') / output_name(local_path, mde)
    lines = []
    # Read UTF-8 without stripping BOM so it is retained in the output.
    with src.open(encoding='utf-8', newline='') as source:
        for line in source:
            match = parse_line(line)
            if match and match['prefix'].lstrip() in dic:
                text = dic[match['prefix'].lstrip()].word.replace('\n', r'\n')
                if mde == 'eu4':
                    text = special_escape(text, True, True)
                # Escape unescaped quotes; existing game escapes remain intact.
                text = re.sub(r'(?<!\\)((?:\\\\)*)"', r'\1\\"', text)
                line = match['prefix'] + '"' + text + '"' + match['suffix'] + (match['newline'] or '')
            elif mde != 'eu4' and line.lstrip('\ufeff \t').startswith('l_english:'):
                line = line.replace('l_english:', 'l_simp_chinese:', 1)
            lines.append(line)
    atomic_write(dst, ''.join(lines))

def translate_para(local_path, mde, output_root=None, project_root=None, translator=None, issues=None):
    import hashlib
    import json
    import logging
    project_root = Path(project_root) if project_root is not None else ROOT
    translator = translator or request.request_deepseek_batch
    entries = extract(project_root / 'localisation' / local_path, mde, issues=issues)
    line_numbers = {}
    if issues is not None:
        with (project_root / 'localisation' / local_path).open(encoding='utf-8-sig') as stream:
            for number, line in enumerate(stream, 1):
                match = parse_line(line)
                if match:
                    line_numbers[match['prefix'].lstrip()] = number
    cache_path = project_root / 'already' / (str(local_path) + '.cache.json')
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
        if not isinstance(cache, dict):
            raise ValueError('缓存格式错误')
    except (ValueError, OSError):
        logging.warning('缓存损坏，重新翻译：%s', cache_path)
        cache = {}
    tran, pending, hashes = {}, [], {}
    for key, text in entries:
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        hashes[key] = digest
        cached = cache.get(key)
        valid = isinstance(cached, dict) and cached.get('source_hash') == digest and isinstance(cached.get('text'), str) and request.valid_translation(text, cached['text'])
        blank = not text.strip()
        tran[key] = Paradox_data(key, text if blank else cached['text'] if valid else text, int(blank or valid))
    for key, item in tran.items():
        if not item.vis:
            pending.append(key)
    successful = len(tran) - len(pending)
    failures = 0
    for offset in range(0, len(pending), 150):
        keys = pending[offset:offset + 150]
        try:
            results = translator([tran[key].word for key in keys], mde, successful, len(tran))
            if len(results) != len(keys):
                raise ValueError('请求结果数量与输入不一致')
        except ValueError:
            if issues is None:
                raise
            results = [{'success': False, 'text': tran[key].word} for key in keys]
        for key, result in zip(keys, results):
            if result['success'] and request.valid_translation(tran[key].word, result['text']):
                tran[key].word, tran[key].vis = result['text'], 1
                cache[key] = {'source_hash': hashes[key], 'text': result['text']}
                successful += 1
            else:
                failures += 1
                if issues is not None:
                    issues.append({'file': str(local_path), 'line': line_numbers[key], 'reason': '翻译失败或返回格式异常；已保留英文'})
        # Save each completed segment independently of final publication.
        atomic_write(cache_path, json.dumps(cache, ensure_ascii=False, indent=2))
    outputs(local_path, tran, mde, output_root, project_root)
    return failures
