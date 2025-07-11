#!/usr/bin/python
# -*- coding: UTF-8 -*-

import os,sys
from time import sleep
from tokenize import untokenize

from pydantic.types import T
import Paradox,Request
class Paradox_data:
    def __init__(self,key_w,word,vis):
        self.key_w=key_w
        self.word=word
        self.vis=vis

def translate(dir_name,mde,model):
    dirs=os.listdir("./localisation/"+dir_name)
    alrs=os.listdir("./already/"+model+"/"+dir_name)
    for eng in dirs:
        if mde in para:
            if Paradox.check(eng)==1:
                os.mkdir("./chn/"+ dir_name+eng)
                if eng not in alrs: 
                    os.mkdir("./already/"+model+"/"+dir_name+eng)
                translate(dir_name+eng+"/",mde,model)
                continue
            elif Paradox.check(eng)==2:
                chn=eng.replace("l_english","l_simp_chinese")
                os.rename("./localisation/"+dir_name+eng,"./localisation/"+dir_name+chn)
                eng=chn
            print(dir_name+eng)
            tran={}
            tp=Paradox.extract("./localisation/"+dir_name+eng)
            for ct in tp:
                tran[ct[0]]=Paradox_data(ct[0],ct[1],0)
            ap=Paradox.extract("./already/"+model+"/"+dir_name+eng)
            for ct in ap:
                tran[ct[0]]=Paradox_data(ct[0],ct[1],1)
            cnt=0
            # 收集所有需要翻译的文本
            texts=[]
            pdata=[]
            for tct in tran:
                if tran[tct].word == "" and tran[tct].vis == 0:
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
                        Paradox.part(model+"/"+dir_name+eng, seg_pdata[j].key_w, seg_pdata[j].word)
                    cnt+=seg_length
            Paradox.outputs(dir_name+eng,tran)
para=["st","hoi4","eu4","ck3","vic3"]
modes=os.listdir("./localisation/")
model="deepseek"
for ex_mode in modes:
    if ex_mode in para:
        Paradox.clean("./chn/"+ex_mode+"/")
        os.mkdir("./chn/"+ex_mode+"/")
        translate(ex_mode+"/",ex_mode,model)
