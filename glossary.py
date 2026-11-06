"""Glossary workflow, word-cloud scanning, AI extraction/approval, and web memory guards."""
from collections import Counter
import json
import re
from typing import Dict, List, Optional, Tuple

import request
from translation_cache import canonical_key, digest, entries

# Web version (--server-mode) memory & scale caps. Local desktop mode is unlimited.
SERVER_MAX_SCAN_BYTES = 32 * 1024 * 1024        # 32 MB max raw localisation bytes in memory
SERVER_MAX_SCAN_ENTRIES = 40000                 # 40,000 max localisation entries per Mod
SERVER_MAX_GLOSSARY_BYTES = 16 * 1024 * 1024    # 16 MB max text scanned for word cloud / glossary
SERVER_MAX_UNIQUE_TOKENS = 20000                # 20,000 max unique candidate phrases in counter
SERVER_MAX_GLOSSARY_TERMS = 300                 # 300 max stored glossary terms per Mod on server

WORKFLOW_MODES = ('fast', 'glossary')
EXTRACT_MODES = ('short_keys', 'long_extract', 'ai_extract')
APPROVAL_MODES = ('manual', 'ai_approve')

ENGLISH_STOPWORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'if', 'then', 'else', 'when', 'at', 'by', 'for', 'with',
    'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 'above', 'below',
    'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further',
    'once', 'here', 'there', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more',
    'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
    'too', 'very', 'can', 'will', 'just', 'should', 'now', 'is', 'are', 'was', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'would',
    'could', 'might', 'must', 'shall', 'may', 'this', 'that', 'these', 'those', 'it', 'its',
    'they', 'them', 'their', 'theirs', 'we', 'us', 'our', 'ours', 'you', 'your', 'yours',
    'he', 'him', 'his', 'she', 'her', 'hers', 'who', 'whom', 'whose', 'which', 'what',
    'one', 'two', 'three', 'new', 'old', 'also', 'even', 'still', 'yet', 'every', 'much',
    'many', 'well', 'back', 'only', 'Gain', 'Lose', 'Add', 'Remove', 'Every', 'All',
})

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
PROPER_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z'-]{2,}(?:\s+(?:of\s+|the\s+)?[A-Z][A-Za-z'-]{2,}){0,3}\b")
CHINESE_PHRASE_RE = re.compile(r"[\u4e00-\u9fff]{2,8}")


def check_server_memory_limit(service, sources: Optional[Dict[str, bytes]] = None,
                              entries_count: int = 0, stage: str = '扫描') -> None:
    """Enforce memory and entry caps in server_mode; local desktop mode has no limit."""
    if not getattr(service, 'server_mode', False):
        return
    if sources is not None:
        total_bytes = sum(len(data) for data in sources.values() if isinstance(data, (bytes, bytearray)))
        limit = SERVER_MAX_GLOSSARY_BYTES if '术语' in stage else SERVER_MAX_SCAN_BYTES
        if total_bytes > limit:
            mb = limit // (1024 * 1024)
            raise ValueError(f'网页版内存保护：{stage}文本体积（{total_bytes / (1024 * 1024):.1f} MB）超过服务器上限（{mb} MB），请使用本地版或在浏览器端处理')
    if entries_count > SERVER_MAX_SCAN_ENTRIES:
        raise ValueError(f'网页版内存保护：{stage}条目数（{entries_count} 条）超过服务器上限（{SERVER_MAX_SCAN_ENTRIES} 条），请使用本地版或在浏览器端处理')


def clean_english_for_glossary(text: str) -> str:
    """Strip Paradox variables, icons, colour codes and escapes before word-cloud tokenization."""
    if not isinstance(text, str):
        return ''
    stripped = request.TOKENS.sub(' ', text)
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    return stripped


def count_words(cleaned: str) -> List[str]:
    return WORD_RE.findall(cleaned)


def normalize_phrase(words: List[str]) -> str:
    return ' '.join(words).strip()


