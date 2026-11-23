import re
src=open('/tmp/px/build.py').read()
start=src.index('def autoplay'); end=src.index("put_video(6")
from pptx import Presentation
from pptx.util import Emu,Pt
from lxml import etree
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
p=Presentation(); p.slide_width=Emu(12192000); p.slide_height=Emu(6858000)
exec(src[start:end])
L=p.slide_layouts[6]
def txt(s,t):
    tb=s.shapes.add_textbox(Emu(300000),Emu(200000),Emu(9000000),Emu(900000)); tb.text_frame.text=t; tb.text_frame.paragraphs[0].runs[0].font.size=Pt(40)
for v,lab in [('/tmp/chk/tA.mp4','A 현재 소리'),('/tmp/chk/tB.mp4','B 무음'),('/tmp/chk/tD.mp4','D AAC44k'),('/tmp/chk/tE.mp4','E MP3')]:
    s=p.slides.add_slide(L); txt(s,'BLANK — next: '+lab)
    s=p.slides.add_slide(L)
    pic=s.shapes.add_picture('/tmp/chk/q0.jpg',Emu(1000000),Emu(1000000),Emu(7000000),Emu(4600000)); pic.name='Image 0'
    put_video(len(p.slides)-1,v,'/tmp/chk/q0.jpg',23700,['Image 0'])
    txt(s,lab)
p.save('/tmp/chk/latency_test3.pptx'); print('ok')
