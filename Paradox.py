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

class Paradox_data:
    def __init__(self,key_w,word,vis):
        self.key_w=key_w
        self.word=word
        self.vis=vis
     
def check(str):
    if str.find(".yml")==-1: 
        return 1
    elif str.find("l_english.yml")!=-1:
        return 2
    else:
        return 0
def clean(dir_name):
    """
    递归删除目录，调用方可能传入不存在的路径，因此先校验再处理。
    """
    if not os.path.isdir(dir_name):
        return
    for name in os.listdir(dir_name):
        full_path = os.path.join(dir_name, name)
        if os.path.isdir(full_path):
            clean(full_path)
        else:
            os.remove(full_path)
    os.rmdir(dir_name)
def extract(path,mde):
    """
    流式解析 localisation/already 文件，避免一次性读入超大文件。
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).touch(exist_ok=True)
    pdata=[]
    try:
        with open(path,"r",encoding="utf-8") as fo:
            for raw_line in fo:
                #print(raw_line)
                strin=raw_line.lstrip()
                find_length=strin.find("\"")
                skipp=(strin.lstrip()).find("#")
                # skipp:如果#在5个字符内，则跳过
                if (skipp<=5 and skipp!=-1) or find_length==-1:
                    #print(raw_line)
                    continue
                start_l=find_length+1
                end_l=len(strin)-2
                if find_length!=-1:
                    # 确保 end_l 有效且大于 start_l，避免索引错误
                    if end_l <= start_l or end_l < 0 or end_l >= len(strin):
                        continue
                    if mde=="eu4":
                        original_text = special_unescape(strin[start_l:end_l],True,True)
                        #print(original_text)
                        pdata.append((strin[0:find_length],original_text))
                    else:
                        original_text = strin[start_l:end_l]
                        #print(original_text)
                        pdata.append((strin[0:find_length],original_text))
    except (FileNotFoundError, IOError, UnicodeDecodeError) as e:
        print(f"读取文件 {path} 时出错: {e}")
        return []
    return pdata
def outputs(local_path: str, dic: Dict[str, Paradox_data], mde: str):
    src_path = "./localisation/"+local_path
    dst_path = "./chn/"+local_path
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(src_path,"r",encoding="utf-8") as fo, open(dst_path,"w",encoding="utf-8") as fi:
        for raw_line in fo:
            strin=raw_line.lstrip()
            find_length=strin.find("\"")
            skipp=(strin.lstrip()).find("#")
            if (skipp<=5 and skipp!=-1) or find_length==-1:
                write_line = raw_line
                if "l_english" in raw_line and mde!="eu4":
                    write_line=raw_line.replace("l_english:","l_simp_chinese:")
                fi.write(write_line)
                continue
            ori=strin[0:find_length]
            pdata = dic.get(ori)
            if pdata is None:
                # 字典缺失时保留原文，避免 KeyError 直接中断
                fi.write(raw_line)
                continue
            if mde=="eu4":
                new_line=" "+ori+"\""+special_escape(pdata.word.replace("\n","\\n")+"\"\n",True,True)
            else:
                new_line=" "+ori+"\""+pdata.word.replace("\n","\\n")+"\"\n"
            fi.write(new_line)
def writein(local_path,rel,chn,mode="a"):
    full_path = "./already/"+local_path
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path,mode,encoding="utf-8") as fi:
        fi.write(rel+"\""+chn.replace("\n","\\n")+"\"\n")
def translate_para(local_path,mde):
    tran: Dict[str, Paradox_data]={}
    tp=extract("./localisation/"+local_path,mde)
    for ct in tp:
        tran[ct[0]]=Paradox_data(key_w=ct[0],word=ct[1],vis=0)
    already_path = os.path.join("./already", local_path)
    os.makedirs(os.path.dirname(already_path), exist_ok=True)
    with open(already_path, "a", encoding="utf-8"):
        pass
    ap=extract(already_path,mde)
    for ct in ap:
        tran[ct[0]]=Paradox_data(key_w=ct[0],word=ct[1],vis=1)
    cnt=0
    # 收集所有需要翻译的文本
    texts: List[str]=[]
    pdata: List[Paradox_data]=[]
    for tct in tran:
        if tran[tct].vis == 0:
            pdata.append(Paradox_data(key_w=tran[tct].key_w,word=tran[tct].word,vis=1))
            texts.append(tran[tct].word)
        else:
            cnt+=1
    if texts!=[]:
        seg_length=150
        for i in range(0,len(texts),seg_length):
            seg_texts = texts[i:min(len(texts),i+seg_length)]
            seg_pdata = pdata[i:min(len(pdata),i+seg_length)]
            seg_texts = request.request_deepseek_batch(seg_texts, mde, cnt ,len(tran))
            for j in range(len(seg_texts)):
                seg_pdata[j].word=seg_texts[j]
                tran[seg_pdata[j].key_w] = seg_pdata[j]
                writein("/"+local_path, seg_pdata[j].key_w, seg_pdata[j].word,"a")
            cnt+=len(seg_pdata)
    outputs(local_path,tran,mde)