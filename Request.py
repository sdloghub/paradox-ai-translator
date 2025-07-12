#print(findrule("st"))
from time import sleep
import requests,json
from openai import OpenAI
import concurrent.futures

APP_KEY = '4bcdbd21d0636955'
APP_SECRET = '6FibaBh0UcYkSwBKyWtFA11pn6qqvsKK'

def findrule(game):
    fi=open("./Rule.txt","r",encoding="utf-8")
    rules=fi.readlines()
    for x in rules:
        tpoint=x.find(game+":")
        if tpoint!=-1:
            tpoint=x.find(":")
            return x[tpoint+1:]
    return ""

def request_deepseek(tran, game,al_cnt,all_len):
    """
    支持单个字符串或字符串列表的翻译
    :param strr: 单个字符串或字符串列表
    :param game: 游戏名称，用于获取规则
    :param max_workers: 最大并发数，默认5
    :return: 单个字符串的翻译结果或字符串列表的翻译结果列表
    """
    client = OpenAI(api_key="sk-e85d7bea05cd45438fe258f807ec79d8", base_url="https://api.deepseek.com")
    def _translate_(s):
        messages = [
            {"role": "system", "content": findrule(game)},
            {"role": "user", "content": s}
        ]
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages
        )
        return response.choices[0].message.content

    # 使用线程池并行处理
    results = []
    cnt=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        future_to_str = {executor.submit(_translate_, s): s for s in tran}
        for future in concurrent.futures.as_completed(future_to_str):
            try:
                cnt+=1
                result = future.result()
                results.append(result)
                print(f"{al_cnt+cnt}/{all_len}")
            except Exception as e:
                print(f"翻译请求出错: {e}")
                results.append("")  # 出错时返回空字符串

    # 如果输入是单个字符串，则返回单个结果；否则返回列表
    return results
# 网易有道智云翻译服务api调用demo
# api接口: https://openapi.youdao.com/api