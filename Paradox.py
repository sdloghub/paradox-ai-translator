import os,sys,re
import Request
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
def chinese_in(txt):
    pattern = re.compile(r'[\u4e00-\u9fff]')
    if bool(pattern.search(txt)):
        return True
    else:
        return txt.count("$") or txt.count("[") or txt.count("]") or txt.count("£")
def clean(dir_name):
    dir=os.listdir(dir_name)
    for name in dir:
        if check(name)==1:
            clean(dir_name+name+"/")
        else:
            os.remove(dir_name+name)
    os.rmdir(dir_name)
def extract(str,mde):
    fa=open(str,"a+",encoding="utf-8")
    fa.close()
    fo=open(str,"r+",encoding="utf-8")
    local_list=fo.readlines()
    fo.close()
    cnt=0
    pdata=[]
    while cnt<len(local_list):
        strin=local_list[cnt].lstrip()
        find_length=strin.find("\"")
        skipp=(strin.lstrip()).find("#")
        if (skipp<=3 and skipp!=-1) or find_length==-1:
            cnt+=1
            continue
        start_l=find_length+1
        end_l=len(strin)-2
        if skipp!=-1:
            end_l=skipp-2
        if find_length!=-1:
            if mde=="eu4":
                pdata.append((strin[0:find_length],special_unescape(strin[start_l:end_l],True,True),mde))
            else:
                pdata.append((strin[0:find_length],strin[start_l:end_l],mde))
        cnt+=1
    return pdata
def outputs(local_path,dic,mde):
    fo=open("./localisation/"+local_path,"r",encoding="utf-8")
    local_list=fo.readlines()
    fo.close()
    fi=open("./chn/"+local_path,"w",encoding="utf-8")
    cnt=0
    ori=""
    rep=""
    while cnt<len(local_list):
        strin=local_list[cnt].lstrip()
        find_length=strin.find("\"")
        skipp=(strin.lstrip()).find("#")
        if (skipp<=3 and skipp!=-1) or find_length==-1 or chinese_in(strin):
            if strin.find("l_english")!=-1 and mde!="eu4":
                strin=strin.replace("l_english:","l_simp_chinese:")
            fi.write(strin)
            cnt+=1
            continue
        if find_length!=-1:
            ori=strin[0:find_length]
            if mde=="eu4":
                strin=" "+ori+"\""+special_escape(dic[ori].word.replace("\n","\\n")+"\"\n",True,True)
            else:
                strin=" "+ori+"\""+dic[ori].word.replace("\n","\\n")+"\"\n"
            fi.write(strin)
            cnt+=1
            continue
def writein(local_path,rel,chn,mde):
    fi=open("./already/"+local_path,mde,encoding="utf-8")
    fi.write(rel+"\""+chn.replace("\n","\\n")+"\"\n")
    fi.close()
def translate_para(local_path,mde,model):
    tran={}
    tp=extract("./localisation/"+local_path,mde)
    for ct in tp:
        tran[ct[0]]=Paradox_data(key_w=ct[0],word=ct[1],vis=0)
    ap=extract("./already/"+model+"/"+local_path,mde)
    for ct in ap:
        if (ct[1].replace(" ","")!="" or chinese_in(ct[1])==True):
            tran[ct[0]]=Paradox_data(key_w=ct[0],word=ct[1],vis=1)
    cnt=0
    # 收集所有需要翻译的文本
    texts=[]
    pdata=[]
    for tct in tran:
        if ((tran[tct].word).replace(" ","") == "" or chinese_in(tran[tct].word)==True) and tran[tct].vis == 0:
            tran[tct].vis = 1
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
            seg_texts = Request.request_deepseek(seg_texts, mde, cnt ,len(tran))
            for j in range(len(seg_texts)):
                seg_pdata[j].word=seg_texts[j]
                tran[seg_pdata[j].key_w] = seg_pdata[j]
                writein(model+"/"+local_path, seg_pdata[j].key_w, seg_pdata[j].word,"a")
            cnt+=seg_length
    outputs(local_path,tran,mde)



# 测试代码
'''
original = "你好"
escaped = special_escape(original, True, True)
unescaped = special_unescape(escaped, True, True)
print(f"原始: {original}")
print(f"转义: {escaped}")
print(f"还原: {unescaped}")
'''