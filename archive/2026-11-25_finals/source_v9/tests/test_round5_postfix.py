"""결선 보완 5차 뒤처리(C122~C129) 회귀 시험 — 실행: python -m unittest discover -s tests
API·네트워크 호출 없음. 손으로 만든 최소 HWPX 로 시험한다. 각 시험은 제출본 코드(해당 함수 없음)에서 실패한다."""
import os
import re
import shutil
import sys
import tempfile
import unittest
import xml.dom.minidom
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "app"))
from hwpai import postfix  # noqa: E402

NS = ('xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
      'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
      'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"')
CHARPR = ('<hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0" symMark="NONE" '
          'borderFillIDRef="2"><hh:fontRef hangul="0"/><hh:underline type="NONE" shape="SOLID" color="#000000"/></hh:charPr>')


def build(path, sections, fonts=("함초롬바탕",), files=None, hpf_extra=""):
    faces = "".join(f'<hh:font id="{i}" face="{f}" type="TTF" isEmbedded="0"/>' for i, f in enumerate(fonts))
    header = (f'<?xml version="1.0" encoding="UTF-8"?><hh:head {NS} version="1.2" secCnt="{len(sections)}"><hh:refList>'
              f'<hh:fontfaces><hh:fontface lang="HANGUL" fontCnt="{len(fonts)}">{faces}</hh:fontface></hh:fontfaces>'
              f'<hh:charProperties itemCnt="1">{CHARPR}</hh:charProperties></hh:refList></hh:head>')
    items = "".join(f'<opf:item id="section{i}" href="Contents/section{i}.xml" media-type="application/xml"/>' for i in range(len(sections)))
    refs = "".join(f'<opf:itemref idref="section{i}" linear="yes"/>' for i in range(len(sections)))
    hpf = (f'<?xml version="1.0" encoding="UTF-8"?><opf:package xmlns:opf="http://www.idpf.org/2007/opf/"><opf:manifest>'
           f'<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>{items}{hpf_extra}</opf:manifest>'
           f'<opf:spine><opf:itemref idref="header" linear="yes"/>{refs}</opf:spine></opf:package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/content.hpf", hpf)
        for i, body in enumerate(sections):
            z.writestr(f"Contents/section{i}.xml", f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {NS}>{body}</hs:sec>')
        for n, b in (files or {}).items():
            z.writestr(n, b)


def read(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def wellformed(path):
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith(".xml") or n.endswith(".hpf"):
                xml.dom.minidom.parseString(z.read(n))


class Round5(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "t.hwpx")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_c122_cur_size_zero(self):
        body = ('<hp:p><hp:run charPrIDRef="0"><hp:container groupLevel="0"><hp:offset x="0" y="0"/><hp:orgSz width="100" height="200"/><hp:curSz width="100" height="300"/>'
                '<hp:pic id="1" groupLevel="1"><hp:offset x="0" y="0"/><hp:orgSz width="50" height="60"/><hp:curSz width="70" height="60"/></hp:pic>'
                '<hp:line id="2" groupLevel="1"><hp:offset x="0" y="0"/><hp:orgSz width="100" height="100"/><hp:curSz width="13890" height="0"/></hp:line>'
                '<hp:line id="3" groupLevel="0"><hp:offset x="0" y="0"/><hp:orgSz width="100" height="100"/><hp:curSz width="13890" height="0"/></hp:line>'
                '</hp:container></hp:run></hp:p>')
        build(self.p, [body])
        self.assertEqual(postfix._fix_cur_size_zero(self.p), 2)
        x = read(self.p, "Contents/section0.xml")
        self.assertIn('<hp:orgSz width="100" height="200"/><hp:curSz width="0" height="300"/>', x)   # 같은 차원만 0
        self.assertIn('<hp:orgSz width="50" height="60"/><hp:curSz width="70" height="0"/>', x)
        self.assertIn('<hp:line id="2" groupLevel="1"><hp:offset x="0" y="0"/><hp:orgSz width="100" height="100"/><hp:curSz width="13890" height="0"/>', x)   # 다른 값은 그대로
        self.assertIn('<hp:line id="3" groupLevel="0"><hp:offset x="0" y="0"/><hp:orgSz width="100" height="100"/><hp:curSz width="13890" height="0"/>', x)
        wellformed(self.p)

    def test_c123_ole_chart(self):
        ole = ('<hp:p><hp:run charPrIDRef="0"><hp:ole id="7" zOrder="1" numberingType="PICTURE" textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0" '
               'dropcapstyle="None" href="" groupLevel="0" instid="0" objectType="UNKNOWN" binaryItemIDRef="ole1"><hp:offset x="0" y="0"/>'
               '<hp:sz width="32250" widthRelTo="ABSOLUTE" height="18750" heightRelTo="ABSOLUTE" protect="0"/><hp:pos treatAsChar="0"/>'
               '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:caption side="BOTTOM"><hp:subList><hp:p><hp:run charPrIDRef="0"><hp:t>그림 1</hp:t></hp:run></hp:p></hp:subList></hp:caption></hp:ole></hp:run></hp:p>')
        build(self.p, [ole], files={"BinData/ole1.OLE": b"x"},
              hpf_extra='<opf:item id="ole1" href="BinData/ole1.OLE" media-type="application/ole"/>')
        old = postfix._ole_chart_xml
        postfix._ole_chart_xml = lambda b: b"<chartSpace/>"
        try:
            self.assertEqual(postfix._fix_ole_chart(self.p), 1)
        finally:
            postfix._ole_chart_xml = old
        x = read(self.p, "Contents/section0.xml")
        self.assertIn('<hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/ooxmlchart"><hp:chart id="7"', x)
        self.assertIn('chartIDRef="Chart/chart1.xml"><hp:sz width="32250"', x)
        self.assertIn("</hp:chart></hp:case><hp:default><hp:ole id=\"7\"", x)
        self.assertEqual(x.count("그림 1"), 2)            # 캡션도 차트에 함께
        self.assertEqual(read(self.p, "Chart/chart1.xml"), "<chartSpace/>")
        wellformed(self.p)

    def test_c124_font_local_names(self):
        build(self.p, ['<hp:p/>'], fonts=("Haansoft Batang", "HY Junggothic", "Arial", "HYHeadLine M"))
        self.assertEqual(postfix._fix_font_local_names(self.p), 2)
        h = read(self.p, "Contents/header.xml")
        self.assertIn('face="한컴바탕"', h)
        self.assertIn('face="한양중고딕"', h)
        self.assertIn('face="Arial"', h)             # 한국어 이름 없는 글꼴은 그대로
        self.assertIn('face="HYHeadLine M"', h)      # 설치판 이름표에 없는 별칭은 그대로(한글도 그대로 둠)

    def test_c124_font_type_unknown_kept(self):
        """원본 글꼴 종류가 「모름」이면 한글도 이름을 바꾸지 않는다(08663d498dc1 등)."""
        build(self.p, ['<hp:p/>'], fonts=("Haansoft Batang", "Batang"))
        old = postfix._hwp5_face_types
        postfix._hwp5_face_types = lambda src: {"Haansoft Batang": {0}, "Batang": {1}}
        try:
            self.assertEqual(postfix._fix_font_local_names(self.p, "x.hwp"), 1)
        finally:
            postfix._hwp5_face_types = old
        h = read(self.p, "Contents/header.xml")
        self.assertIn('face="Haansoft Batang"', h)
        self.assertIn('face="바탕"', h)

    def test_c125_negative_cell_height(self):
        tbl = ('<hp:p><hp:run charPrIDRef="0"><hp:tbl rowCnt="1" colCnt="2"><hp:sz width="2000" height="566"/><hp:inMargin left="510" right="510" top="283" bottom="283"/>'
               '<hp:tr><hp:tc hasMargin="0"><hp:subList><hp:p><hp:run charPrIDRef="0"><hp:t>글</hp:t></hp:run></hp:p></hp:subList>'
               '<hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="1000" height="4294951402"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'
               '<hp:tc hasMargin="1"><hp:subList/><hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="1000" height="4294967000"/><hp:cellMargin left="141" right="141" top="100" bottom="50"/></hp:tc>'
               '</hp:tr></hp:tbl></hp:run></hp:p>')
        build(self.p, [tbl])
        self.assertEqual(postfix._fix_negative_cell_height(self.p), 2)
        x = read(self.p, "Contents/section0.xml")
        self.assertIn('<hp:cellSz width="1000" height="566"/>', x)    # 표 안쪽 여백 283+283
        self.assertIn('<hp:cellSz width="1000" height="150"/>', x)    # 칸 여백을 쓰는 칸 100+50

    def test_c126_split_sections(self):
        sec = '<hp:p id="0"><hp:run charPrIDRef="0"><hp:secPr id=""/></hp:run><hp:run charPrIDRef="0"><hp:t>{}</hp:t></hp:run></hp:p>'
        build(self.p, ["".join(sec.format(t) for t in ("가", "나", "다"))],
              files={"META-INF/container.rdf": '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about=""><ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" rdf:resource="Contents/section0.xml"/></rdf:Description><rdf:Description rdf:about="Contents/section0.xml"><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#SectionFile"/></rdf:Description><rdf:Description rdf:about=""><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#Document"/></rdf:Description></rdf:RDF>'})
        self.assertEqual(postfix._split_sections(self.p), 2)
        for i, t in enumerate(("가", "나", "다")):
            x = read(self.p, f"Contents/section{i}.xml")
            self.assertEqual(x.count("<hp:secPr"), 1)
            self.assertIn(f"<hp:t>{t}</hp:t>", x)
        self.assertIn('secCnt="3"', read(self.p, "Contents/header.xml"))
        hpf = read(self.p, "Contents/content.hpf")
        self.assertEqual(hpf.count('idref="section'), 3)
        self.assertEqual(read(self.p, "META-INF/container.rdf").count("SectionFile"), 3)
        wellformed(self.p)

    def test_c127_clickhere_guide(self):
        body = ('<hp:p id="1"><hp:run charPrIDRef="0"><hp:t>앞 </hp:t><hp:ctrl><hp:fieldBegin id="5" type="CLICK_HERE" name="a" editable="1" dirty="0">'
                '<hp:parameters cnt="2" name=""><hp:stringParam name="Command">Clickhere:set:53:Direction:wstring:10:FIRSTGUIDE HelpState:wstring:0:  </hp:stringParam>'
                '<hp:stringParam name="Direction">FIRSTGUIDE</hp:stringParam></hp:parameters></hp:fieldBegin></hp:ctrl>'
                '<hp:ctrl><hp:fieldEnd beginIDRef="5"/></hp:ctrl><hp:t> 뒤</hp:t></hp:run>'
                '<hp:linesegarray><hp:lineseg textpos="0"/></hp:linesegarray></hp:p>')
        build(self.p, [body])
        self.assertEqual(postfix._fix_clickhere_guide(self.p), 1)
        x = read(self.p, "Contents/section0.xml")
        self.assertIn('</hp:fieldBegin></hp:ctrl></hp:run><hp:run charPrIDRef="1"><hp:t>FIRSTGUIDE</hp:t></hp:run><hp:run charPrIDRef="0"><hp:ctrl><hp:fieldEnd', x)
        self.assertNotIn("<hp:linesegarray>", x)
        h = read(self.p, "Contents/header.xml")
        self.assertIn('<hh:charProperties itemCnt="2">', h)
        self.assertRegex(h, r'<hh:charPr id="1"[^>]*textColor="#FF0000".*?<hh:italic/>')
        wellformed(self.p)

    def test_c128_table_geometry(self):
        tbl = ('<hp:p><hp:run charPrIDRef="0"><hp:tbl rowCnt="1" colCnt="1"><hp:sz width="1000" widthRelTo="ABSOLUTE" height="68595" heightRelTo="ABSOLUTE" protect="0"/>'
               '<hp:tr><hp:tc><hp:subList/><hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="1000" height="66528"/></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>')
        build(self.p, [tbl])
        old = postfix._hwp5_tables
        postfix._hwp5_tables = lambda src: [[1, 1, 1000, 66528, [(0, 0, 1, 1, 1000, 66528)]]]
        try:
            self.assertEqual(postfix._restore_table_geometry("x.hwp", self.p), 1)
            postfix._hwp5_tables = lambda src: [[2, 1, 1000, 1, [(0, 0, 1, 1, 1000, 1)]]]   # 구조가 다르면 손대지 않는다
            self.assertEqual(postfix._restore_table_geometry("x.hwp", self.p), 0)
        finally:
            postfix._hwp5_tables = old
        self.assertIn('<hp:sz width="1000" widthRelTo="ABSOLUTE" height="66528"', read(self.p, "Contents/section0.xml"))


if __name__ == "__main__":
    unittest.main()
