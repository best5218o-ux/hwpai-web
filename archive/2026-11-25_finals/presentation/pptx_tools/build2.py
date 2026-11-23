import re,copy
exec(open('build.py').read().replace("p.save('out.pptx')",""))
from pptx.util import Emu
def img_slide(idx,img,f):
    s=p.slides[idx]; tree=s.shapes._spTree
    for sh in list(s.shapes): tree.remove(sh._element)
    s.shapes.add_picture(img,0,0,p.slide_width,p.slide_height)
    s.notes_slide.notes_text_frame.text=aside(f)
img_slide(0,'h2_00.jpg','cover'); img_slide(5,'h2_01.jpg','flow'); img_slide(12,'h2_03.jpg','unique'); img_slide(16,'h2_04.jpg','close'); img_slide(2,'h2_05.jpg','pile')
for _i,_j,_f in [(9,'h3_compare1.jpg','compare1'),(11,'h3_perf.jpg','perf'),(14,'h3_anyone.jpg','anyone'),(15,'h3_improve.jpg','improve'),(17,'h3_qacompare.jpg','qa-compare'),(13,'h3_ai.jpg','ai')]: img_slide(_i,_j,_f)
for idx,f in [(3,'today'),(14,'anyone')]:
    p.slides[idx].notes_slide.notes_text_frame.text=aside(f)
# place title
s8=p.slides[7]
for sh in s8.shapes:
    if sh.has_text_frame and '다운로드' in sh.text_frame.text:
        tf=sh.text_frame; runs=[r for para in tf.paragraphs for r in para.runs]
        runs[0].text='폴더 실시간 감시, '; 
        if len(runs)>1:
            runs[1].text='들어오는 HWP 자동 변환'
            for r in runs[2:]: r.text=''
p.slides[7].notes_slide.notes_text_frame.text=aside('place')
# new watch slide after index 7
layout=p.slides[16].slide_layout
ns=p.slides.add_slide(layout)
for sh in list(ns.shapes): ns.shapes._spTree.remove(sh._element)
ns.shapes.add_picture('h2_02.jpg',0,0,p.slide_width,p.slide_height)
ns.notes_slide.notes_text_frame.text=aside('watch')
lst=p.slides._sldIdLst; el=lst[-1]; lst.remove(el); lst.insert(8,el)
p.save('out2.pptx'); print('ok',len(p.slides))
