import sys,os,zipfile,re,struct,zlib,collections,olefile,json
sys.path.insert(0,'<작업폴더>')
from h5cells import records
def raw_faces(path):
    o=olefile.OleFileIO(path)
    fh=o.openstream('FileHeader').read(); comp=struct.unpack_from('<I',fh,36)[0]&1
    d=o.openstream('DocInfo').read(); d=zlib.decompress(d,-15) if comp else d
    idm=None; out=[]
    for tag,lvl,r in records(d):
        if tag==17: # ID_MAPPINGS
            idm=struct.unpack_from('<7i',r,4)  # counts after binData? layout: bindata, then 7 langs
        if tag==19:
            flags=r[0]; n=struct.unpack_from('<H',r,1)[0]; name=r[3:3+2*n].decode('utf-16le','replace')
            p=3+2*n; alt=None; atype=None
            if flags&0x80:
                atype=r[p]; m=struct.unpack_from('<H',r,p+1)[0]; alt=r[p+3:p+3+2*m].decode('utf-16le','replace')
            out.append((name,alt,atype,flags))
    # split by idm counts
    res=[];i=0
    for c in idm: res.append(out[i:i+c]); i+=c
    return res
def hx_faces(path):
    h=zipfile.ZipFile(path).read('Contents/header.xml').decode()
    res=[]
    for m in re.finditer(r'<hh:fontface lang="(\w+)" fontCnt="\d+">(.*?)</hh:fontface>',h,re.S):
        res.append([(f.group(1),f.group(2)) for f in re.finditer(r'<hh:font id="\d+" face="([^"]*)" type="(\w+)"',m.group(2))])
    return res
pairs=collections.Counter(); keep=collections.Counter(); ex={}
for root in sys.argv[1:]:
    for f in sorted(os.listdir(root+'/hangul')):
        k=f[:-5]
        try: R=raw_faces(root+'/원본/'+k+'.hwp'); X=hx_faces(root+'/hangul/'+f)
        except Exception as e: continue
        for rl,xl in zip(R,X):
            if len(rl)!=len(xl): pairs[('LENMISMATCH',)]+=1; continue
            for (n,alt,at,fl),(xn,xt) in zip(rl,xl):
                if n!=xn: pairs[(n,xn,alt,at,xt)]+=1; ex[(n,xn)]=k
                else: keep[(n,alt,xt)]+=1
json.dump({'pairs':[[list(k),v] for k,v in pairs.items()],'keep':[[list(k),v] for k,v in keep.items()]},open(S+'/fontpairs.json','w') if (S:='<작업폴더>') else None,ensure_ascii=False)
for k,v in pairs.most_common(60): print(v,k)
