import struct,sys
sys.path.insert(0,'<작업폴더>')
from h5cells import sections
def shapes(path):
    out=[]
    for recs in sections(path):
        for tag,lvl,d in recs:
            if tag==76 and len(d)>=48:
                off=8 if d[0:4]==d[4:8] else 4
                cid=d[0:4][::-1].decode('latin1')
                x,y,gl,ver,ow,oh,cw,ch=struct.unpack_from('<iiHHIIII',d,off)
                out.append(dict(id=cid,gl=gl,org=(ow,oh),cur=(cw,ch),off=(x,y)))
    return out
if __name__=='__main__':
    for s in shapes(sys.argv[1]): print(s)
