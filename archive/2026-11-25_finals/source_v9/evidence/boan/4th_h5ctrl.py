import struct,sys
sys.path.insert(0,'<작업폴더>')
from h5cells import sections
def ctrls(path, ids=None):
    out=[]
    for recs in sections(path):
        for tag,lvl,d in recs:
            if tag==71 and len(d)>=24:
                cid=d[0:4][::-1].decode('latin1')
                if ids and cid not in ids: continue
                attr,vo,ho,w,h=struct.unpack_from('<IiiII',d,4)
                out.append(dict(id=cid,attr=attr,vo=vo,ho=ho,w=w,h=h,lvl=lvl))
    return out
if __name__=='__main__':
    for c in ctrls(sys.argv[1], set(sys.argv[2:]) or None): print(c)
