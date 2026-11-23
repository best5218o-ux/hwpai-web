from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from lxml import etree
P='http://schemas.openxmlformats.org/presentationml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
AUD='http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio'
_n=[0]
def _place_transition(slide,el):
    sld=slide._element
    for t in sld.findall('{%s}transition'%P): sld.remove(t)
    tm=sld.find('{%s}timing'%P)
    if tm is not None: tm.addprevious(el)
    else:
        ext=sld.find('{%s}extLst'%P)
        if ext is not None: ext.addprevious(el)
        else: sld.append(el)
def trans_sound(slide,wav,name):
    _n[0]+=1
    part=Part(PackURI(f'/ppt/media/tsound{_n[0]}.wav'),'audio/wav',slide.part.package,open(wav,'rb').read())
    rid=slide.part.relate_to(part,AUD)
    el=etree.fromstring(f'<p:transition xmlns:p="{P}" xmlns:r="{R}" spd="fast"><p:sndAc><p:stSnd><p:snd r:embed="{rid}" name="{name}"/></p:stSnd></p:sndAc></p:transition>')
    _place_transition(slide,el)
def trans_stop(slide):
    el=etree.fromstring(f'<p:transition xmlns:p="{P}" spd="fast"><p:sndAc><p:endSnd/></p:sndAc></p:transition>')
    _place_transition(slide,el)
