from lxml import etree
P='http://schemas.openxmlformats.org/presentationml/2006/main'
def autoplay2(slide,items):
    """items: list of (spid, delay_ms, dur_ms)"""
    for t in slide._element.findall('{%s}timing'%P): slide._element.remove(t)
    cid=[4]
    def nid():
        cid[0]+=1; return cid[0]
    effs=''
    for k,(spid,d,ms) in enumerate(items):
        a=nid(); b=nid()
        nt='afterEffect' if k==0 else 'withEffect'
        effs+=f'''<p:par><p:cTn id="{a}" presetID="1" presetClass="mediacall" presetSubtype="0" fill="hold" nodeType="{nt}"><p:stCondLst><p:cond delay="{d}"/></p:stCondLst><p:childTnLst>
<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="{b}" dur="{ms}" fill="hold"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:cmd></p:childTnLst></p:cTn></p:par>'''
    vids=''
    for spid,d,ms in items:
        vids+=f'<p:video><p:cMediaNode vol="80000"><p:cTn id="{nid()}" fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cMediaNode></p:video>'
    x=f'''<p:timing xmlns:p="{P}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>
<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>
<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>
<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>
{effs}
</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>
</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>
{vids}
</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>'''
    el=etree.fromstring(x)
    ext=slide._element.find('{%s}extLst'%P)
    if ext is not None: ext.addprevious(el)
    else: slide._element.append(el)
