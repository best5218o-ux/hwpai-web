"""HWPX 정적 구조 검사(C99) — 한글을 열지 않고 OWPML(KS X 6101) 패키지의 필수 구조·참조 무결성·버전 정보를 표준 라이브러리만으로 본다.
목적: 구버전 한글·웹기안기처럼 직접 열어 볼 수 없는 환경에 보내기 전에 「열기 전에 걸러낼 수 있는 구조 결함」을 찾는다.
확인하는 것: ① zip(mimetype 첫 항목·저장 방식·경로 안전·중복) ② container.xml·content.hpf(매니페스트·spine·구역 파일 존재)
③ version.xml(버전 정보 필수 속성) ④ header.xml(필수 refList 묶음·구역 수 secCnt) ⑤ 구역 XML 의 참조 번호(글자·문단 모양·스타일·테두리배경)가 header 에 있는지
⑥ 그림 참조(binaryItemIDRef)가 매니페스트·zip 에 있는지 ⑦ 한컴이 쓰지 않는 추가 항목(참고).
한컴 한글이 저장한 파일을 같은 규칙으로 검사해 기준선과 비교할 수 있다. 이 검사는 「열린다」를 보증하지 않는다 — 열기 성공은 한컴 열기 시험으로만 확인한다.
사용: python -m hwpai.hwpxcheck 파일.hwpx […]  또는  hwpxcheck.check(path) -> {"errors": [...], "warnings": [...], "info": {...}}"""
from __future__ import annotations

import re
import sys
import zipfile
import xml.etree.ElementTree as ET


def _ln(t: str) -> str:
    return t.rsplit("}", 1)[-1]


