#!/usr/bin/python
# -*- coding: UTF-8 -*-

import os,json

import paradox


def translate(dir_name,mde):
    dirs=os.listdir("./localisation/"+dir_name)
    alrs=os.listdir("./already/"+dir_name)
    for eng in dirs:
        if mde in para:
            if paradox.check(eng)==1:
                os.mkdir("./chn/"+ dir_name+eng)
                if eng not in alrs: 
                    os.mkdir("./already/"+dir_name+eng)
                translate(dir_name+eng+"/",mde)
                continue
            elif paradox.check(eng)==2 and mde!="eu4":
                chn=eng.replace("l_english","l_simp_chinese")
                os.rename("./localisation/"+dir_name+eng,"./localisation/"+dir_name+chn)
                eng=chn
            print(dir_name+eng)
            paradox.translate_para(dir_name+eng,mde)
            
para=["st","hoi4","eu4","ck3","vic3"]
modes=os.listdir("./localisation/") 
for ex_mode in modes:
    if ex_mode in para:
        paradox.clean("./chn/"+ex_mode+"/")
        os.mkdir("./chn/"+ex_mode+"/")
        translate(ex_mode+"/",ex_mode)
