import sys,zipfile,re
src,dst,mode=sys.argv[1],sys.argv[2],sys.argv[3]
zi=zipfile.ZipFile(src); files={n:zi.read(n) for n in zi.namelist()}
ct=files['[Content_Types].xml'].decode()
if mode=='nonotes':
    # drop notes master + notes slides
    for n in list(files):
        if n.startswith('ppt/notesMasters/') or n.startswith('ppt/notesSlides/'): del files[n]
    ct=re.sub(r'<Override PartName="/ppt/notes[^>]*/>','',ct)
    pr=files['ppt/_rels/presentation.xml.rels'].decode()
    pr=re.sub(r'<Relationship [^>]*notesMaster"[^>]*/>','',pr); files['ppt/_rels/presentation.xml.rels']=pr.encode()
    p=files['ppt/presentation.xml'].decode(); p=re.sub(r'<p:notesMasterIdLst>.*?</p:notesMasterIdLst>','',p); files['ppt/presentation.xml']=p.encode()
    for n in list(files):
        if re.match(r'ppt/slides/_rels/slide\d+\.xml\.rels',n):
            r=files[n].decode(); r=re.sub(r'<Relationship [^>]*/notesSlide"[^>]*/>','',r); files[n]=r.encode()
elif mode=='theme2':
    files['ppt/theme/theme2.xml']=files['ppt/theme/theme1.xml']
    r=files['ppt/notesMasters/_rels/notesMaster1.xml.rels'].decode().replace('theme1.xml','theme2.xml'); files['ppt/notesMasters/_rels/notesMaster1.xml.rels']=r.encode()
    ct=ct.replace('<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>','<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/><Override PartName="/ppt/theme/theme2.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>')
    assert 'theme2.xml' in ct
files['[Content_Types].xml']=ct.encode()
zo=zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED)
order=['[Content_Types].xml']+[n for n in zi.namelist() if n in files and n!='[Content_Types].xml']+[n for n in files if n not in zi.namelist()]
for n in order:
    zo.writestr(n,files[n],compress_type=zipfile.ZIP_STORED if n.endswith(('.mp4','.jpg','.jpeg','.png','.wav')) else zipfile.ZIP_DEFLATED)
zo.close(); print(dst)
