"""문서 속성(메타데이터) 점검 — 본문에 없어도 파일 속성에 남아 있는 작성자·단체·제목 등을 찾는다.

  python -m hwpai meta 문서.hwp [--scrub 결과.hwpx]

읽는 곳
  HWP   요약 정보 스트림(HwpSummaryInformation): 제목·주제·작성자·키워드·설명·마지막 저장자·작성/저장 시각
  HWPX  Contents/content.hpf 메타(title·creator·subject·description·keyword·lastsaveby·날짜), Preview/PrvText.txt(본문 미리보기 글)
「확인 대기」 목록에는 값이 있는 작성자·마지막 저장자·단체명 꼴을 올린다(sens.doc_text 가 본문 뒤에 [문서 속성] 블록으로 붙인다).
가리기(--scrub): HWPX 결과에서 작성자·마지막 저장자·키워드·설명을 비운다(본문은 건드리지 않음). 원본은 바꾸지 않는다.
한계: HWP 요약 정보 스트림은 한글이 쓴 변형 형식이라 값 끝의 쓰레기 바이트를 잘라 읽는다. 암호·배포용 문서는 읽지 못할 수 있다.
"""
from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET

HWP_FIELDS = {2: "제목", 3: "주제", 4: "작성자", 5: "키워드", 6: "설명", 8: "마지막 저장자"}
PERSON_FIELDS = ("작성자", "마지막 저장자")
GENERIC = re.compile(r"^(rhwp|hwpai|hancom office|microsoft|user|owner|admin|administrator|author|unknown|pc|win\d*|hancom|한컴|사용자|관리자|-)$", re.I)
MARK = "[문서 속성]"


def _clean(v) -> str:
    if isinstance(v, bytes):
        v = v.decode("utf-16-le", "ignore")
    v = str(v or "")
    v = v.split("\x00")[0]
    return re.sub(r"[\x00-\x1f]", "", v).strip()


def read_meta(path: str) -> dict:
    """{필드: 값} (값이 있는 것만, 시각은 문자열)."""
    out: dict = {}
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                if "Contents/content.hpf" in z.namelist():
                    root = ET.fromstring(z.read("Contents/content.hpf"))
                    for el in root.iter():
                        tag = el.tag.rsplit("}", 1)[-1]
                        if tag == "title" and (el.text or "").strip():
                            out["제목"] = el.text.strip()
                        elif tag == "meta":
                            nm = (el.get("name") or "").lower()
                            m = {"creator": "작성자", "subject": "주제", "description": "설명", "keyword": "키워드",
                                 "lastsaveby": "마지막 저장자", "createddate": "작성 시각", "modifieddate": "저장 시각"}.get(nm)
                            if m and (el.text or "").strip():
                                out[m] = el.text.strip()
                if "Preview/PrvText.txt" in z.namelist():
                    pv = z.read("Preview/PrvText.txt").decode("utf-8", "ignore").strip()
                    if pv:
                        out["_본문 미리보기 글자수"] = str(len(pv))
        else:
            import olefile
            o = olefile.OleFileIO(path)
            try:
                if o.exists("\x05HwpSummaryInformation"):
                    pr = o.getproperties("\x05HwpSummaryInformation", convert_time=True)
                    for k, name in HWP_FIELDS.items():
                        v = _clean(pr.get(k))
                        if v:
                            out[name] = v
                    for k, name in ((12, "작성 시각"), (13, "저장 시각")):
                        if pr.get(k):
                            out[name] = str(pr[k])[:19]
            finally:
                o.close()
    except Exception as e:  # 읽지 못해도 점검은 계속(속성이 없는 것으로 본다)
        out["_읽기 오류"] = f"{type(e).__name__}"
    return out


def meta_block(meta: dict) -> str:
    """본문 뒤에 붙일 검출용 글 블록. 시각·내부 항목은 제외."""
    rows = [f"{k}: {v}" for k, v in meta.items() if not k.startswith("_") and k not in ("작성 시각", "저장 시각")]
    return ("\n\n" + MARK + "\n" + "\n".join(rows)) if rows else ""


def meta_items(text: str) -> list[dict]:
    """[문서 속성] 블록의 값에서 검출 항목을 만든다(sens.detect 가 부른다)."""
    i = text.find(MARK)
    if i < 0:
        return []
    out, pos = [], i + len(MARK)
    for line in text[pos:].split("\n"):
        m = re.match(r"^(작성자|마지막 저장자|제목|주제|키워드|설명): (.+)$", line)
        ln_start = pos + 1 if False else None
        if m:
            k, v = m.group(1), m.group(2)
            s = text.index(line, pos) + len(k) + 2
            if k in PERSON_FIELDS:
                generic = bool(GENERIC.match(v))
                auto = "추정 비민감" if generic else "의심"
                why = "기본 사용자 이름(프로그램 기본값)으로 보임" if generic else "파일 속성에 남은 작성자 이름 — 본문에 없어도 파일을 건네면 노출됩니다"
                out.append({"kind": "문서속성(" + k + ")", "text": v, "start": s, "end": s + len(v), "auto": auto, "reason": why,
                            "before": k + ": ", "after": ""})
            elif k in ("키워드", "설명") and re.search(r"\d{2,3}-\d{3,4}-\d{4}|@", v):
                out.append({"kind": "문서속성(" + k + ")", "text": v, "start": s, "end": s + len(v), "auto": "의심",
                            "reason": "속성에 연락처 꼴이 있음", "before": k + ": ", "after": ""})
        pos += len(line) + 1
    return out


def scrub_hwpx(src: str, dst: str, fields=("creator", "lastsaveby", "keyword", "description")) -> dict:
    """HWPX 의 content.hpf 속성 값을 비운다(본문은 그대로). 되돌릴 수 없으므로 새 파일에만 쓴다."""
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("원본을 덮어쓸 수 없습니다.")
    cleared = []
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        raw = {i.filename: z.read(i.filename) for i in infos}
    if "Contents/content.hpf" in raw:
        x = raw["Contents/content.hpf"].decode("utf-8")
        for f in fields:
            pat = re.compile(r'(<opf:meta name="%s" content="text">)([^<]+)(</opf:meta>)' % f, re.I)
            m = pat.search(x)
            if m:
                cleared.append(f)
                x = pat.sub(r"\1\3", x)
        raw["Contents/content.hpf"] = x.encode("utf-8")
    with zipfile.ZipFile(dst + ".part", "w") as o:
        for i in infos:
            o.writestr(i, raw[i.filename], compress_type=zipfile.ZIP_STORED if i.filename == "mimetype" else zipfile.ZIP_DEFLATED)
    os.replace(dst + ".part", dst)
    return {"out": dst, "cleared": cleared}


def cmd_meta(a):
    import json
    m = read_meta(a.path)
    print(json.dumps(m, ensure_ascii=False, indent=1))
    if a.scrub:
        src = a.path
        if not zipfile.is_zipfile(src):
            raise SystemExit("--scrub 은 HWPX 에만 씁니다. HWP 는 먼저 변환하세요: hwpai convert")
        print(json.dumps(scrub_hwpx(src, a.scrub), ensure_ascii=False))
    return 0
