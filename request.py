#print(findrule("st"))
import json
from pathlib import Path
import concurrent.futures

# SDK imports are deferred until a real API request or packaged self-test.
OpenAI = None
class APIConnectionError(Exception):
    pass
class APITimeoutError(Exception):
    pass

def load_sdk():
    global OpenAI, APIConnectionError, APITimeoutError
    if OpenAI is not None:
        return
    try:
        from openai import OpenAI as sdk_client, APIConnectionError as sdk_connection, APITimeoutError as sdk_timeout
    except ImportError as error:
        raise RuntimeError('缺少 openai 依赖，请运行启动脚本或安装 requirements.txt') from error
    OpenAI, APIConnectionError, APITimeoutError = sdk_client, sdk_connection, sdk_timeout

import logging
import time
import os
import re
from collections import Counter


_RULES_CACHE = None

def findrule(game, language=None):
    from localization import normalize, current_language
    language = normalize(language or current_language())
    """
    仅在首次调用时读取 rules.json，后续直接复用缓存，避免频繁 IO。
    """
    global _RULES_CACHE
    if _RULES_CACHE is None:
        rules_path = Path(__file__).resolve().parent / "rules.json"
        with rules_path.open("r", encoding="utf-8") as fi:
            _RULES_CACHE = json.load(fi)
    if 'common' in _RULES_CACHE:
        context = _RULES_CACHE.get('games', {}).get(game, {})
        common = _RULES_CACHE.get('languages', {}).get(language, {}).get('common', _RULES_CACHE['common'])
        guidance = _RULES_CACHE.get('languages', {}).get(language, {}).get('games', {}).get(game, context.get('guidance', ''))
        return (common + {'zh-CN':'\n\n当前游戏：', 'zh-TW':'\n\n目前遊戲：', 'ru':'\n\nИгра: '}[language] + context.get('name', game)
                + '\n' + guidance)
    return _RULES_CACHE[game]
#print(findrule("st"))
# Match script variables, game icons, colour/format tokens and literal escapes.
TOKENS = re.compile(r'\$[^$\r\n]*\$|\[[^\]\r\n]*\]|£[^£\s]+£?|@[A-Za-z0-9_]+!?|§(?:[^\r\n]|$)|\#(?:[A-Za-z][A-Za-z0-9_]*|!)|\\+(?:[nrt"]|\\)')

def output_text(text):
    """The exact value the YML parser will read after publication."""
    text = text.replace('\n', r'\n')
    return re.sub(r'(?<!\\)((?:\\\\)*)"', r'\1\\"', text)

def protect_tokens(text):
    """Protect even malformed source markers; the model must not repair them."""
    import secrets
    prefix = 'WT' + secrets.token_hex(8) + '_'
    tokens = {}
    def mask(match):
        placeholder = '⟦' + prefix + str(len(tokens)) + '⟧'
        tokens[placeholder] = match.group()
        return placeholder
    return TOKENS.sub(mask, text), tokens

class ProtectedTokenError(ValueError):
    pass

class LegalComplianceError(ValueError):
    pass

HOI4_ILLEGAL_ABORT_TOKEN = '__ILLEGAL_CONTENT_ABORT__'
HOI4_PROHIBITED_PATTERN = re.compile(
    r'(?:__ILLEGAL_CONTENT_ABORT__|台独|台湾独立|台湾共和国|藏独|西藏独立|疆独|东突厥斯坦|港独|香港独立|'
    r'分裂中国|推翻中国共产党|打倒中国共产党|颠覆中华人民共和国|法轮功|法轮大法|真善忍好|三退保平安)',
    re.I
)

def audit_hoi4_compliance(texts):
    if isinstance(texts, str):
        texts = [texts]
    for item in texts:
        if isinstance(item, str) and HOI4_PROHIBITED_PATTERN.search(item):
            raise LegalComplianceError('审核未通过：检测到钢铁雄心4模组包含违反中国法律法规的内容，已直接终止并退出翻译任务')

def restore_tokens(text, tokens):
    placeholders = re.findall(r'⟦WT[a-f0-9]+_\d+⟧', text)
    if Counter(placeholders) != Counter(tokens.keys()):
        raise ProtectedTokenError('受保护的变量占位符缺失、重复或被修改')
    for placeholder, original in tokens.items():
        text = text.replace(placeholder, original)
    return text

def validation_error(original, translated, language=None):
    from localization import current_language
    language = language or current_language()
    pattern = r'[\u0400-\u052f]' if language == 'ru' else r'[\u3400-\u9fff]'
    if not is_token_only(original) and not re.search(pattern, translated):
        return '未返回目标语言译文，不能将英文回复作为完成缓存'
    before, after = Counter(TOKENS.findall(original)), Counter(TOKENS.findall(output_text(translated)))
    details = []
    for label, tokens in (('缺少', before - after), ('新增', after - before)):
        if tokens:
            details.append(label + '格式标记 ' + repr(list(tokens.elements())[:8]))
    return '；'.join(details) or '返回空文本、分隔符或不支持的换行'

