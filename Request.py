#print(findrule("st"))
import json
from pathlib import Path
import concurrent.futures

from openai import OpenAI, APIConnectionError, APITimeoutError
import logging
import time
import os
import re
from collections import Counter


_RULES_CACHE = None

def findrule(game):
    """
    仅在首次调用时读取 rules.json，后续直接复用缓存，避免频繁 IO。
    """
    global _RULES_CACHE
    if _RULES_CACHE is None:
        rules_path = Path(__file__).resolve().parent / "rules.json"
        with rules_path.open("r", encoding="utf-8") as fi:
            _RULES_CACHE = json.load(fi)
    return _RULES_CACHE[game]
#print(findrule("st"))
# Match script variables, game icons, colour/format tokens and literal escapes.
TOKENS = re.compile(r'\$[^$\r\n]*\$|\[[^\]\r\n]*\]|£[^£\s]+£?|@[A-Za-z0-9_]+!?|§.|\#(?:[A-Za-z][A-Za-z0-9_]*|!)|\\(?:[nrt"\\])')

def valid_translation(original, translated):
    return (isinstance(translated, str)
            and (bool(translated.strip()) or not original.strip())
            and "---SEPARATOR---" not in translated
            and Counter(TOKENS.findall(original)) == Counter(TOKENS.findall(translated)))

def request_deepseek_batch(tran, game, al_cnt, all_len, batch_size=25, pool_size=40):
    """返回与输入顺序一致的 {text, success, error}；失败项保留原文。"""
    if batch_size < 1 or pool_size < 1:
        raise ValueError("batch_size 和 pool_size 必须大于零")
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("请设置 DEEPSEEK_API_KEY 环境变量")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", max_retries=0)
    rule = findrule(game)
    separator = "\n---SEPARATOR---\n"

    def failed(original, error):
        return {"text": original, "success": False, "error": error}

    def translate_text(text):
        # SDK 重试关闭，由这里控制：首次请求加最多三次临时错误重试。
        for attempt in range(4):
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "system", "content": rule},
                              {"role": "user", "content": text}],
                )
                content = response.choices[0].message.content
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("模型返回空文本")
                return content
            except Exception as error:
                status = getattr(error, "status_code", None)
                transient = isinstance(error, (APIConnectionError, APITimeoutError)) or status in (408, 409, 429) or (isinstance(status, int) and status >= 500)
                if not transient or attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    def translate_batch(batch):
        try:
            content = translate_text(separator.join(batch))
        except Exception as error:
            logging.warning("翻译请求失败，条目保留原文且不缓存 (%s)", type(error).__name__)
            return [failed(text, type(error).__name__) for text in batch]
        parts = content.split(separator)
        if len(parts) == len(batch) and all(valid_translation(original, part.strip()) for part, original in zip(parts, batch)):
            return [{"text": part.strip(), "success": True, "error": None} for part in parts]
        logging.warning("批次分隔符数量或内容不正确，改为逐条翻译")
        results = []
        for original in batch:
            try:
                for validation_attempt in range(3):
                    text = translate_text(original).strip()
                    if valid_translation(original, text):
                        break
                else:
                    raise ValueError("变量或格式代码校验失败")
                results.append({"text": text, "success": True, "error": None})
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
            print(f"已处理 {al_cnt + completed}/{all_len}")
    return results