def extract_glossary_candidates(
    source_entries: List[Dict],
    existing_translations: Optional[Dict[str, str]] = None,
    extract_mode: str = 'short_keys',
    min_count: int = 2,
    server_mode: bool = False,
    max_terms: Optional[int] = None,
) -> List[Dict]:
    """
    Scan English entries to build a word-cloud / glossary candidate list.
    - 'short_keys': Prioritize standalone keys with < 5 words that appear multiple times (>= min_count).
    - 'long_extract': Include 'short_keys' first, plus repeated words/phrases extracted from longer keys.
    """
    if extract_mode not in EXTRACT_MODES:
        raise ValueError('术语表扫描模式无效')
    existing_translations = existing_translations or {}
    limit_tokens = SERVER_MAX_UNIQUE_TOKENS if server_mode else None
    limit_terms = max_terms or (SERVER_MAX_GLOSSARY_TERMS if server_mode else None)

    short_key_counts: Counter = Counter()
    short_key_display: Dict[str, str] = {}
    short_key_trans: Dict[str, Counter] = {}
    all_cleaned_texts: List[str] = []

    scanned_bytes = 0
    for row in source_entries:
        raw = row.get('text', '')
        if not raw or not raw.strip():
            continue
        if server_mode:
            scanned_bytes += len(raw.encode('utf-8', errors='ignore'))
            if scanned_bytes > SERVER_MAX_GLOSSARY_BYTES:
                raise ValueError('网页版内存保护：术语扫描文本超过 16 MB 内存上限，请改用快速模式或本地版')
        cleaned = clean_english_for_glossary(raw)
        if not cleaned:
            continue
        words = count_words(cleaned)
        if not words:
            continue
        all_cleaned_texts.append(cleaned)
        # Standalone short key (< 5 words)
        if 1 <= len(words) < 5 and len(cleaned) <= 80:
            phrase = normalize_phrase(words)
            folded = phrase.lower()
            if folded not in ENGLISH_STOPWORDS and not all(w.lower() in ENGLISH_STOPWORDS for w in words):
                if limit_tokens and len(short_key_counts) >= limit_tokens and folded not in short_key_counts:
                    continue
                short_key_counts[folded] += 1
                # Prefer Title Case / capitalized form
                if folded not in short_key_display or (phrase[0].isupper() and not short_key_display[folded][0].isupper()):
                    short_key_display[folded] = phrase
                zh = existing_translations.get(raw) or existing_translations.get(phrase)
                if zh:
                    short_key_trans.setdefault(folded, Counter())[zh] += 1

    # Also check if standalone short keys appear inside longer entries so keys appearing once standalone + in text count as >= 2
    if short_key_counts:
        singletons = [folded for folded, cnt in short_key_counts.items() if cnt == 1 and len(folded) >= 3]
        if singletons:
            # Build a bounded lookup over longer texts
            joined_sample = '\n'.join(all_cleaned_texts[:10000 if server_mode else len(all_cleaned_texts)]).lower()
            for folded in singletons:
                occurrences = len(re.findall(r'\b' + re.escape(folded) + r'\b', joined_sample))
                if occurrences >= min_count:
                    short_key_counts[folded] = occurrences

    results_by_folded: Dict[str, Dict] = {}
    for folded, count in short_key_counts.most_common():
        if count < min_count:
            continue
        display = short_key_display[folded]
        best_zh = ''
        if folded in short_key_trans and short_key_trans[folded]:
            best_zh = short_key_trans[folded].most_common(1)[0][0]
        results_by_folded[folded] = {
            'term': display,
            'translation': best_zh,
            'count': count,
            'source_mode': 'short_keys',
            'enabled': True,
            'approved': bool(best_zh),
            'note': f'短键值高频术语（<5词，出现 {count} 次）',
        }
        if limit_terms and len(results_by_folded) >= limit_terms:
            break

    if extract_mode in ('long_extract', 'ai_extract'):
        long_counts: Counter = Counter()
        long_display: Dict[str, str] = {}
        for cleaned in all_cleaned_texts:
            words = count_words(cleaned)
            # Extract proper noun phrases (1 to 4 words) from longer entries
            for match in PROPER_PHRASE_RE.finditer(cleaned):
                phrase = ' '.join(match.group(0).split())
                p_words = count_words(phrase)
                if not (1 <= len(p_words) < 5):
                    continue
                folded = phrase.lower()
                if folded in ENGLISH_STOPWORDS or all(w.lower() in ENGLISH_STOPWORDS for w in p_words):
                    continue
                if limit_tokens and len(long_counts) >= limit_tokens and folded not in long_counts:
                    continue
                long_counts[folded] += 1
                if folded not in long_display:
                    long_display[folded] = phrase
            # Also count repeated significant words (>= 4 chars) in longer keys
            if len(words) >= 5:
                for w in words:
                    if len(w) < 4:
                        continue
                    folded = w.lower()
                    if folded in ENGLISH_STOPWORDS:
                        continue
                    if limit_tokens and len(long_counts) >= limit_tokens and folded not in long_counts:
                        continue
                    long_counts[folded] += 1
                    if folded not in long_display or (w[0].isupper() and not long_display[folded][0].isupper()):
                        long_display[folded] = w

        for folded, count in long_counts.most_common():
            if count < min_count:
                continue
            if folded in results_by_folded:
                # Update count if higher
                if count > results_by_folded[folded]['count']:
                    results_by_folded[folded]['count'] = count
                continue
            if limit_terms and len(results_by_folded) >= limit_terms:
                break
            display = long_display[folded]
            best_zh = existing_translations.get(display, '')
            results_by_folded[folded] = {
                'term': display,
                'translation': best_zh,
                'count': count,
                'source_mode': 'long_extract',
                'enabled': True,
                'approved': bool(best_zh),
                'note': f'长键值词云提取（出现 {count} 次）',
            }

    # Sort: short_keys first, then by count descending, then alphabetically
    ordered = sorted(
        results_by_folded.values(),
        key=lambda item: (0 if item['source_mode'] == 'short_keys' else 1, -item['count'], item['term'].lower())
    )
    if limit_terms:
        ordered = ordered[:limit_terms]
    return ordered