def is_token_only(text):
    """若文本为空白，或剔除全部游戏标识符后不再包含任何英文字母，则视为仅剩标识符/已翻译。"""
    return not isinstance(text, str) or not re.search(r'[A-Za-z]', TOKENS.sub('', text))

def valid_translation(original, translated, language=None):
    from localization import current_language
    language = language or current_language()
    if not isinstance(original, str) or not isinstance(translated, str):
        return False
    if not original.strip():
        return translated == original
    return (bool(translated.strip())
            and "---SEPARATOR---" not in translated
            and (is_token_only(original) or bool(re.search(r'[\u0400-\u052f]' if language == 'ru' else r'[\u3400-\u9fff]', translated)))
            and Counter(TOKENS.findall(original)) == Counter(TOKENS.findall(output_text(translated))))

def request_deepseek_batch(tran, game, al_cnt, all_len, batch_size=25, pool_size=40, config=None, progress=None):
    """返回与输入顺序一致的 {text, success, error}；失败项保留原文。"""
    if batch_size < 1 or pool_size < 1:
        raise ValueError("batch_size 和 pool_size 必须大于零")
    if not tran:
        return []
    if game == 'hoi4':
        audit_hoi4_compliance(tran)
    translatable = [index for index, text in enumerate(tran) if not is_token_only(text)]
    if len(translatable) != len(tran):
        # 空白或仅含标识符/数字/标点的条目直接视为已翻译，跳过 API 送审并原样保留全部标识符。
        results = [{"text": text, "success": True, "error": None} for text in tran]
        if translatable:
            translated = request_deepseek_batch([tran[index] for index in translatable], game,
                al_cnt + len(tran) - len(translatable), all_len, batch_size, pool_size, config, progress)
            for index, result in zip(translatable, translated):
                results[index] = result
        return results
    config = config or {}
    api_key = config.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("请在设置中填写 API Key")
    load_sdk()
    client = OpenAI(api_key=api_key, base_url=config.get("base_url", "https://api.deepseek.com"),
                    timeout=90, max_retries=0)
    model = config.get("model", "deepseek-chat")
    language = config.get('target_language', 'zh-CN')
    rule = findrule(game, language)
    separator = "\n---SEPARATOR---\n"

    def failed(original, error):
        return {"text": original, "success": False, "error": error}

    def translate_text(text, protected=False):
        # SDK 重试关闭，由这里控制：首次请求加最多三次临时错误重试。
        for attempt in range(4):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": rule + (
                        '\n本条中的 ⟦WT…⟧ 是程序保护的游戏标记。必须逐字保留每个占位符各一次，'
                        '不要翻译、删除、复制或修复它们。仅翻译其余正文，仅返回译文。' if protected else '')},
                              {"role": "user", "content": text}],
                )
                content = response.choices[0].message.content
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("模型返回空文本")
                if game == 'hoi4':
                    audit_hoi4_compliance(content)
                return content
            except LegalComplianceError:
                raise
            except Exception as error:
                status = getattr(error, "status_code", None)
                transient = isinstance(error, (APIConnectionError, APITimeoutError)) or status in (408, 409, 429) or (isinstance(status, int) and status >= 500)
                if not transient or attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    def translate_batch(batch):
        try:
            content = translate_text(separator.join(batch))
        except LegalComplianceError:
            raise
        except Exception as error:
            logging.warning("翻译请求失败，条目保留原文且不缓存 (%s)", type(error).__name__)
            return [failed(text, type(error).__name__) for text in batch]
        parts = content.split(separator)
        if len(parts) == len(batch) and all(valid_translation(original, part.strip(), language) for part, original in zip(parts, batch)):
            if game == 'hoi4':
                audit_hoi4_compliance(parts)
            return [{"text": output_text(part.strip()), "success": True, "error": None} for part in parts]
        logging.warning("批次分隔符数量或内容不正确，改为逐条翻译")
        results = []
        for original in batch:
            try:
                for validation_attempt in range(3):
                    if validation_attempt:
                        masked, tokens = protect_tokens(original)
                        try:
                            text = restore_tokens(translate_text(masked, protected=True).strip(), tokens)
                        except ProtectedTokenError:
                            text = ''
                            continue
                    else:
                        text = translate_text(original).strip()
                    if valid_translation(original, text, language):
                        break
                else:
                    results.append(failed(original, validation_error(original, text, language)))
                    continue
                if game == 'hoi4':
                    audit_hoi4_compliance(text)
                results.append({"text": output_text(text), "success": True, "error": None})
            except LegalComplianceError:
                raise
            except Exception as error:
                logging.warning("逐条翻译失败，保留原文且不缓存 (%s)", type(error).__name__)
                results.append(failed(original, type(error).__name__))
        return results

    results = [None] * len(tran)
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
        futures = {executor.submit(translate_batch, tran[i:i + batch_size]): i
                   for i in range(0, len(tran), batch_size)}
        for future in concurrent.futures.as_completed(futures):
            start = futures[future]
            batch_results = future.result()
            results[start:start + len(batch_results)] = batch_results
            completed += len(batch_results)
            message = f"已处理 {al_cnt + completed}/{all_len}"
            print(message)
            if progress:
                progress(message)
    return results