def check(path: str) -> dict:
    err, warn, info = [], [], {}
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return {"errors": [f"zip 을 열 수 없음: {type(e).__name__}"], "warnings": [], "info": {}}
    with z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        # ① zip
        if not infos or infos[0].filename != "mimetype":
            err.append("mimetype 이 첫 항목이 아님")
        else:
            mi = infos[0]
            if mi.compress_type != zipfile.ZIP_STORED:
                warn.append("mimetype 이 저장(STORED) 방식이 아님")
            if z.read("mimetype").strip() not in (b"application/hwp+zip", b"application/hwpml-package+xml"):
                err.append("mimetype 내용이 HWPX 가 아님: %r" % z.read("mimetype")[:40])
        if len(set(names)) != len(names):
            err.append("같은 이름의 zip 항목이 중복됨")
        for n in names:
            if n.startswith("/") or ".." in n.split("/"):
                err.append(f"안전하지 않은 경로: {n}")
        bad = [i.filename for i in infos if i.compress_type == zipfile.ZIP_DEFLATED and i.compress_size > i.file_size]
        if bad:
            warn.append(f"압축하면 커지는 항목 {len(bad)}개(일부 도구가 보안 오류로 봄): {bad[:2]}")
        # ② container / content.hpf
        hpf_name = "Contents/content.hpf"
        if "META-INF/container.xml" in names:
            try:
                root = ET.fromstring(z.read("META-INF/container.xml"))
                rf = [e.get("full-path") for e in root.iter() if _ln(e.tag) == "rootfile" and "hwpml-package" in (e.get("media-type") or "")]
                if rf:
                    hpf_name = rf[0]
                else:
                    err.append("container.xml 에 패키지 rootfile 이 없음")
            except ET.ParseError:
                err.append("container.xml 이 올바른 XML 이 아님")
        else:
            err.append("META-INF/container.xml 없음")
        manifest, spine = {}, []
        if hpf_name in names:
            try:
                root = ET.fromstring(z.read(hpf_name))
                for e in root.iter():
                    if _ln(e.tag) == "item" and e.get("id"):
                        manifest[e.get("id")] = e.get("href", "")
                    elif _ln(e.tag) == "itemref" and e.get("idref"):
                        spine.append(e.get("idref"))
            except ET.ParseError:
                err.append("content.hpf 가 올바른 XML 이 아님")
        else:
            err.append(f"{hpf_name} 없음")
        for i in spine:
            if i not in manifest:
                err.append(f"spine 이 매니페스트에 없는 항목을 가리킴: {i}")
        secs = [manifest[i] for i in spine if re.search(r"section\d+\.xml$", manifest.get(i, ""))]
        secs = [s if s in names else "Contents/" + s.split("/")[-1] for s in secs]
        for s in secs:
            if s not in names:
                err.append(f"구역 파일이 zip 에 없음: {s}")
        for i, h in manifest.items():
            if h and not h.startswith(("http", "#")) and h not in names and ("Contents/" + h) not in names:
                if i.startswith("image") or "BinData" in h:
                    warn.append(f"매니페스트 그림 항목의 파일이 없음: {h}")
        empty_img = [i for i, h in manifest.items() if i.startswith("image") and not h]
        if empty_img:
            err.append(f"href 가 빈 그림 항목 {len(empty_img)}개(그림 데이터 없음)")
        # ③ version.xml
        if "version.xml" in names:
            try:
                v = ET.fromstring(z.read("version.xml"))
                info["version"] = {k: v.get(k) for k in ("major", "minor", "micro", "xmlVersion", "application", "appVersion")}
                for k in ("major", "minor", "xmlVersion"):
                    if not v.get(k):
                        err.append(f"version.xml 에 {k} 가 없음")
            except ET.ParseError:
                err.append("version.xml 이 올바른 XML 이 아님")
        else:
            err.append("version.xml 없음")
        # ④ header
        ids = {"charPr": set(), "paraPr": set(), "style": set(), "borderFill": set()}
        if "Contents/header.xml" in names:
            try:
                h = ET.fromstring(z.read("Contents/header.xml"))
                if _ln(h.tag) != "head":
                    err.append("header.xml 의 루트가 head 가 아님")
                sc = h.get("secCnt")
                if sc is not None and secs and int(sc) != len(secs):
                    err.append(f"head@secCnt({sc}) 와 구역 파일 수({len(secs)}) 가 다름")
                refl = next((c for c in h if _ln(c.tag) == "refList"), None)
                if refl is None:
                    err.append("refList 없음")
                else:
                    have = {_ln(c.tag) for c in refl}
                    for need in ("fontfaces", "borderFills", "charProperties", "paraProperties", "styles"):
                        if need not in have:
                            err.append(f"refList 에 {need} 없음")
                    for e in refl.iter():
                        n = _ln(e.tag)
                        if n in ids and e.get("id") is not None:
                            ids[n].add(e.get("id"))
            except ET.ParseError:
                err.append("header.xml 이 올바른 XML 이 아님")
        else:
            err.append("Contents/header.xml 없음")
        # ⑤ 구역 참조
        miss = {"charPrIDRef": set(), "paraPrIDRef": set(), "styleIDRef": set(), "borderFillIDRef": set()}
        refmap = {"charPrIDRef": "charPr", "paraPrIDRef": "paraPr", "styleIDRef": "style", "borderFillIDRef": "borderFill"}
        pics = set()
        npar = 0
        for s in secs:
            if s not in names:
                continue
            try:
                for _ev, e in ET.iterparse(__import__("io").BytesIO(z.read(s)), events=("end",)):
                    n = _ln(e.tag)
                    if n == "p":
                        npar += 1
                    for k, kind in refmap.items():
                        v = e.get(k)
                        if v is not None and v != "" and ids[kind] and v not in ids[kind]:
                            miss[k].add(v)
                    if n == "img":
                        r = e.get("binaryItemIDRef")
                        if r:
                            pics.add(r)
                    e.clear()
            except ET.ParseError as ex:
                err.append(f"{s} 가 올바른 XML 이 아님: {str(ex)[:60]}")
        for k, vs in miss.items():
            if vs:
                err.append(f"{k} 가 header 에 없는 번호를 가리킴: {sorted(vs)[:5]}")
        # ⑥ 그림 참조
        for r in sorted(pics):
            if r not in manifest:
                err.append(f"그림 참조 {r} 가 매니페스트에 없음")
        # ⑦ 추가 항목(참고)
        std = {"mimetype", "version.xml", "settings.xml", "Contents/header.xml", "Contents/content.hpf", "META-INF/container.xml", "META-INF/container.rdf",
               "META-INF/manifest.xml", "Preview/PrvText.txt", "Preview/PrvImage.png", "Scripts/headerScripts", "Scripts/sourceScripts"}
        extra = [n for n in names if n not in std and not n.startswith(("BinData/", "Contents/section", "Chart/", "Contents/masterPage", "Contents/history", "Scripts/"))
                 and not n.endswith("/")]
        if extra:
            info["extra_members"] = extra[:5]
        info["sections"] = len(secs)
        info["paragraphs"] = npar
    return {"errors": err, "warnings": warn, "info": info}


if __name__ == "__main__":
    import json
    for p in sys.argv[1:]:
        r = check(p)
        print(p, "오류", len(r["errors"]), "경고", len(r["warnings"]))
        print(json.dumps(r, ensure_ascii=False, indent=1))