def extract_glossary_from_package_pairs(
    english_entries: List[Dict],
    translated_candidates: List[Dict],
    target_language: str = 'zh-CN',
    server_mode: bool = False,
) -> List[Dict]:
    """
    Case 1 of External Import: Directly extract glossary from an exported package or matched EN-ZH pairs,
    prioritizing < 5 word short keys and repeated terms.
    """
    by_key: Dict[str, List[str]] = {}
    for cand in translated_candidates:
        if cand.get('target_language', 'zh-CN') != target_language:
            continue
        text = (cand.get('text') or '').strip()
        if not text:
            continue
        ck = canonical_key(str(cand.get('key', '')))
        if ck:
            by_key.setdefault(ck, []).append(text)

    pair_counts: Counter = Counter()
    pair_display: Dict[str, str] = {}
    pair_zh: Dict[str, Counter] = {}
    limit_terms = SERVER_MAX_GLOSSARY_TERMS if server_mode else None

    for entry in english_entries:
        ck = canonical_key(entry['key'])
        zh_list = by_key.get(ck)
        if not zh_list:
            continue
        en_raw = entry.get('text', '').strip()
        if not en_raw or request.is_token_only(en_raw):
            continue
        cleaned = clean_english_for_glossary(en_raw)
        words = count_words(cleaned)
        if not (1 <= len(words) < 5) or len(cleaned) > 80:
            continue
        zh_clean = zh_list[0].strip()
        if not request.valid_translation(en_raw, zh_clean, target_language):
            continue
        phrase = normalize_phrase(words)
        folded = phrase.lower()
        if folded in ENGLISH_STOPWORDS:
            continue
        pair_counts[folded] += 1
        if folded not in pair_display or (phrase[0].isupper() and not pair_display[folded][0].isupper()):
            pair_display[folded] = phrase
        pair_zh.setdefault(folded, Counter())[zh_clean] += 1

    # Prioritize repeated (<5 words) keys first, then single short keys if under limit
    extracted = []
    for folded, count in sorted(pair_counts.items(), key=lambda x: (-x[1], x[0])):
        zh_best = pair_zh[folded].most_common(1)[0][0]
        extracted.append({
            'term': pair_display[folded],
            'translation': zh_best,
            'count': count,
            'source_mode': 'package_import',
            'enabled': True,
            'approved': True,
            'note': f'导入包直接提取（<5词短键值，出现 {count} 次）',
        })
        if limit_terms and len(extracted) >= limit_terms:
            break
    return extracted


