import os,sys,re
import Request
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
    return bool(pattern.search(txt))
def clean(dir_name):
    dir=os.listdir(dir_name)
    for name in dir:
        if check(name)==1:
            clean(dir_name+name+"/")
        else:
            os.remove(dir_name+name)
    os.rmdir(dir_name)
def extract(str):
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
        skipp=strin.find("#")
        if skipp!=-1 or find_length==-1:
            cnt+=1
            continue
        start_l=find_length+1
        end_l=len(strin)-2
        if find_length!=-1:
            pdata.append((strin[0:find_length],strin[start_l:end_l]))
        cnt+=1
    return pdata
def outputs(local_path,dic):
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
        skipp=strin.find("#")
        if skipp!=-1 or find_length==-1:
            if strin.find("l_english")!=-1:
                strin=strin.replace("l_english:","l_simp_chinese:")
            fi.write(strin)
            cnt+=1
            continue
        start_l=find_length+1
        end_l=len(strin)-2
        if find_length!=-1:
            ori=strin[0:find_length]
            rep=strin[start_l:end_l]
            strin=(strin.replace(rep,dic[ori].word.replace("\n","\\n")))
            fi.write(strin)
            cnt+=1
            continue
def writein(local_path,rel,chn,mde):
    fi=open("./already/"+local_path,mde,encoding="utf-8")
    fi.write(rel+"\""+chn.replace("\n","\\n")+"\"\n")
    fi.close()
def translate_para(local_path,mde,model):
    tran={}
    tp=extract("./localisation/"+local_path)
    for ct in tp:
        tran[ct[0]]=Paradox_data(ct[0],ct[1],0)
    ap=extract("./already/"+model+"/"+local_path)
    for ct in ap:
        if ct[1]!="" '''and chinese_in(ct[1])==True''':
            tran[ct[0]]=Paradox_data(ct[0],ct[1],1)
    cnt=0
    # 收集所有需要翻译的文本
    texts=[]
    pdata=[]
    for tct in tran:
        if (tran[tct].word == "" or chinese_in(tran[tct].word)==True) and tran[tct].vis == 0:
            tran[tct].vis = 1
        if tran[tct].vis == 0:
            pdata.append(Paradox_data(tran[tct].key_w,tran[tct].word,1))
            texts.append(tran[tct].word)
        else:
            cnt+=1
    if texts!=[]:
        seg_length=50
        for i in range(0,len(texts),seg_length):
            seg_texts = texts[i:min(len(texts),i+seg_length)]
            seg_pdata = pdata[i:min(len(pdata),i+seg_length)]
            seg_texts = Request.request_deepseek(seg_texts, mde, cnt ,len(tran))
            for j in range(len(seg_texts)):
                seg_pdata[j].word=seg_texts[j]
                tran[seg_pdata[j].key_w] = seg_pdata[j]
                writein(model+"/"+local_path, seg_pdata[j].key_w, seg_pdata[j].word,"a")
            cnt+=seg_length
    outputs(local_path,tran)