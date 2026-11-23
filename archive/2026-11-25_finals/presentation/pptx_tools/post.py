import sys
from pptx import Presentation
src,dst=sys.argv[1],sys.argv[2]
p=Presentation(src); W,H=p.slide_width,p.slide_height
S=list(p.slides)
def full_img(s,img):
    t=s.shapes._spTree
    for sh in list(s.shapes): t.remove(sh._element)
    s.shapes.add_picture(img,0,0,W,H)
for n,img in [(2,'h4_problem.jpg'),(4,'h4_today.jpg'),(5,'h4_treasure.jpg'),(12,'h4_compare2.jpg')]:
    full_img(S[n-1],'/tmp/px/'+img)
# 7: 배경+제목 그림을 맨 아래에, 영상·투명판은 유지
s=S[6]; t=s.shapes._spTree
for sh in list(s.shapes):
    if sh.has_text_frame and sh.text_frame.text.strip() and sh.name!='ClickThrough': t.remove(sh._element)
pic=s.shapes.add_picture('/tmp/px/h4_demo.jpg',0,0,W,H); t.remove(pic._element); t.insert(2,pic._element)
# 8: 제목은 영상·표지그림에 들어 있으므로 글상자 제거
s=S[7]; t=s.shapes._spTree
for sh in list(s.shapes):
    if sh.has_text_frame and sh.text_frame.text.strip() and sh.name!='ClickThrough': t.remove(sh._element)

import re
SD='/tmp/claude-0/-home-claude/2de2d425-f65d-5b12-93ca-373977a7f91a/scratchpad/deck2/project/slides/'
ORDER=['cover','problem','pile','today','treasure','flow','demo','place','watch','hangul','compare1','compare2','perf','unique','ai','anyone','improve','close']
for sl,n in zip(S[:18],ORDER):
    sl.notes_slide.notes_text_frame.text=re.search(r'<aside>(.*?)</aside>',open(SD+n+'.html').read(),re.S).group(1).strip()
# 부록 19~21 삭제
lst=p.slides._sldIdLst
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
for el in list(lst)[18:]:
    p.part.drop_rel(el.get(R)); lst.remove(el)
p.save(dst)
q=Presentation(dst)
for i,s in enumerate(q.slides,1):
    tx=[sh for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
    print(i,[sh.shape_type for sh in s.shapes],'text',len(tx))