def extract_chinese_repeats_from_yml(
    english_entries: List[Dict],
    yml_candidates: List[Dict],
    game: str,
    config: Optional[Dict] = None,
    demo: bool = False,
    server_mode: bool = False,
    log=None,
) -> List[Dict]:
    """
    Case 2 of External Import: Pure YML file imported -> use AI (or demo fallback) to extract
    repeated Chinese terms and pair them with English keys/terms as a glossary.
    """
    en_by_key: Dict[str, str] = {}
    for entry in english_entries:
        ck = canonical_key(entry['key'])
        if ck and ck not in en_by_key and entry.get('text', '').strip():
            en_by_key[ck] = clean_english_for_glossary(entry['text'])

    zh_counter: Counter = Counter()
    zh_to_en: Dict[str, Counter] = {}
    limit_tokens = SERVER_MAX_UNIQUE_TOKENS if server_mode else None
    limit_terms = SERVER_MAX_GLOSSARY_TERMS if server_mode else None

    for cand in yml_candidates:
        zh_text = request.TOKENS.sub(' ', cand.get('text', '')).strip()
        if not zh_text:
            continue
        ck = canonical_key(str(cand.get('key', '')))
        en_text = en_by_key.get(ck, '')
        en_words = count_words(en_text) if en_text else []
        if 1 <= len(zh_text) <= 12 and (not en_words or len(en_words) < 5):
            if not limit_tokens or len(zh_counter) < limit_tokens or zh_text in zh_counter:
                zh_counter[zh_text] += 1
                if en_text and 1 <= len(en_words) < 5:
                    zh_to_en.setdefault(zh_text, Counter())[normalize_phrase(en_words)] += 1
        for match in CHINESE_PHRASE_RE.finditer(zh_text):
            frag = match.group(0)
            if not limit_tokens or len(zh_counter) < limit_tokens or frag in zh_counter:
                zh_counter[frag] += 1
                if en_text and 1 <= len(en_words) < 5:
                    zh_to_en.setdefault(frag, Counter())[normalize_phrase(en_words)] += 1

    repeated = [(zh, cnt) for zh, cnt in zh_counter.most_common(120) if cnt >= 2]
    if not repeated and yml_candidates:
        # Fallback if small test YML has only 1 occurrence per key
        for cand in yml_candidates[:30]:
            zh_text = request.TOKENS.sub(' ', cand.get('text', '')).strip()
            if zh_text:
                ck = canonical_key(str(cand.get('key', '')))
                en_text = en_by_key.get(ck, '')
                if en_text:
                    zh_to_en.setdefault(zh_text, Counter())[en_text] += 1
                repeated.append((zh_text, 1))

    if demo or not (config and config.get('api_key')):
        results = []
        seen_terms = set()
        for zh, cnt in repeated:
            en_cand = zh_to_en.get(zh, Counter()).most_common(1)
            term = en_cand[0][0] if en_cand else zh
            if term.lower() in seen_terms:
                continue
            seen_terms.add(term.lower())
            results.append({
                'term': term,
                'translation': zh,
                'count': cnt,
                'source_mode': 'yml_ai_import',
                'enabled': True,
                'approved': True,
                'note': f'纯 YML 高频中文提取（出现 {cnt} 次）',
            })
            if limit_terms and len(results) >= limit_terms:
                break
        return results

    # Call AI to refine repeated Chinese segments & pair with English source terms
    if log:
        log('正在调用 AI 从导入的纯 YML 译文中提取高频中文术语表（消耗额外 Token）…')
    request.load_sdk()
    client = request.OpenAI(
        api_key=config['api_key'],
        base_url=config.get('base_url', 'https://api.deepseek.com'),
        timeout=60,
        max_retries=1,
    )
    sample_items = []
    for zh, cnt in repeated[:80]:
        en_cand = zh_to_en.get(zh, Counter()).most_common(1)
        sample_items.append({'chinese': zh, 'count': cnt, 'matched_english': en_cand[0][0] if en_cand else ''})

    prompt = (
        '你是 Paradox 游戏汉化术语提取助手。请从以下导入 YML 文件的高频中文片段及关联英文中，'
        '筛选出真正的游戏专有名词、势力、科技、法案、修正或核心概念术语，剔除普通虚词和残缺片段。\n'
        '仅返回 JSON 数组，每项格式为 {"term": "英文术语(若无英文则填中文词本身)", "translation": "中文标准译名", "count": 出现次数, "note": "AI 提取自纯 YML"}。'
    )
    try:
        response = client.chat.completions.create(
            model=config.get('model', 'deepseek-chat'),
            messages=[
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps(sample_items, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content or '[]'
        parsed = _parse_ai_json_list(content)
        results = []
        for item in parsed:
            term = str(item.get('term', '')).strip()
            translation = str(item.get('translation', '')).strip()
            if term and translation:
                results.append({
                    'term': term[:120],
                    'translation': translation[:120],
                    'count': int(item.get('count', 2) or 2),
                    'source_mode': 'yml_ai_import',
                    'enabled': True,
                    'approved': True,
                    'note': str(item.get('note') or 'AI 从纯 YML 提取高频中文术语')[:120],
                })
                if limit_terms and len(results) >= limit_terms:
                    break
        if results:
            return results
    except Exception as exc:
        if log:
            log(f'AI 提取纯 YML 术语表回退至本地词频匹配（{type(exc).__name__}）')

    # Fallback if AI returned non-JSON or failed
    results = []
    for zh, cnt in repeated[: (limit_terms or 100)]:
        en_cand = zh_to_en.get(zh, Counter()).most_common(1)
        term = en_cand[0][0] if en_cand else zh
        results.append({
            'term': term,
            'translation': zh,
            'count': cnt,
            'source_mode': 'yml_ai_import',
            'enabled': True,
            'approved': True,
            'note': f'纯 YML 高频中文提取（出现 {cnt} 次）',
        })
    return results


def _parse_ai_json_list(text: str) -> List[Dict]:
    text = text.strip()
    match = re.search(r'\[.*\]', text, re.S)
    if match:
        text = match.group(0)
    data = json.loads(text)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def ai_extract_and_approve_glossary(
    candidates: List[Dict],
    sample_entries: List[Dict],
    game: str,
    target_language: str = 'zh-CN',
    config: Optional[Dict] = None,
    demo: bool = False,
    ai_extract: bool = False,
    ai_approve: bool = False,
    server_mode: bool = False,
    log=None,
) -> List[Dict]:
    """
    Use AI to extract new terms from sample entries (when ai_extract=True)
    and/or automatically approve and translate candidate terms (when ai_approve=True).
    """
    limit_terms = SERVER_MAX_GLOSSARY_TERMS if server_mode else None
    if demo:
        demo_dict = {
            'political power': '政治点数',
            'new beginning': '新的开始',
            'a new beginning': '新的开始',
            'galactic empire': '银河帝国',
            'stability': '稳定度',
            'war support': '战争支持度',
        }
        results = []
        for item in candidates:
            term = item['term']
            zh = item.get('translation') or demo_dict.get(term.lower(), f'【术语】{term}')
            results.append({
                **item,
                'translation': zh if (ai_approve or ai_extract or item.get('translation')) else '',
                'approved': bool(ai_approve or ai_extract or item.get('approved')),
                'source_mode': 'ai_extract' if ai_extract else item.get('source_mode', 'short_keys'),
                'note': ('AI 提取（注意：可能消耗较多 Token）' if ai_extract else item.get('note', ''))
                        + (' · AI 已自动审批' if ai_approve else ''),
            })
        return results[:limit_terms] if limit_terms else results

    config = config or {}
    api_key = config.get('api_key')
    if not api_key:
        if ai_extract or ai_approve:
            raise ValueError('使用 AI 提取或 AI 自动审批术语表前，请先配置有效的 API Key')
        return candidates

    request.load_sdk()
    client = request.OpenAI(
        api_key=api_key,
        base_url=config.get('base_url', 'https://api.deepseek.com'),
        timeout=90,
        max_retries=1,
    )
    model = config.get('model', 'deepseek-chat')
    lang_label = {'zh-CN': '简体中文', 'zh-TW': '繁體中文', 'ru': '俄语 (Русский)', 'ko': '韩语 (한국어)', 'ja': '日语 (日本語)'}.get(target_language, '简体中文')

    payload = {
        'candidates': [{'term': c['term'], 'count': c['count'], 'translation': c.get('translation', '')} for c in candidates[:120]],
    }
    if ai_extract:
        # Include sample sentences for AI to discover additional domain terms
        sample_texts = []
        for row in sample_entries[:80]:
            cleaned = clean_english_for_glossary(row.get('text', ''))
            if cleaned and len(cleaned) <= 240:
                sample_texts.append(cleaned)
        payload['sample_texts'] = sample_texts

    if log:
        log(f"正在调用 AI ({model}) {'提取并' if ai_extract else ''}审批术语表（注意：AI 提取与审批会消耗额外 Token）…")

    system_prompt = (
        f"你是 Paradox 游戏本地化术语专家。目标语言：{lang_label}。\n"
        "任务：审查候选高频词云与样本文本，筛选出真正需要统一译名的游戏专有名词、国家/势力、理念、科技、事件修正或核心机制术语，"
        "剔除普通英语虚词或无固定译名的日常短语，并为每个保留的术语提供准确、地道的目标语言译名。\n"
        '请仅输出 JSON 数组，格式为：[{"term": "English Term", "translation": "目标语言译名", "count": 出现次数, "note": "简短说明"}]。'
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
            ],
        )
        parsed = _parse_ai_json_list(response.choices[0].message.content or '[]')
        if parsed:
            merged: Dict[str, Dict] = {}
            for item in parsed:
                term = str(item.get('term', '')).strip()
                trans = str(item.get('translation', '')).strip()
                if not term or not trans:
                    continue
                folded = term.lower()
                merged[folded] = {
                    'term': term[:120],
                    'translation': trans[:120],
                    'count': int(item.get('count', 2) or 2),
                    'source_mode': 'ai_extract' if ai_extract else 'short_keys',
                    'enabled': True,
                    'approved': True,
                    'note': str(item.get('note') or ('AI 提取并审批（消耗额外 Token）' if ai_extract else 'AI 自动审批'))[:120],
                }
            # Retain any existing pre-translated candidates not covered if not ai_approve
            for orig in candidates:
                folded = orig['term'].lower()
                if folded not in merged and not ai_approve:
                    merged[folded] = orig
            result_list = sorted(merged.values(), key=lambda x: (-x['count'], x['term'].lower()))
            return result_list[:limit_terms] if limit_terms else result_list
    except Exception as exc:
        if log:
            log(f'AI 术语表处理异常（{type(exc).__name__}），保留词云扫描结果')
        if ai_extract:
            raise ValueError(f'AI 提取术语表失败：{type(exc).__name__}') from exc
    return candidates[:limit_terms] if limit_terms else candidates


def format_glossary_prompt_for_batch(batch_texts: List[str], glossary: Dict[str, str], language: str = 'zh-CN') -> str:
    """Build a compact system-prompt addendum containing only glossary terms appearing in `batch_texts`."""
    if not glossary or not batch_texts:
        return ''
    combined = '\n'.join(batch_texts).lower()
    matched = []
    # Sort longer terms first so multi-word phrases take precedence
    for term, translation in sorted(glossary.items(), key=lambda kv: (-len(kv[0]), kv[0].lower())):
        if not term or not translation:
            continue
        t_low = term.lower()
        if t_low in combined:
            matched.append(f'- {term} = {translation}')
            if len(matched) >= 80:
                break
    if not matched:
        return ''
    headers = {
        'zh-CN': '\n\n【本批术语表（若原文出现以下术语，请严格采用指定译名以保持全 Mod 统一）】：\n',
        'zh-TW': '\n\n【本批術語表（若原文出現以下術語，請嚴格採用指定譯名以保持全 Mod 統一）】：\n',
        'ru': '\n\n[Глоссарий для этой партии (строго используйте указанные переводы терминов)]:\n',
        'ko': '\n\n[이번 배치 용어집 (다음 용어가 등장하면 지정된 번역을 엄격히 사용하세요)]:\n',
        'ja': '\n\n【用語集（原文に以下の用語が含まれる場合、指定された訳語を厳密に使用してください）】：\n',
    }
    return headers.get(language, headers['zh-CN']) + '\n'.join(matched)


class GlossaryManager:
    """Manage per-Mod glossary terms and workflow preferences in SQLite."""

    def __init__(self, service):
        self.service = service
        with service.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS mod_glossary (
                    mod_id TEXT NOT NULL,
                    term TEXT NOT NULL,
                    translation TEXT NOT NULL DEFAULT '',
                    count INTEGER NOT NULL DEFAULT 1,
                    source_mode TEXT NOT NULL DEFAULT 'short_keys',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    approved INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(mod_id, term)
                );
                CREATE TABLE IF NOT EXISTS mod_glossary_settings (
                    mod_id TEXT PRIMARY KEY,
                    workflow_mode TEXT NOT NULL DEFAULT 'fast',
                    extract_mode TEXT NOT NULL DEFAULT 'short_keys',
                    approval_mode TEXT NOT NULL DEFAULT 'manual',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            ''')

    def settings(self, mod_id: str) -> Dict:
        with self.service.connect() as db:
            row = db.execute(
                'SELECT workflow_mode, extract_mode, approval_mode FROM mod_glossary_settings WHERE mod_id=?',
                (mod_id,)
            ).fetchone()
            total = db.execute('SELECT COUNT(*) FROM mod_glossary WHERE mod_id=?', (mod_id,)).fetchone()[0]
            active = db.execute(
                "SELECT COUNT(*) FROM mod_glossary WHERE mod_id=? AND enabled=1 AND trim(translation)<>''",
                (mod_id,)
            ).fetchone()[0]
        return {
            'workflow_mode': row[0] if row and row[0] in WORKFLOW_MODES else 'fast',
            'extract_mode': row[1] if row and row[1] in EXTRACT_MODES else 'short_keys',
            'approval_mode': row[2] if row and row[2] in APPROVAL_MODES else 'manual',
            'total_terms': total,
            'active_terms': active,
            'server_memory_limited': bool(getattr(self.service, 'server_mode', False)),
            'limits': {
                'max_scan_mb': SERVER_MAX_SCAN_BYTES // (1024 * 1024),
                'max_glossary_mb': SERVER_MAX_GLOSSARY_BYTES // (1024 * 1024),
                'max_entries': SERVER_MAX_SCAN_ENTRIES,
                'max_terms': SERVER_MAX_GLOSSARY_TERMS,
            } if getattr(self.service, 'server_mode', False) else None,
        }

    def save_settings(self, mod_id: str, workflow_mode: Optional[str] = None,
                      extract_mode: Optional[str] = None, approval_mode: Optional[str] = None) -> Dict:
        current = self.settings(mod_id)
        wf = workflow_mode if workflow_mode is not None else current['workflow_mode']
        ex = extract_mode if extract_mode is not None else current['extract_mode']
        ap = approval_mode if approval_mode is not None else current['approval_mode']
        if wf not in WORKFLOW_MODES:
            raise ValueError('翻译模式无效（请选择快速模式或术语表模式）')
        if ex not in EXTRACT_MODES:
            raise ValueError('术语提取方式无效')
        if ap not in APPROVAL_MODES:
            raise ValueError('术语审批方式无效')
        with self.service.connect() as db:
            db.execute(
                '''INSERT OR REPLACE INTO mod_glossary_settings
                   (mod_id, workflow_mode, extract_mode, approval_mode, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (mod_id, wf, ex, ap)
            )
        return self.settings(mod_id)

    def list_terms(self, mod_id: str) -> List[Dict]:
        with self.service.connect() as db:
            rows = db.execute(
                '''SELECT term, translation, count, source_mode, enabled, approved, note
                   FROM mod_glossary WHERE mod_id=?
                   ORDER BY enabled DESC, approved DESC, count DESC, lower(term) ASC''',
                (mod_id,)
            ).fetchall()
        return [
            {
                'term': r[0],
                'translation': r[1],
                'count': r[2],
                'source_mode': r[3],
                'enabled': bool(r[4]),
                'approved': bool(r[5]),
                'note': r[6],
            }
            for r in rows
        ]

    def active_glossary_map(self, mod_id: str) -> Dict[str, str]:
        with self.service.connect() as db:
            rows = db.execute(
                '''SELECT term, translation FROM mod_glossary
                   WHERE mod_id=? AND enabled=1 AND trim(translation)<>''
                   ORDER BY length(term) DESC''',
                (mod_id,)
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def replace_terms(self, mod_id: str, terms: List[Dict], merge: bool = True) -> List[Dict]:
        if not isinstance(terms, list):
            raise ValueError('术语表数据格式错误')
        server_mode = bool(getattr(self.service, 'server_mode', False))
        if server_mode and len(terms) > SERVER_MAX_GLOSSARY_TERMS:
            terms = terms[:SERVER_MAX_GLOSSARY_TERMS]
        existing_map = {t['term'].lower(): t for t in self.list_terms(mod_id)} if merge else {}
        for item in terms:
            if not isinstance(item, dict):
                continue
            term = str(item.get('term', '')).strip()
            if not term or len(term) > 160 or any(c in term for c in '\r\n\x00'):
                continue
            translation = str(item.get('translation', '')).strip()
            if len(translation) > 240 or any(c in translation for c in '\r\n\x00'):
                continue
            folded = term.lower()
            prev = existing_map.get(folded, {})
            # Preserve existing manual translation unless overwritten
            final_trans = translation if translation else prev.get('translation', '')
            existing_map[folded] = {
                'term': term,
                'translation': final_trans,
                'count': max(1, int(item.get('count', prev.get('count', 1)) or 1)),
                'source_mode': str(item.get('source_mode') or prev.get('source_mode') or 'short_keys')[:40],
                'enabled': bool(item.get('enabled', prev.get('enabled', True))),
                'approved': bool(item.get('approved', prev.get('approved', bool(final_trans)))),
                'note': str(item.get('note', prev.get('note', '')))[:200],
            }
        ordered = sorted(existing_map.values(), key=lambda x: (-x['count'], x['term'].lower()))
        if server_mode and len(ordered) > SERVER_MAX_GLOSSARY_TERMS:
            ordered = ordered[:SERVER_MAX_GLOSSARY_TERMS]
        with self.service.connect() as db:
            db.execute('DELETE FROM mod_glossary WHERE mod_id=?', (mod_id,))
            db.executemany(
                '''INSERT INTO mod_glossary
                   (mod_id, term, translation, count, source_mode, enabled, approved, note, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                [
                    (
                        mod_id,
                        t['term'],
                        t['translation'],
                        t['count'],
                        t['source_mode'],
                        int(t['enabled']),
                        int(t['approved']),
                        t['note'],
                    )
                    for t in ordered
                ]
            )
        return self.list_terms(mod_id)

    def scan_and_extract(self, item: Dict, extract_mode: str = 'short_keys',
                         approval_mode: str = 'manual', min_count: int = 2,
                         config: Optional[Dict] = None) -> Dict:
        """Scan Mod English files and extract glossary / word-cloud terms."""
        sources = self.service.original_sources(item)
        check_server_memory_limit(self.service, sources=sources, stage='术语扫描')
        source_rows = entries(sources, item['game'], strict=False)
        check_server_memory_limit(self.service, entries_count=len(source_rows), stage='术语扫描')

        # Collect existing translations from SQLite cache to pre-fill known short keys
        existing_trans: Dict[str, str] = {}
        with self.service.connect() as db:
            for src_file, key, src_hash, zh in db.execute(
                'SELECT source_file, entry_key, source_hash, chinese FROM translation_entries WHERE mod_id=?',
                (item['id'],)
            ):
                existing_trans[f'{src_file}|{key}|{src_hash}'] = zh
        en_to_zh: Dict[str, str] = {}
        for row in source_rows:
            en_text = row.get('text', '').strip()
            if not en_text:
                continue
            zh = existing_trans.get(f"{row['source_file']}|{row['key']}|{digest(en_text)}")
            if zh:
                en_to_zh[en_text] = zh
                cleaned = clean_english_for_glossary(en_text)
                if cleaned:
                    en_to_zh[cleaned] = zh

        candidates = extract_glossary_candidates(
            source_rows,
            existing_translations=en_to_zh,
            extract_mode=extract_mode,
            min_count=min_count,
            server_mode=bool(getattr(self.service, 'server_mode', False)),
        )
        # If small Mod (like demo Mod with 2 lines) has no >=2 repeated short keys, include <5 word keys with min_count=1 so users can still inspect/approve them
        if not candidates and source_rows:
            candidates = extract_glossary_candidates(
                source_rows,
                existing_translations=en_to_zh,
                extract_mode=extract_mode,
                min_count=1,
                server_mode=bool(getattr(self.service, 'server_mode', False)),
            )

        use_ai_extract = (extract_mode == 'ai_extract')
        use_ai_approve = (approval_mode == 'ai_approve')
        if use_ai_extract or use_ai_approve:
            candidates = ai_extract_and_approve_glossary(
                candidates=candidates,
                sample_entries=source_rows,
                game=item['game'],
                target_language=self.service.target_language,
                config=config or self.service.config(),
                demo=self.service.demo,
                ai_extract=use_ai_extract,
                ai_approve=use_ai_approve,
                server_mode=bool(getattr(self.service, 'server_mode', False)),
                log=self.service.log,
            )

        saved = self.replace_terms(item['id'], candidates, merge=True)
        settings = self.save_settings(item['id'], workflow_mode='glossary',
                                      extract_mode=extract_mode, approval_mode=approval_mode)
        self.service.log(
            f"{item['title']}：术语表扫描完成（模式：{extract_mode}，审批：{approval_mode}），共 {len(saved)} 个术语，已生效 {settings['active_terms']} 个"
        )
        return {'terms': saved, 'settings': settings}
