"""사용: fontmap_build.py <Windows 글꼴 폴더> <한컴 HOffice130 폴더>. 글꼴 파일 메타데이터(이름 표 nameID 1, 영어 0x409 / 한국어 0x412)와 한컴 HFT 등록표로 「영문 글꼴 이름 → 한국어 글꼴 이름」 표를 만든다."""
import os,sys,json,re,collections
from fontTools.ttLib import TTFont, TTCollection
def u(r):
    try: return r.toUnicode()
    except Exception: return None
m=collections.defaultdict(set); src={}
win_ko={}    # Windows 설치 글꼴의 한국어 이름 → 영문 이름
seen=set()   # 같은 파일 이름이 Windows 글꼴 폴더에 있으면 그 판이 쓰인다(한컴 사본은 건너뜀)
for root in sys.argv[1:]:
  for dp,dn,fn in os.walk(root):
    for f in fn:
        if not f.lower().endswith(('.ttf','.ttc','.otf')): continue
        if f.lower() in seen and 'HOffice' in root: continue
        if 'HOffice' not in root: seen.add(f.lower())
        try: fonts=TTCollection(os.path.join(dp,f),lazy=True).fonts if f.lower().endswith('.ttc') else [TTFont(os.path.join(dp,f),lazy=True)]
        except Exception: continue
        for ft in fonts:
            try: nt=ft['name']
            except Exception: continue
            en=[u(r) for r in nt.names if r.nameID==1 and r.platformID==3 and r.langID==0x409]
            ko=[u(r) for r in nt.names if r.nameID==1 and r.platformID==3 and r.langID==0x412]
            for e in en:
                for k in ko:
                    if not (e and k and k != e):
                        continue
                    if 'HOffice' in root and win_ko.get(k, e) != e:
                        continue   # 같은 한국어 이름을 Windows 설치 글꼴이 다른 영문 이름으로 이미 가짐(HYgsrB·HYHeadLine M 류) — 한글은 이 별칭을 풀지 않는다
                    m[e].add(k); src[e]='ttf:'+f
                    if 'HOffice' not in root: win_ko.setdefault(k, e)
hft=[a for a in sys.argv[1:] if 'HOffice' in a]
for h in hft:
    b=open(h+'/Bin/FontDB/hftinfo.dat','rb').read().decode('utf-16le','replace')
    for ln in b.splitlines():
        mm=re.match(r'^([^=\[;]+)=([^,]+\.HFT),[^,]*,[^,]*,[^,]*,[^,]*,\d+,(.+)$',ln.strip(),re.I)
        if mm:
            ko,f,en=mm.group(1).strip(),mm.group(2),mm.group(3).strip()
            if en and en!=ko: m[en].add(ko); src[en]='hft:'+f
print(json.dumps({e:{'ko':sorted(v),'src':src[e]} for e,v in sorted(m.items())},ensure_ascii=False,indent=0))
