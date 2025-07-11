import os,sys
def check(str):
    if str.find(".yml")==-1: 
        return 1
    elif str.find("l_english.yml")!=-1:
        return 2
    else:
        return 0
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
def part(local_path,rel,chn):
    fi=open("./already/"+local_path,"a+",encoding="utf-8")
    fi.write(rel+"\""+chn.replace("\n","\\n")+"\"\n")
    fi.close()