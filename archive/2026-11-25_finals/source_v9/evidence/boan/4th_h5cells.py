import olefile,zlib,struct,sys
def records(data):
    i=0
    while i+4<=len(data):
        h=struct.unpack_from('<I',data,i); h=h[0]; i+=4
        tag=h&0x3ff; lvl=(h>>10)&0x3ff; sz=h>>20
        if sz==0xfff: sz=struct.unpack_from('<I',data,i)[0]; i+=4
        yield tag,lvl,data[i:i+sz]; i+=sz
def sections(path):
    o=olefile.OleFileIO(path)
    fh=o.openstream('FileHeader').read(); comp=struct.unpack_from('<I',fh,36)[0]&1
    names=sorted([e for e in o.listdir() if e[0]=='BodyText'], key=lambda e:int(e[1][7:]))
    for e in names:
        d=o.openstream(e).read()
        if comp: d=zlib.decompress(d,-15)
        yield list(records(d))
def tables(path):
    out=[]
    for recs in sections(path):
        cur=None
        for idx,(tag,lvl,d) in enumerate(recs):
            if tag==77: # HWPTAG_TABLE
                prop,rows,cols=struct.unpack_from('<IHH',d,0)
                cur={'rows':rows,'cols':cols,'lvl':lvl,'cells':[], 'raw':d}
                out.append(cur)
            elif tag==72 and cur is not None and lvl==cur['lvl']:
                # cell list header
                npara,prop=struct.unpack_from('<hI',d,0)
                off=8
                col,row,cs,rs,w,h=struct.unpack_from('<HHHHII',d,off)
                cur['cells'].append({'row':row,'col':col,'rs':rs,'cs':cs,'w':w,'h':h})
    return out
if __name__=='__main__':
    for t in tables(sys.argv[1]):
        print('TABLE',t['rows'],t['cols'])
        for c in t['cells']: print(c)
