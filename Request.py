#print(findrule("st"))
import json
from pathlib import Path
import concurrent.futures

from openai import OpenAI

APP_KEY = '4bcdbd21d0636955'
APP_SECRET = '6FibaBh0UcYkSwBKyWtFA11pn6qqvsKK' 

_RULES_CACHE = None

def findrule(game):
    """
    仅在首次调用时读取 rules.json，后续直接复用缓存，避免频繁 IO。
    """
    global _RULES_CACHE
    if _RULES_CACHE is None:
        rules_path = Path("rules.json")
        with rules_path.open("r", encoding="utf-8") as fi:
            _RULES_CACHE = json.load(fi)
    return _RULES_CACHE[game]
#print(findrule("st"))
def request_deepseek_batch(tran, game, al_cnt, all_len, batch_size=15, pool_size=30):
    """
    支持批量合并翻译：将多条文本合并成一批进行翻译，然后拆分回原格式
    :param tran: 字符串列表
    :param game: 游戏名称，用于获取规则
    :param al_cnt: 已翻译数量
    :param all_len: 总数量
    :param batch_size: 每批合并的文本数量，默认5
    :param pool_size: 线程池最大并发数，默认20
    :return: 翻译结果列表
    client = OpenAI(api_key="sk-jkG33jX6jy8wtqfi2yAjC41vZ1ZgDjffN6Mqjo5HLRp9Gt9j", base_url="https://yinli.one/v1")
    """
    client = OpenAI(api_key="sk-e85d7bea05cd45438fe258f807ec79d8", base_url="https://api.deepseek.com")
    
    # 分隔符，用于合并和拆分文本
    SEPARATOR = "\n---SEPARATOR---\n"
    
    def _translate_batch_(batch_text):
        """翻译一批合并的文本"""
        messages = [
            {"role": "system", "content": findrule(game)},
            {"role": "user", "content": batch_text}
        ]
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages
        )
        return response.choices[0].message.content
    
    # 将文本列表按 batch_size 分组并合并
    batches = []
    batch_indices = []  # 记录每批对应的原始索引范围
    
    for i in range(0, len(tran), batch_size):
        batch = tran[i:i+batch_size]
        batch_text = SEPARATOR.join(batch)
        batches.append(batch_text)
        batch_indices.append((i, min(i+batch_size, len(tran))))
    
    # 使用线程池并行处理批次
    results = [None] * len(tran)
    cnt = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
        future_to_batch_idx = {}
        for batch_idx, batch_text in enumerate(batches):
            future = executor.submit(_translate_batch_, batch_text)
            future_to_batch_idx[future] = batch_idx
        
        # 按完成顺序收集结果并拆分
        for future in concurrent.futures.as_completed(future_to_batch_idx):
            batch_idx = future_to_batch_idx[future]
            start_idx, end_idx = batch_indices[batch_idx]
            
            try:
                batch_result = future.result()
                # 按分隔符拆分翻译结果
                translated_parts = batch_result.split(SEPARATOR)
                
                # 如果拆分后的数量不匹配，尝试其他方式处理
                if len(translated_parts) != (end_idx - start_idx):
                    # 如果拆分失败，尝试按行拆分或使用原文本
                    print(f"警告：批次 {batch_idx} 拆分结果数量不匹配，使用备用方案")
                    # 尝试按更简单的分隔符拆分
                    if "\n---\n" in batch_result:
                        translated_parts = batch_result.split("\n---\n")
                    else:
                        # 如果还是不行，将整个结果作为第一个，其余使用原文本
                        translated_parts = [batch_result] + tran[start_idx+1:end_idx]
                
                # 将拆分后的结果填充到对应位置
                for j, part in enumerate(translated_parts):
                    if start_idx + j < end_idx:
                        results[start_idx + j] = part.strip()
                        cnt += 1
                        print(f"{al_cnt+cnt}/{all_len}")
                
            except Exception as e:
                print(f"翻译批次 {batch_idx} 出错: {e}")
                # 出错时使用原文本
                for j in range(start_idx, end_idx):
                    results[j] = tran[j]
                    cnt += 1
                    print(f"{al_cnt+cnt}/{all_len}")
    
    # 填充任何未处理的项（理论上不应该发生）
    for i in range(len(results)):
        if results[i] is None:
            results[i] = tran[i]
    
    return results
# 网易有道智云翻译服务api调用demo
# api接口: https://openapi.youdao.com/api