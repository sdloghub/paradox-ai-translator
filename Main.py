#!/usr/bin/python
# -*- coding: UTF-8 -*-

import os,sys
from time import sleep
from tokenize import untokenize

from pydantic.types import T
import Paradox,Request


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
            Paradox.translate_para(dir_name+eng,mde,model)
            
para=["st","hoi4","eu4","ck3","vic3"]
modes=os.listdir("./localisation/")
model="deepseek"
for ex_mode in modes:
    if ex_mode in para:
        Paradox.clean("./chn/"+ex_mode+"/")
        os.mkdir("./chn/"+ex_mode+"/")
        translate(ex_mode+"/",ex_mode,model)
