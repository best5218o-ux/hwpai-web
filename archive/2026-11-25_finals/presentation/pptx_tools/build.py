import re,copy
from pptx import Presentation
from pptx.util import Emu
from lxml import etree
S='/tmp/claude-0/-home-claude/2de2d425-f65d-5b12-93ca-373977a7f91a/scratchpad/deck2/project/slides/'
def aside(f):
    return re.search(r'<aside>(.*?)</aside>',open(S+f+'.html').read(),re.S).group(1).strip()
p=Presentation('in.pptx')
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
import os
DELAY=os.environ.get('DELAY','0')
def autoplay(slide,spid,ms):
    for t in slide._element.findall('p:timing',ns): slide._element.remove(t)
    x=f'''<p:timing xmlns:p="{ns['p']}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>
<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>
<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>
<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>
<p:par><p:cTn id="5" presetID="1" presetClass="mediacall" presetSubtype="0" fill="hold" nodeType="afterEffect"><p:stCondLst><p:cond delay="{DELAY}"/></p:stCondLst><p:childTnLst>
<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="6" dur="{ms}" fill="hold"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:cmd>
</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>
</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>
<p:video><p:cMediaNode vol="80000"><p:cTn id="7" fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cMediaNode></p:video>
</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>'''
    el=etree.fromstring(x)
    # timing must come after clrMapOvr / before extLst
    ext=slide._element.find('p:extLst',ns)
    if ext is not None: ext.addprevious(el)
    else: slide._element.append(el)
def put_video(idx,video,poster,ms,remove_names):
    s=p.slides[idx]; tree=s.shapes._spTree
    geo=None; pos=None
    for sh in list(s.shapes):
        if sh.name in remove_names:
            if sh.name.startswith('Image'): geo=(sh.left,sh.top,sh.width,sh.height); pos=list(tree).index(sh._element)
            tree.remove(sh._element)
    mv=s.shapes.add_movie(video,*geo,poster_frame_image=poster,mime_type='video/mp4')
    tree.remove(mv._element); tree.insert(pos,mv._element)
    autoplay(s,mv.shape_id,ms)
    # 영상 위에 투명 판을 덮어, 화면을 눌러도 영상이 멈추지 않고 다음 장으로 넘어가게 한다
    from pptx.enum.shapes import MSO_SHAPE
    cov=s.shapes.add_shape(MSO_SHAPE.RECTANGLE,0,0,p.slide_width,p.slide_height)
    cov.name='ClickThrough'; cov.line.fill.background(); cov.fill.solid()
    from pptx.dml.color import RGBColor
    cov.fill.fore_color.rgb=RGBColor(0,0,0)
    sf=cov.fill._xPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}solidFill')[0]
    a_=etree.SubElement(sf,'{http://schemas.openxmlformats.org/drawingml/2006/main}alpha'); a_.set('val','0')
    cov.text_frame.text=''
import os
Q=os.environ.get('QUAD','v3_quad.mp4'); PL=os.environ.get('PLACE','v3_place.mp4')
put_video(6,Q,'s3_quad.jpg',23700,['Shape 1','Image 0'])
put_video(7,PL,'s3_place.jpg',19600,['Image 0'])
for idx,img,f in [(8,'hi00.jpg','hangul'),(14,'hi01.jpg','anyone'),(15,'hi02.jpg','improve')]:
    s=p.slides[idx]; tree=s.shapes._spTree
    for sh in list(s.shapes): tree.remove(sh._element)
    s.shapes.add_picture(img,0,0,p.slide_width,p.slide_height)
for idx,f in [(6,'demo'),(7,'place'),(8,'hangul'),(14,'anyone'),(15,'improve'),(5,'flow')]:
    p.slides[idx].notes_slide.notes_text_frame.text=aside(f)
p.save('out.pptx')
print('saved')
