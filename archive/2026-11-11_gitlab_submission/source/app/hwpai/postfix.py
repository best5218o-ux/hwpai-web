"""변환 결과 HWPX 뒤처리(데스크톱 엔진 래퍼와 웹 시험판이 함께 쓴다). 엔진(rhwp) 소스는 고치지 않고, 변환본 zip 안 XML·BinData 만 원본 HWP 와 맞춰 바로잡는다.
C86 확장자 없는 그림 복원 · C88 문단 안 마지막 쪽번호 위치 · C90 교정부호 필드 type · C92 주석 안 자동번호 · C93 한컴 기호 코드 · C95 변경 추적 삭제·삽입 이력. 모두 (원본 경로, 변환본 경로)를 받아 바꾼 곳 수를 돌려준다."""
from __future__ import annotations

import os


ERRORS: list = []   # 뒤처리 중 삼킨 오류(웹·점검에서 원인을 볼 수 있게 남긴다)


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _restore_extensionless_images(src, dst):
    """C86: HWP 의 BinData 항목에 확장자가 비어 있으면(옛 저장본) 엔진이 그림 데이터를 HWPX 에 싣지 못하고
    content.hpf 에 href="" 로 빈 항목만 남긴다(그림이 사라진다). 이 경우 원본 BinData 스트림에서 그림 데이터를 꺼내
    그림 형식을 머리 바이트(JPEG·PNG·GIF·BMP)로 확인한 뒤 BinData/imageN.<확장자> 로 넣고 content.hpf 를 고친다.
    형식을 모르면 건드리지 않는다. 고친 개수를 돌려준다(해당 없으면 0). 원본 파일은 바꾸지 않는다."""
    import re, struct, zipfile, zlib
    try:
        with open(src, "rb") as f:
            if f.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return 0
        zin = zipfile.ZipFile(dst)
        hpf = zin.read("Contents/content.hpf").decode("utf-8")
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0
    todo = re.findall(r'<opf:item id="image(\d+)" href="" media-type="application/octet-stream" isEmbeded="0"/>', hpf)
    if not todo:
        zin.close()
        return 0
    try:
        import olefile
        ole = olefile.OleFileIO(src)
    except Exception:
        zin.close()
        return 0
    try:
        fh = ole.openstream("FileHeader").read()
        comp = bool(struct.unpack_from("<I", fh, 36)[0] & 1)
        di = ole.openstream("DocInfo").read()
        if comp:
            di = zlib.decompress(di, -15)
        items = []   # DocInfo 순서대로 (스트림 이름, 압축방식)
        p = 0
        while p + 4 <= len(di):
            h = struct.unpack_from("<I", di, p)[0]; t = h & 0x3FF; sz = h >> 20; p += 4
            if sz == 0xFFF:
                sz = struct.unpack_from("<I", di, p)[0]; p += 4
            if t == 18:
                pl = di[p:p + sz]
                attr = struct.unpack_from("<H", pl, 0)[0]
                if attr & 0xF == 1 and len(pl) >= 6:
                    bid = struct.unpack_from("<H", pl, 2)[0]
                    ln = struct.unpack_from("<H", pl, 4)[0]
                    ext = pl[6:6 + ln * 2].decode("utf-16le", "replace")
                    items.append((f"BIN{bid:04X}" + (("." + ext) if ext else ""), (attr >> 4) & 3, ext))
                else:
                    items.append((None, 0, ""))
            p += sz
        add = {}
        for n in todo:
            i = int(n) - 1
            if not (0 <= i < len(items)) or items[i][0] is None or items[i][2]:
                continue
            name, mode, _ = items[i]
            if not ole.exists("BinData/" + name):
                continue
            b = ole.openstream("BinData/" + name).read()
            if mode == 1 or (mode == 0 and comp):
                try:
                    b = zlib.decompress(b, -15)
                except Exception:
                    pass
            kind = (".jpg", "image/jpeg") if b[:3] == b"\xff\xd8\xff" else (".png", "image/png") if b[:8] == b"\x89PNG\r\n\x1a\n" else (".gif", "image/gif") if b[:4] in (b"GIF8",) else (".bmp", "image/bmp") if b[:2] == b"BM" else None
            if not kind:
                continue
            add[n] = (f"BinData/image{n}{kind[0]}", kind[1], b)
    except Exception:
        add = {}
    finally:
        ole.close()
    if not add:
        zin.close()
        return 0
    new = hpf
    for n, (href, mt, _) in add.items():
        new = new.replace(f'<opf:item id="image{n}" href="" media-type="application/octet-stream" isEmbeded="0"/>',
                          f'<opf:item id="image{n}" href="{href}" media-type="{mt}" isEmbeded="1"/>', 1)
    tmp = dst + ".fix"
    try:
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                data = zin.read(zi.filename)
                if zi.filename == "Contents/content.hpf":
                    data = new.encode("utf-8")
                zout.writestr(zi, data, compress_type=zi.compress_type)
            for href, mt, b in add.values():
                zout.writestr(href, b, compress_type=zipfile.ZIP_DEFLATED)
        zin.close()
        os.replace(tmp, dst)
    except Exception:
        try:
            zin.close()
        except Exception:
            pass
        _rm(tmp)
        return 0
    return len(add)


def _restore_symbol_codepoints(src, dst):
    """C93: 엔진은 원본의 한컴 기호 글꼴 문자(U+A000~AFFF 영역, 예: U+A832)를 사용자 정의 영역 15면(U+F0832)으로 옮겨 저장한다. 한컴 한글 13 이
    같은 원본을 저장한 HWPX 는 원본 코드(U+A832)를 그대로 둔다(한컴 대조 2026-11-10, e09951a7ac17: 4종 40자 대응). 변환본에 U+F0000~F0FFF 문자가
    있고 원본에 대응하는 U+A000대 문자(하위 12비트 같음)가 있을 때만 되돌린다. 바꾼 글자 수를 돌려준다."""
    import re, zipfile
    PL = re.compile("[\U000f0000-\U000f0fff]")
    try:
        zin = zipfile.ZipFile(dst)
        names = [zi.filename for zi in zin.infolist() if zi.filename.startswith("Contents/section") and zi.filename.endswith(".xml")]
        xs = {n: zin.read(n).decode("utf-8") for n in names}
        if not any(PL.search(x) for x in xs.values()):
            return 0
        from . import api as _api
        from .render import plain_text as _pt
        orig = set(c for c in _pt(_api.read(src)) if 0xA000 <= ord(c) <= 0xAFFF)
        if not orig:
            return 0
        cnt = [0]
        def rep(m):
            c = chr(0xA000 | (ord(m.group(0)) & 0xFFF))
            if c in orig:
                cnt[0] += 1
                return c
            return m.group(0)
        patched = {}
        for n, x in xs.items():
            before = cnt[0]
            y = PL.sub(rep, x)
            if cnt[0] != before:
                patched[n] = y.encode("utf-8")
        if not cnt[0]:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        import os
        os.replace(tmp, dst)
        return cnt[0]
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_note_autonum(dst):
    """C92: 엔진은 각주·미주 안의 autoNum num 을 문서 전체 누적 번호로 쓰면서 같은 주석의 footNote/endNote number 는 「쪽마다 다시 시작」 등을
    반영한 값으로 쓴다(restart-page.hwp: number=1,2,1 인데 autoNum num=1,2,3). 한컴 한글 13 의 HWPX 는 둘이 같다(1,2,1, 한컴 대조 2026-11-10).
    주석 요소 안 첫 autoNum(numType 이 FOOTNOTE/ENDNOTE)의 num 을 주석의 number 로 맞춘다. 바꾼 곳 수를 돌려준다."""
    import re, zipfile
    note = re.compile(r'(<hp:(footNote|endNote)\b[^>]*?\bnumber=")(\d+)("[^>]*>)(.*?)(</hp:\2>)', re.S)
    auto = re.compile(r'(<hp:autoNum\b[^>]*?\bnum=")(\d+)("[^>]*?numType="(?:FOOTNOTE|ENDNOTE)")')
    cnt = [0]
    def one(m):
        n = m.group(3)
        def sub(a):
            if a.group(2) == n:
                return a.group(0)
            cnt[0] += 1
            return a.group(1) + n + a.group(3)
        body, k = auto.subn(sub, m.group(5), count=1)
        return m.group(1) + n + m.group(4) + body + m.group(6)
    try:
        zin = zipfile.ZipFile(dst)
        patched = {}
        for zi in zin.infolist():
            if zi.filename.startswith("Contents/section") and zi.filename.endswith(".xml"):
                x = zin.read(zi.filename).decode("utf-8")
                before = cnt[0]
                y = note.sub(one, x)
                if cnt[0] != before:
                    patched[zi.filename] = y.encode("utf-8")
        if not cnt[0]:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        import os
        os.replace(tmp, dst)
        return cnt[0]
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_equation_child_order(dst):
    """C107: 엔진은 <hp:equation> 안에 <hp:script> 를 <hp:sz> 앞에 쓴다. OWPML(EquationType = AbstractShapeObjectType 의
    sz·pos·outMargin·caption·shapeComment 다음에 script)과 한컴 저장본은 script 를 맨 뒤에 둔다. 한컴 열기 시험(2026-11-10,
    58edc88128ce 수식 1,724개)에서 이 순서만 한컴처럼 바꾼 판이 원본과 같은 쪽 수(22)였고 엔진 순서는 23쪽이었다.
    script 를 equation 끝으로 옮기고, protect 가 없는 sz 에 protect="0" 을 붙인다(한컴 표기). 바꾼 수식 수를 돌려준다."""
    import re, zipfile, os
    eq = re.compile(r'(<hp:equation\b[^>]*>)(.*?)(</hp:equation>)', re.S)
    sc = re.compile(r'<hp:script>.*?</hp:script>|<hp:script/>', re.S)
    def fix(m):
        body = m.group(2)
        s1 = sc.search(body)
        if not s1:
            return m.group(0), 0
        rest = body[:s1.start()] + body[s1.end():]
        rest2 = re.sub(r'(<hp:sz\b(?![^>]*\bprotect=)[^>]*?)/>', r'\1 protect="0"/>', rest, count=1)
        new = rest2 + s1.group(0)
        return (m.group(1) + new + m.group(3), 0 if new == body else 1)
    try:
        zin = zipfile.ZipFile(dst)
        patched = {}; total = 0
        for zi in zin.infolist():
            if zi.filename.startswith("Contents/section") and zi.filename.endswith(".xml"):
                x = zin.read(zi.filename).decode("utf-8")
                if "<hp:equation" not in x:
                    continue
                k = [0]
                def f2(m):
                    r, c = fix(m); k[0] += c; return r
                y = eq.sub(f2, x)
                if k[0]:
                    patched[zi.filename] = y.encode("utf-8"); total += k[0]
        if not total:
            zin.close(); return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_negative_out_margin(dst):
    """C106: 엔진이 HWP 바깥 여백 0xFFFF 를 -1 로 읽어 <hp:outMargin left="-1" …> 로 쓰는 경우가 있다(d0800ca0826e 표).
    한컴 한글 2024 가 같은 원본을 저장한 HWPX 440건에는 음수 바깥 여백이 하나도 없고 이 자리는 0 이다(한컴 대조 2026-11-10).
    음수 값만 0 으로 바꾼다. 바꾼 요소 수를 돌려준다."""
    import re, zipfile, os
    pat = re.compile(r'<hp:outMargin ([^>]*?)/>')
    try:
        zin = zipfile.ZipFile(dst)
        patched = {}; total = 0
        for zi in zin.infolist():
            if zi.filename.startswith("Contents/section") and zi.filename.endswith(".xml"):
                x = zin.read(zi.filename).decode("utf-8")
                if '<hp:outMargin left="-' not in x and '="-' not in x:
                    continue
                k = [0]
                def f2(m):
                    b = re.sub(r'="-\d+"', '="0"', m.group(1))
                    if b == m.group(1):
                        return m.group(0)
                    k[0] += 1
                    return f'<hp:outMargin {b}/>'
                y = pat.sub(f2, x)
                if k[0]:
                    patched[zi.filename] = y.encode("utf-8"); total += k[0]
        if not total:
            zin.close(); return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _field_extra_props(src):
    """원본 HWP 필드 컨트롤(%xxx) 머리의 「추가 속성」 바이트를 필드 인스턴스 id 별로 모은다. 실패하면 빈 사전."""
    import struct, zlib
    out = {}
    try:
        with open(src, "rb") as f:
            if f.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return out
        import olefile
        ole = olefile.OleFileIO(src)
        try:
            fh = ole.openstream("FileHeader").read()
            flags = struct.unpack_from("<I", fh, 36)[0]
            if flags & 0x6:
                return out
            si = 0
            while ole.exists(f"BodyText/Section{si}"):
                d = ole.openstream(f"BodyText/Section{si}").read()
                if flags & 1:
                    d = zlib.decompress(d, -15)
                p = 0
                while p + 4 <= len(d):
                    h = struct.unpack_from("<I", d, p)[0]; t = h & 0x3FF; sz = h >> 20; p += 4
                    if sz == 0xFFF:
                        sz = struct.unpack_from("<I", d, p)[0]; p += 4
                    if t == 71 and sz >= 15 and d[p + 3:p + 4] == b"%":
                        n = struct.unpack_from("<H", d, p + 9)[0]
                        q = p + 11 + 2 * n
                        if q + 4 <= p + sz:
                            out[struct.unpack_from("<I", d, q)[0]] = d[p + 8]
                    p += sz
                si += 1
        finally:
            ole.close()
    except Exception as _e:
        ERRORS.append(f"fieldprops {type(_e).__name__}: {str(_e)[:80]}")
    return out


def _fix_field_ids(dst, src=None):
    """C112(후보): 한컴 한글 13(0,0,3901)이 저장한 HWPX 는 모든 fieldBegin 에 zorder·fieldid 를, fieldEnd 에 fieldid 를 쓴다
    (대량 판정 642건 전수, 2026-11-10). fieldid = 필드 컨트롤 ID 4글자를 big-endian 정수로 읽은 값('%%me'=623209829 …),
    zorder = 메모(MEMO)는 문서 안 나타난 순서 1,2,3…, 그 밖은 -1. 누름틀(CLICK_HERE)은 parameters 에 Prop(원본 필드 머리의
    추가 속성 바이트)·Direction(Command 안 안내문)을 더 써 cnt=3 이다(518cb939079e 한컴 저장본). 엔진은 이것들을 쓰지 않는다.
    확인된 7종만 채우고, 이미 있으면 건드리지 않는다. 채운 개수를 돌려준다."""
    import re, zipfile, os
    _cid = {"MEMO": b"%%me", "HYPERLINK": b"%hlk", "CLICK_HERE": b"%clk", "FORMULA": b"%fmu",
            "BOOKMARK": b"%bmk", "DATE": b"%dte", "PATH": b"%pat"}
    props = _field_extra_props(src) if src else {}
    pat = re.compile(r'<hp:fieldBegin\b([^>]*?)(?:/>()|>(.*?)</hp:fieldBegin>)', re.S)
    pend = re.compile(r'<hp:fieldEnd\b([^>]*?)/>')
    try:
        zin = zipfile.ZipFile(dst)
        names = [n for n in zin.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)]
        names.sort(key=lambda n: int(re.sub(r"\D", "", n) or 0))
        patched = {}; total = 0; memo = [0]; bid_type = {}
        def rep(m):
            selfclose = m.group(2) is not None
            a, body = m.group(1), (m.group(3) or "")
            t = re.search(r'\btype="(\w+)"', a)
            i = re.search(r'\bid="(\d+)"', a)
            if not t or t.group(1) not in _cid:
                return m.group(0)
            if i:
                bid_type[i.group(1)] = t.group(1)
            if "fieldid=" not in a and "zorder=" not in a:
                if t.group(1) == "MEMO":
                    memo[0] += 1; z = memo[0]
                else:
                    z = -1
                a = f'{a} zorder="{z}" fieldid="{int.from_bytes(_cid[t.group(1)], "big")}"'
            if t.group(1) == "CLICK_HERE" and i and int(i.group(1)) in props and 'name="Prop"' not in body:
                pm = re.search(r'<hp:parameters cnt="(\d+)"([^>]*)>(.*?)</hp:parameters>', body, re.S)
                cm = re.search(r'Direction:wstring:(\d+):', body)
                if pm and cm:
                    k = int(cm.group(1)); st = cm.end()
                    direc = body[st:st + k]
                    inner = f'<hp:integerParam name="Prop">{props[int(i.group(1))]}</hp:integerParam>' + pm.group(3)
                    inner += f'<hp:stringParam name="Direction">{direc}</hp:stringParam>'
                    body = body[:pm.start()] + f'<hp:parameters cnt="{int(pm.group(1)) + 2}"{pm.group(2)}>{inner}</hp:parameters>' + body[pm.end():]
            if selfclose:
                return f'<hp:fieldBegin{a}/>'
            return f'<hp:fieldBegin{a}>{body}</hp:fieldBegin>'
        def rep_end(m):
            a = m.group(1)
            if "fieldid=" in a:
                return m.group(0)
            b = re.search(r'beginIDRef="(\d+)"', a)
            ty = bid_type.get(b.group(1)) if b else None
            if not ty:
                return m.group(0)
            return f'<hp:fieldEnd{a} fieldid="{int.from_bytes(_cid[ty], "big")}"/>'
        for n in names:
            x = zin.read(n).decode("utf-8")
            y = pat.sub(rep, x)
            y = pend.sub(rep_end, y)
            if y != x:
                patched[n] = y.encode("utf-8"); total += 1
        if not total:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return sum(v.count(b"fieldid=") for v in patched.values())
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_script_manifest_ids(dst):
    """C113: 엔진은 content.hpf 에 문서 스크립트를 id="rhwpHeaderScript"·"rhwpSourceScript" 로 올리고 settings 뒤에 둔다.
    한컴 한글 13(0,0,3901)은 이 id 의 스크립트를 문서 스크립트로 읽지 않아, 변환본을 한글에서 열면 스크립트가 돌지 않고
    다시 저장하면 스크립트가 사라진다(대량 판정: 원본에 스크립트가 남은 13건 모두 변환본 쪽에서 사라짐, 6ba1b5fb0425 은
    스크립트가 채우는 연도 2026 대신 저장값 2010). 한컴 저장본과 같은 id(headersc·sourcesc)·순서(스크립트 다음 settings)로 바꾼다."""
    import re, zipfile, os
    try:
        zin = zipfile.ZipFile(dst)
        if "Contents/content.hpf" not in zin.namelist():
            return 0
        x = zin.read("Contents/content.hpf").decode("utf-8")
        if "rhwpHeaderScript" not in x and "rhwpSourceScript" not in x:
            return 0
        y = x.replace('"rhwpHeaderScript"', '"headersc"').replace('"rhwpSourceScript"', '"sourcesc"')
        m = re.search(r'(<opf:item id="settings"[^>]*/>)((?:<opf:item id="(?:headersc|sourcesc)"[^>]*/>)+)', y)
        if m:
            y = y[:m.start()] + m.group(2) + m.group(1) + y[m.end():]
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                data = y.encode("utf-8") if zi.filename == "Contents/content.hpf" else zin.read(zi.filename)
                zout.writestr(zi, data, compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return 1
    except Exception as _e:
        ERRORS.append(f"script-manifest {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _hwp_char_counts(src, codes):
    """원본 HWP 본문 PARA_TEXT 에서 주어진 UTF-16 코드들의 개수. 읽지 못하면 None."""
    import struct, zlib
    try:
        with open(src, "rb") as f:
            if f.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return None
        import olefile
        ole = olefile.OleFileIO(src)
        try:
            fl = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)[0]
            if fl & 0x6:
                return None
            cnt = {c: 0 for c in codes}; si = 0
            while ole.exists(f"BodyText/Section{si}"):
                d = ole.openstream(f"BodyText/Section{si}").read()
                if fl & 1:
                    d = zlib.decompress(d, -15)
                p = 0
                while p + 4 <= len(d):
                    h = struct.unpack_from("<I", d, p)[0]; t = h & 0x3FF; sz = h >> 20; p += 4
                    if sz == 0xFFF:
                        sz = struct.unpack_from("<I", d, p)[0]; p += 4
                    if t == 67:
                        w = struct.unpack_from(f"<{sz // 2}H", d, p)
                        for c in codes:
                            cnt[c] += w.count(c)
                    p += sz
                si += 1
            return cnt
        finally:
            ole.close()
    except Exception as _e:
        ERRORS.append(f"charcount {type(_e).__name__}: {str(_e)[:80]}")
        return None


def _fix_soft_hyphen(src, dst):
    """C114: HWP 문자 24(하이픈 제어 문자)를 엔진이 어떤 문단에서는 <hp:hypen/>(한컴 표기)로, 어떤 문단에서는 글자 U+00AD 로
    쓴다(c9ef76195394: 원본 문자24 12개 → 변환본 U+00AD 12개, 한컴 저장본은 <hp:hypen/> 12개). 원본에 글자 U+00AD 가 하나도 없고
    「변환본 U+00AD 수 + <hp:hypen/> 수 = 원본 문자24 수」일 때만 변환본의 U+00AD 를 <hp:hypen/> 으로 바꾼다. 바꾼 수를 돌려준다."""
    import re, zipfile, os
    cnt = _hwp_char_counts(src, (24, 0xAD))
    if not cnt or cnt[0xAD] != 0 or cnt[24] == 0:
        return 0
    try:
        zin = zipfile.ZipFile(dst)
        names = [n for n in zin.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)]
        texts = {n: zin.read(n).decode("utf-8") for n in names}
        shy = sum(t.count("\u00ad") for t in texts.values()); hy = sum(t.count("<hp:hypen/>") for t in texts.values())
        if shy == 0 or shy + hy != cnt[24]:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                data = texts[zi.filename].replace("\u00ad", "<hp:hypen/>").encode("utf-8") if zi.filename in texts else zin.read(zi.filename)
                zout.writestr(zi, data, compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return shy
    except Exception as _e:
        ERRORS.append(f"softhyphen {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_caret_position(src, dst):
    """C115: 엔진은 settings.xml 의 커서 위치를 늘 listIDRef=0 paraIDRef=0 pos=16 으로 쓴다. 원본 HWP 의 DocInfo 문서 속성
    (DOCUMENT_PROPERTIES)에는 실제 커서 위치(목록 id·문단 id·글자 위치)가 있고, 한컴 저장본은 이 값을 그대로 쓴다.
    한컴 한글 13 은 연 문서의 커서가 누름틀 안에 놓이면 누름틀 안내문을 본문 글로 넣어 저장한다(518cb939079e·f8fc3f24f7c4:
    「제목 입력」 9자가 생김 — settings.xml 만 한컴 저장본 것으로 바꾸면 사라짐, 2026-11-10 시험18). 원본 값으로 바꾼다."""
    import re, struct, zlib, zipfile, os
    try:
        with open(src, "rb") as f:
            if f.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return 0
        import olefile
        ole = olefile.OleFileIO(src)
        try:
            fl = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)[0]
            if fl & 0x6:
                return 0
            d = ole.openstream("DocInfo").read()
        finally:
            ole.close()
        if fl & 1:
            d = zlib.decompress(d, -15)
        h = struct.unpack_from("<I", d, 0)[0]
        if h & 0x3FF != 16 or (h >> 20) < 26:
            return 0
        lst, para, pos = struct.unpack_from("<3I", d, 4 + 14)
        zin = zipfile.ZipFile(dst)
        if "settings.xml" not in zin.namelist():
            return 0
        x = zin.read("settings.xml").decode("utf-8")
        new = f'<ha:CaretPosition listIDRef="{lst}" paraIDRef="{para}" pos="{pos}"/>'
        y, k = re.subn(r'<ha:CaretPosition\b[^>]*/>', new, x)
        if not k or y == x:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, y.encode("utf-8") if zi.filename == "settings.xml" else zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return 1
    except Exception as _e:
        ERRORS.append(f"caret {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_note_suffix(src, dst):
    """C117: 원본 HWP 의 각주·미주 모양(FOOTNOTE_SHAPE, 구역마다 각주·미주 순서로 1개씩)의 앞·뒤 장식 문자가 0(없음)이어도
    엔진은 suffixChar=")" 를 쓴다. 한컴 저장본은 "" — 화면의 각주 번호가 「1」 대신 「1)」로 바뀐다(대량 판정 70문서,
    032b5fc93b1f 각주 230개). 구역별 원본 값으로 footNotePr·endNotePr 와 본문 안 각주·미주 번호(autoNum FOOTNOTE/ENDNOTE)의
    prefixChar·suffixChar 를 맞춘다. 바꾼 곳 수를 돌려준다."""
    import re, struct, zlib, zipfile, os
    try:
        with open(src, "rb") as f:
            if f.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return 0
        import olefile
        ole = olefile.OleFileIO(src)
        shapes = {}
        try:
            fl = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)[0]
            if fl & 0x6:
                return 0
            si = 0
            while ole.exists(f"BodyText/Section{si}"):
                d = ole.openstream(f"BodyText/Section{si}").read()
                if fl & 1:
                    d = zlib.decompress(d, -15)
                p = 0; recs = []
                while p + 4 <= len(d) and len(recs) < 2:
                    h = struct.unpack_from("<I", d, p)[0]; t = h & 0x3FF; sz = h >> 20; p += 4
                    if sz == 0xFFF:
                        sz = struct.unpack_from("<I", d, p)[0]; p += 4
                    if t == 74 and sz >= 10:
                        _a, _u, pre, suf = struct.unpack_from("<I3H", d, p)
                        recs.append((chr(pre) if pre else "", chr(suf) if suf else ""))
                    p += sz
                if len(recs) == 2:
                    shapes[si] = recs
                si += 1
        finally:
            ole.close()
        if not shapes:
            return 0
        from xml.sax.saxutils import escape as _esc
        zin = zipfile.ZipFile(dst); patched = {}; total = [0]
        for n in zin.namelist():
            m = re.fullmatch(r"Contents/section(\d+)\.xml", n)
            if not m or int(m.group(1)) not in shapes:
                continue
            (fpre, fsuf), (epre, esuf) = shapes[int(m.group(1))]
            x = zin.read(n).decode("utf-8")
            def setfmt(tag, pre, suf):
                def r(mm):
                    t = mm.group(0)
                    t2 = re.sub(r'prefixChar="[^"]*"', f'prefixChar="{_esc(pre, {chr(34): "&quot;"})}"', t)
                    t2 = re.sub(r'suffixChar="[^"]*"', f'suffixChar="{_esc(suf, {chr(34): "&quot;"})}"', t2)
                    if t2 != t:
                        total[0] += 1
                    return t2
                return r
            y = re.sub(r'(?<=<hp:footNotePr>)<hp:autoNumFormat [^>]*/>', setfmt("f", fpre, fsuf), x)
            y = re.sub(r'(?<=<hp:endNotePr>)<hp:autoNumFormat [^>]*/>', setfmt("e", epre, esuf), y)
            y = re.sub(r'(?<=numType="FOOTNOTE">)<hp:autoNumFormat [^>]*/>', setfmt("f", fpre, fsuf), y)
            y = re.sub(r'(?<=numType="ENDNOTE">)<hp:autoNumFormat [^>]*/>', setfmt("e", epre, esuf), y)
            # 각주·미주 컨트롤 자체의 장식 문자(HWP 컨트롤 머리의 값)는 한컴이 쓰지 않는다 — 엔진이 suffixChar="41" 로 실으면 한컴은
            # 번호를 「1)」로 보인다(032b5fc93b1f). 한컴 저장본과 같게 뺀다.
            y2 = re.sub(r'(<hp:(?:footNote|endNote)\b[^>]*?) suffixChar="\d*"', r'\1', y)
            if y2 != y:
                total[0] += 1
            y = y2
            if y != x:
                patched[n] = y.encode("utf-8")
        if not patched:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total[0]
    except Exception as _e:
        ERRORS.append(f"notesuffix {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_column_enums(dst):
    """C116: 다단 정의(colPr)의 단 종류를 엔진이 OWPML 표기가 아닌 「BalancedNewspaper」·「Parallel」로 써서 한컴이 일반 다단
    (NEWSPAPER)으로 읽는다 — 균형 다단이 풀려 쪽 수가 달라짐(71c23f5e9201 7→8쪽). 또 단 사이 구분선(colLine)의 점선·파선을
    서로 바꿔 쓴다(대량 판정 짝 비교: 한컴 DASH↔엔진 DOT 25곳, 한컴 DOT↔엔진 DASH 1곳, 실선·동그라미는 일치).
    한컴 표기(BALANCED_NEWSPAPER·PARALLEL)와 맞는 선 종류로 바로잡는다. 바꾼 곳 수를 돌려준다."""
    import re, zipfile, os
    try:
        zin = zipfile.ZipFile(dst); patched = {}; total = 0
        for n in zin.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", n):
                continue
            x = zin.read(n).decode("utf-8")
            y = x.replace('<hp:colPr id="" type="BalancedNewspaper"', '<hp:colPr id="" type="BALANCED_NEWSPAPER"')
            y = re.sub(r'(<hp:colPr\b[^>]*\btype=")BalancedNewspaper"', r'\1BALANCED_NEWSPAPER"', y)
            y = re.sub(r'(<hp:colPr\b[^>]*\btype=")Parallel"', r'\1PARALLEL"', y)
            y = re.sub(r'<hp:colLine type="(DOT|DASH)"', lambda m: '<hp:colLine type="%s"' % ("DASH" if m.group(1) == "DOT" else "DOT"), y)
            if y != x:
                total += sum(1 for a, b in zip(re.findall(r"<hp:col(?:Pr|Line)\b[^>]*>", x), re.findall(r"<hp:col(?:Pr|Line)\b[^>]*>", y)) if a != b)
                patched[n] = y.encode("utf-8")
        if not patched:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total
    except Exception as _e:
        ERRORS.append(f"colenum {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_column_widths(src, dst):
    """C118: 단 너비를 따로 정한 다단(colPr sameSz="0")을 엔진이 단 너비(colSz) 없이 써서, 한컴이 단 너비를 0 에 가깝게 잡아
    표가 납작해지고 쪽이 늘어난다(87ac4934e661 구역3: 원본 colSz width=32768 gap=0, 13→14쪽). 원본 HWP 의 다단 정의(cold)
    컨트롤에서 단마다 (너비, 간격)을 읽어 같은 순서의 colPr 에 넣는다. 구역별 개수가 맞을 때만. 채운 colPr 수를 돌려준다."""
    import re, struct, zlib, zipfile, os
    try:
        with open(src, "rb") as f:
            if f.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return 0
        import olefile
        ole = olefile.OleFileIO(src); cols = {}
        try:
            fl = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)[0]
            if fl & 0x6:
                return 0
            si = 0
            while ole.exists(f"BodyText/Section{si}"):
                d = ole.openstream(f"BodyText/Section{si}").read()
                if fl & 1:
                    d = zlib.decompress(d, -15)
                p = 0; lst = []
                while p + 4 <= len(d):
                    h = struct.unpack_from("<I", d, p)[0]; t = h & 0x3FF; sz = h >> 20; p += 4
                    if sz == 0xFFF:
                        sz = struct.unpack_from("<I", d, p)[0]; p += 4
                    if t == 71 and d[p:p + 4] == b"dloc" and sz >= 8:
                        attr = struct.unpack_from("<H", d, p + 4)[0]; cnt = (attr >> 2) & 0xFF; same = (attr >> 12) & 1
                        ws = []
                        if not same and sz >= 8 + 4 * cnt:
                            ws = [struct.unpack_from("<2H", d, p + 8 + 4 * k) for k in range(cnt)]
                        lst.append(ws)
                    p += sz
                cols[si] = lst
                si += 1
        finally:
            ole.close()
        zin = zipfile.ZipFile(dst); patched = {}; total = 0
        for n in zin.namelist():
            m = re.fullmatch(r"Contents/section(\d+)\.xml", n)
            if not m or int(m.group(1)) not in cols:
                continue
            lst = cols[int(m.group(1))]
            x = zin.read(n).decode("utf-8")
            found = list(re.finditer(r"<hp:colPr\b[^>]*?(/?)>", x))
            if len(found) != len(lst):
                continue
            out = []; last = 0
            for mm, ws in zip(found, lst):
                tag = mm.group(0)
                if mm.group(1) == "/" and 'sameSz="0"' in tag and ws:
                    out.append(x[last:mm.start()])
                    out.append(tag[:-2] + ">" + "".join(f'<hp:colSz width="{w}" gap="{g}"/>' for w, g in ws) + "</hp:colPr>")
                    last = mm.end(); total += 1
            if last:
                out.append(x[last:])
                patched[n] = "".join(out).encode("utf-8")
        if not patched:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total
    except Exception as _e:
        ERRORS.append(f"colwidth {type(_e).__name__}: {str(_e)[:80]}")
        return 0


_EQ_SIG = {(1125, 78): (900, 86), (1163, 79): (1050, 88), (1190, 74): (1078, 71), (1305, 81): (1080, 88), (1584, 85): (1362, 91)}


def _fix_equation_sizes(dst):
    """C121(기본 켜짐, 끄려면 HWPAI_EQSIZE=0): 옛 한글 수식 조판으로 저장된 수식 크기를 한글 2024 값으로 바꾼다.
    한글은 HWP 를 열 때 수식 크기를 다시 계산하지만 HWPX 는 저장값을 쓴다(58edc88128ce 22 대 23쪽).
    저장소 2,286건 수식 51,745개를 한컴 저장본과 대조: 기준 크기 900 에서 높이·기준선 (1125,78)·(1163,79)·(1190,74)·
    (1305,81)·(1584,85) 는 한컴이 맞게 계산한 수식에는 한 번도 없고, 낡은 문서에만 있다(→ 각각 (900,86)·(1050,88)·(1078,71)·
    (1080,88)·(1362,91)). 이 표지가 5개 이상인 문서만 고치고, 그 문서의 수식은 프라임 하나에 너비 150 을 더한다
    (한컴 대조 1,384건 일관). 대조 결과: 바뀐 수식 중 맞던 수식 0, 한컴 값과 같아진 수식 1,380, 가까워진 수식 245, 멀어진 수식 0.
    바꾼 수식 수를 돌려준다."""
    import re, zipfile, os
    try:
        zin = zipfile.ZipFile(dst)
        secs = [n for n in zin.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)]
        texts = {n: zin.read(n).decode("utf-8") for n in secs}
        eqre = re.compile(r'<hp:equation\b([^>]*)>(.*?)</hp:equation>', re.S)
        def parts(a, b):
            bu = re.search(r'baseUnit="(\d+)"', a); bl = re.search(r'baseLine="(\d+)"', a)
            sz = re.search(r'<hp:sz width="(\d+)"([^>]*?)height="(\d+)"', b)
            return (bu.group(1) if bu else None, int(bl.group(1)) if bl else None, sz)
        sig = 0
        for x in texts.values():
            for m in eqre.finditer(x):
                bu, bl, sz = parts(m.group(1), m.group(2))
                if bu == "900" and sz and bl is not None and (int(sz.group(3)), bl) in _EQ_SIG:
                    sig += 1
        if sig < 5:
            zin.close(); return 0
        total = [0]
        def rep(m):
            a, b = m.group(1), m.group(2)
            bu, bl, sz = parts(a, b)
            if bu != "900" or not sz:
                return m.group(0)
            w, h = int(sz.group(1)), int(sz.group(3))
            sc = re.search(r'<hp:script>(.*?)</hp:script>', b, re.S)
            scr = sc.group(1).replace("&apos;", "'") if sc else ""
            nprime = scr.count("'") + len(re.findall(r'\bprime\b', scr)) + scr.count("\u2032")
            nw, nh, nbl = w + 150 * nprime, h, bl
            if bl is not None and (h, bl) in _EQ_SIG:
                nh, nbl = _EQ_SIG[(h, bl)]
            if (nw, nh, nbl) == (w, h, bl):
                return m.group(0)
            total[0] += 1
            b2 = b[:sz.start()] + f'<hp:sz width="{nw}"{sz.group(2)}height="{nh}"' + b[sz.end():]
            a2 = re.sub(r'baseLine="\d+"', f'baseLine="{nbl}"', a) if nbl != bl else a
            return f'<hp:equation{a2}>{b2}</hp:equation>'
        patched = {}
        for n, x in texts.items():
            y = eqre.sub(rep, x)
            if y != x:
                patched[n] = y.encode("utf-8")
        if not patched:
            zin.close(); return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total[0]
    except Exception as _e:
        ERRORS.append(f"eqsize {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_foreign_lineseg(dst):
    """C120: 한컴이 아닌 생성기가 만든 HWP 의 줄 배치 저장값(lineseg)은 한컴 조판과 다르다. 한컴은 HWP 를 열 때 줄 배치를
    다시 계산하지만 HWPX 를 열 때는 저장값을 그대로 쓴다(ccd56fa8bfe9: 저장값 6,952줄 대 한컴 재계산 7,786줄, 한컴 쪽 176 대 197;
    저장값을 지운 판 197 — 시험26). 저장값을 모든 문서에서 지우면 한컴 쪽 수가 원본과 달라지는 문서가 생긴다(시험27).
    표지 두 가지가 모두 있을 때만 지운다: ① 글꼴 이름이 한글 이름 대신 영문 별칭(Batang·Gulim·Dotum·Gungsuh 계열)으로 저장됨
    ② 이어지는 줄에 한컴 줄 나눔 표지가 거의 없음. 시험27(한글 2024, 저장소 2,286건 전체를 저장값 없이 연 판): 전체에 적용하면
    원본과 쪽 수가 같아지는 문서 1·달라지는 문서 23 → 기각. 두 표지가 모두 있는 문서 8건은 저장값 없이도 모두 원본과 같고
    그중 ccd56fa8bfe9 는 176→197(원본과 같음). 지운 문단 수를 돌려준다."""
    import re, zipfile, os
    try:
        zin = zipfile.ZipFile(dst)
        hd = zin.read("Contents/header.xml").decode("utf-8", "ignore")
        if not re.search(r'<hh:font id="\d+" face="(?:Batang|Gulim|Dotum|Gungsuh)(?:Che)?"', hd):
            zin.close(); return 0
        # 둘째 표지: 한컴이 직접 계산한 줄 배치는 이어지는 줄(textpos>0)에 줄 나눔 표지(flags 비트 20)를 남긴다.
        # 이어지는 줄 가운데 이 표지가 5% 미만이면 저장값을 한컴이 계산하지 않은 것으로 본다(ccd56fa8bfe9 0.2%, 50094a3db2b2 63%).
        cont = mark = 0
        for n in zin.namelist():
            if re.fullmatch(r"Contents/section\d+\.xml", n):
                for tp, fl in re.findall(r'<hp:lineseg textpos="(\d+)"[^>]*flags="(\d+)"', zin.read(n).decode("utf-8", "ignore")):
                    if int(tp) > 0:
                        cont += 1; mark += (int(fl) >> 20) & 1
        if cont < 10 or mark >= 0.05 * cont:
            zin.close(); return 0
        patched = {}; total = 0
        for n in zin.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", n):
                continue
            x = zin.read(n).decode("utf-8")
            y, k = re.subn(r"<hp:linesegarray>.*?</hp:linesegarray>", "", x, flags=re.S)
            if k:
                patched[n] = y.encode("utf-8"); total += k
        if not patched:
            zin.close(); return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total
    except Exception as _e:
        ERRORS.append(f"foreignlineseg {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_shadow_margin(dst):
    """C119: 그림자(평행 그림자)가 있는 그리기 개체는 HWP 의 바깥 여백에 그림자 몫이 들어 있다(87bb1bcb00a8·a62026b57b3f:
    원본 여백 0,600,0,600). 한컴 저장본은 이 개체의 바깥 여백을 0 으로 쓰고, 엔진처럼 600 을 그대로 두면 한컴에서 1쪽이 늘어난다
    (시험22: 0 으로 바꾸면 5쪽·6쪽 원본과 같아짐). 저장소 2,286건 중 해당 개체는 이 4개뿐이며 한컴 저장본 모두 0.
    그림자 종류가 NONE 이 아닌 그리기 개체(rect·ellipse·polygon·arc·curve)의 바깥 여백을 0 으로 쓴다. 바꾼 수를 돌려준다."""
    import re, zipfile, os
    pat = re.compile(r'<hp:(rect|ellipse|polygon|arc|curve)\b(?:(?!<hp:(?:rect|ellipse|polygon|arc|curve)\b).)*?</hp:\1>', re.S)
    try:
        zin = zipfile.ZipFile(dst); patched = {}; total = [0]
        def rep(m):
            t = m.group(0)
            sh = re.search(r'<hp:shadow type="(\w+)"', t)
            if not sh or sh.group(1) == "NONE":
                return t
            t2 = re.sub(r'<hp:outMargin left="\d+" right="\d+" top="\d+" bottom="\d+"/>', '<hp:outMargin left="0" right="0" top="0" bottom="0"/>', t)
            if t2 != t:
                total[0] += 1
            return t2
        for n in zin.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", n):
                continue
            x = zin.read(n).decode("utf-8")
            if "<hp:shadow" not in x:
                continue
            y = pat.sub(rep, x)
            if y != x:
                patched[n] = y.encode("utf-8")
        if not patched:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total[0]
    except Exception as _e:
        ERRORS.append(f"shadowmargin {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_revision_sign_field(dst):
    """C90: 엔진은 command 가 $RevisionSign 인 필드(교정부호 표시)를 type=CROSSREF(상호참조)로 저장한다. 한컴 한글 13(0,0,3901)이 같은 원본을
    저장한 HWPX 는 같은 필드를 type=PROOFREADING_MARKS_SIGN 으로 쓴다(한컴 대조 2026-11-10, 84d297375c48). command 가 $RevisionSign 인
    fieldBegin 의 type 만 바꾼다. 바꾼 개수를 돌려준다."""
    import re, zipfile
    # C104: 한컴 열기 시험(한글 2024, 2026-11-10, d456f515e66bb3e9)에서 한컴이 저장한 HWPX 로 $RevisionClipping → PROOFREADING_MARKS_CLIPPING 확인.
    pat = re.compile(r'(<hp:fieldBegin\b[^>]*?\btype=")CROSSREF("[^>]*>(?:(?!</hp:fieldBegin>).)*?\$Revision(Sign|Clipping))', re.S)
    _map = {"Sign": "PROOFREADING_MARKS_SIGN", "Clipping": "PROOFREADING_MARKS_CLIPPING"}
    try:
        zin = zipfile.ZipFile(dst)
        patched = {}; total = 0
        for zi in zin.infolist():
            if zi.filename.startswith("Contents/section") and zi.filename.endswith(".xml"):
                x = zin.read(zi.filename).decode("utf-8")
                y, k = pat.subn(lambda m: m.group(1) + _map[m.group(3)] + m.group(2), x)
                if k:
                    patched[zi.filename] = y.encode("utf-8"); total += k
        if not total:
            return 0
        tmp = dst + ".tmp"
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        import os
        os.replace(tmp, dst)
        return total
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_last_page_number_pos(src, dst):
    """C88: HWP 한 문단에 쪽번호 위치(pgnp) 컨트롤이 여러 개이면 화면에는 마지막 것이 적용된다(rhwp 조판 규칙: 뒤의 위치가 앞의 위치를
    덮는다). 엔진의 HWPX 저장은 문단당 하나로 접으면서 첫 번째를 남겨, 쪽번호가 사라지거나 없던 쪽번호가 생긴다(실수집 12문서).
    원본 BodyText 에서 「pgnp 가 있는 문단」 순서와 변환본 section 의 pageNum 개수가 정확히 같을 때만, 그 문단의 pageNum 을
    마지막 pgnp 값으로 바꾼다. 개수가 다르면 건드리지 않는다. 바꾼 곳 수를 돌려준다."""
    import re, struct, zipfile, zlib
    try:
        with open(src, "rb") as f:
            if f.read(8) != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return 0
        import olefile
        ole = olefile.OleFileIO(src)
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0
    fixes = {}   # section index -> [(문단순서 번호, 마지막 pgnp 값)] , 문단 순서 목록은 별도
    per_section = {}
    try:
        fh = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", fh, 36)[0]
        if flags & 0x4 or flags & 0x2:
            return 0   # 배포용·암호 문서는 건드리지 않는다
        comp = bool(flags & 1)
        si = 0
        while ole.exists(f"BodyText/Section{si}"):
            d = ole.openstream(f"BodyText/Section{si}").read()
            if comp:
                d = zlib.decompress(d, -15)
            groups = {}         # 문단 번호 -> [(attr, dash)...]
            seq = []            # 변환본에 pageNum 이 나오는 순서(문단마다 첫 pgnp 자리)
            at_level = {}       # PARA_HEADER 레벨 -> 현재 문단 번호
            npara = 0
            p = 0
            while p + 4 <= len(d):
                h = struct.unpack_from("<I", d, p)[0]; t = h & 0x3FF; lv = (h >> 10) & 0x3FF; sz = h >> 20; p += 4
                if sz == 0xFFF:
                    sz = struct.unpack_from("<I", d, p)[0]; p += 4
                if t == 66:   # PARA_HEADER
                    npara += 1
                    at_level[lv] = npara
                    for k in [k for k in at_level if k > lv]:
                        del at_level[k]
                elif t == 71 and sz >= 16 and d[p:p + 4] == b"pgnp"[::-1]:
                    pid = at_level.get(lv - 1)
                    if pid is None:
                        return 0
                    if pid not in groups:
                        groups[pid] = []
                        seq.append(pid)
                    groups[pid].append((struct.unpack_from("<I", d, p + 4)[0], struct.unpack_from("<H", d, p + 14)[0]))
                p += sz
            paras = [groups[k] for k in seq]
            per_section[si] = paras
            si += 1
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0
    finally:
        ole.close()
    return _apply_pgnp_fix(dst, per_section)


def _apply_pgnp_fix(dst, per_section):
    import re, zipfile
    POS = ["NONE", "TOP_LEFT", "TOP_CENTER", "TOP_RIGHT", "BOTTOM_LEFT", "BOTTOM_CENTER", "BOTTOM_RIGHT", "OUTSIDE_TOP", "OUTSIDE_BOTTOM", "INSIDE_TOP", "INSIDE_BOTTOM"]
    FMT = {1: "CIRCLED_DIGIT", 2: "ROMAN_CAPITAL", 3: "ROMAN_SMALL", 4: "LATIN_CAPITAL", 5: "LATIN_SMALL", 6: "CIRCLED_LATIN_CAPITAL",
           7: "CIRCLED_LATIN_SMALL", 8: "HANGUL_SYLLABLE", 9: "CIRCLED_HANGUL_SYLLABLE", 10: "HANGUL_JAMO", 11: "CIRCLED_HANGUL_JAMO",
           12: "HANGUL_PHONETIC", 13: "IDEOGRAPH", 14: "CIRCLED_IDEOGRAPH", 15: "DECAGON_CIRCLE", 16: "DECAGON_CIRCLE_HANJA", 0x80: "SYMBOL", 0x81: "USER_CHAR"}
    if not any(len(l) > 1 and l[0] != l[-1] for lst in per_section.values() for l in lst):
        return 0
    rx = re.compile(r'<hp:ctrl><hp:pageNum pos="[^"]*" formatType="[^"]*" sideChar="[^"]*"/></hp:ctrl>')
    try:
        zin = zipfile.ZipFile(dst)
    except Exception as _e:
        ERRORS.append(f"{type(_e).__name__}: {str(_e)[:80]}")
        return 0
    patched = {}
    total = 0
    for si, plist in per_section.items():
        name = f"Contents/section{si}.xml"
        if name not in zin.namelist():
            if plist:
                zin.close(); return 0
            continue
        xml = zin.read(name).decode("utf-8")
        found = list(rx.finditer(xml))
        if len(found) != len(plist):
            continue   # 개수가 다르면 이 구역은 건드리지 않는다
        out = []; last = 0; n = 0
        for m, lst in zip(found, plist):
            if len(lst) > 1 and lst[0] != lst[-1]:
                attr, dash = lst[-1]
                pos = POS[(attr >> 8) & 0xF] if ((attr >> 8) & 0xF) < len(POS) else "BOTTOM_CENTER"
                fmt = FMT.get(attr & 0xFF, "DIGIT")
                ch = chr(dash) if dash else ""
                side = "" if (not ch or ch.isspace()) else ch.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
                out.append(xml[last:m.start()]); out.append(f'<hp:ctrl><hp:pageNum pos="{pos}" formatType="{fmt}" sideChar="{side}"/></hp:ctrl>')
                last = m.end(); n += 1
        if n:
            out.append(xml[last:]); patched[name] = "".join(out).encode("utf-8"); total += n
    if not patched:
        zin.close()
        return 0
    tmp = dst + ".fix2"
    try:
        with zipfile.ZipFile(tmp, "w") as zout:
            for zi in zin.infolist():
                zout.writestr(zi, patched.get(zi.filename, None) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
    except Exception:
        try:
            zin.close()
        except Exception:
            pass
        _rm(tmp)
        return 0
    return total




def _strip_linesegarray(dst):
    """C98(선택): 변환본의 줄 배치 캐시(hp:linesegarray)를 모두 지워 한글이 열 때 줄을 다시 나누게 한다. 환경변수 HWPAI_LINESEG=strip 일 때만 한다(기본 keep).
    근거: 엔진이 쓴 캐시가 낡은 문단이 있으면(독립 검증기 3/446 문서) 한글이 그 캐시를 그대로 써 글이 겹쳐 보일 수 있고, rhwp 렌더로 쪽 수를 세면
    쪽 수 불일치 13건 중 4건은 정확히 맞고 2건은 가까워졌지만 1건(34929d45c3b0)은 216→235 로 나빠졌고, 438건 전체로는 한컴 쪽 수 일치가
    425 → 329 로 떨어졌다(rhwp 렌더 기준). 그래서 기본은 keep. 한글이 실제로 어느 쪽을 더 맞게 보여 주는지는 한컴 열기 시험의 「변형_줄배치제거」 세트로 가린다."""
    import re, zipfile
    if os.environ.get("HWPAI_LINESEG", "keep").lower() != "strip":
        return 0
    try:
        zin = zipfile.ZipFile(dst)
        names = [i.filename for i in zin.infolist()]
        pat = re.compile(rb"<hp:linesegarray>.*?</hp:linesegarray>", re.S)
        newd, n = {}, 0
        for nm in names:
            if re.fullmatch(r"Contents/section\d+\.xml", nm):
                d = zin.read(nm)
                d2, k = pat.subn(b"", d)
                if k:
                    newd[nm] = d2
                    n += k
        if not n:
            zin.close()
            return 0
        tmp = dst + ".ls"
        with zipfile.ZipFile(tmp, "w") as zo:
            for i in zin.infolist():
                zi = zipfile.ZipInfo(i.filename, i.date_time)
                zi.external_attr = i.external_attr
                zi.compress_type = i.compress_type
                zo.writestr(zi, newd.get(i.filename, zin.read(i.filename)))
        zin.close()
        os.replace(tmp, dst)
        return n
    except Exception as _e:
        ERRORS.append(f"lineseg {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_borderfill_zero(dst):
    """C99: HWP5 의 테두리·배경 번호 0 은 「없음」인데 HWPX 의 refList 는 1 부터 시작해 0 번 항목이 없다. 엔진이 그 0 을 그대로 써서
    표·쪽 테두리가 header 에 없는 번호를 가리켰다(정적 구조 검사: 446개 중 55개, 한컴 저장본은 0개). 모든 선이 NONE 이고 채움이 없는 항목을
    끝에 하나 덧붙이고 0 인 참조를 그 번호로 바꾼다. 해당 없으면 건드리지 않는다. 바꾼 참조 수를 돌려준다."""
    import re
    import zipfile
    try:
        zin = zipfile.ZipFile(dst)
        names = [i.filename for i in zin.infolist()]
        secs = [n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n)]
        data = {n: zin.read(n) for n in secs}
        pat = re.compile(r'(borderFillIDRef=")0(")')
        if not any(pat.search(d.decode("utf8", "ignore")) for d in data.values()):
            zin.close()
            return 0
        hd = zin.read("Contents/header.xml").decode("utf8")
        ids = [int(x) for x in re.findall(r'<hh:borderFill id="(\d+)"', hd)]
        nid = (max(ids) if ids else 0) + 1
        none = ('<hh:borderFill id="%d" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/>'
                '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/>'
                '<hh:rightBorder type="NONE" width="0.1 mm" color="#000000"/><hh:topBorder type="NONE" width="0.1 mm" color="#000000"/>'
                '<hh:bottomBorder type="NONE" width="0.1 mm" color="#000000"/></hh:borderFill>') % nid
        m = re.search(r'<hh:borderFills itemCnt="(\d+)">', hd)
        if not m or "</hh:borderFills>" not in hd:
            zin.close()
            return 0
        hd = hd.replace(m.group(0), '<hh:borderFills itemCnt="%d">' % (int(m.group(1)) + 1), 1).replace("</hh:borderFills>", none + "</hh:borderFills>", 1)
        n = 0
        tmp = dst + ".bf0"
        with zipfile.ZipFile(tmp, "w") as zo:
            for i in zin.infolist():
                b = zin.read(i.filename)
                if i.filename == "Contents/header.xml":
                    b = hd.encode("utf8")
                elif i.filename in data:
                    t = b.decode("utf8")
                    t, k = pat.subn(r"\g<1>%d\g<2>" % nid, t)
                    n += k
                    b = t.encode("utf8")
                zi = zipfile.ZipInfo(i.filename, i.date_time)
                zi.external_attr = i.external_attr
                zi.compress_type = i.compress_type
                zo.writestr(zi, b)
        zin.close()
        os.replace(tmp, dst)
        return n
    except Exception as _e:
        ERRORS.append(f"bf0 {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _align_schema_values(dst):
    """C101: 제3자 OWPML 스키마 검사(python-hwpx)에서 hwpai 에만 나온 값 이탈 중 한컴 저장본으로 정답 값을 확인한 것만 한컴 표기로 맞춘다.
    - hp:cellMargin 의 -1(HWP 의 0xFFFF…「지정 안 함」을 부호 있는 수로 쓴 것) → 4294967295 (한컴 저장본 같은 자리 값, 표본 문서 다수에서 확인)
    - hp:checkBtn@backStyle 의 숫자 1/0 → OPAQUE/TRANSPARENT (한컴 저장본 09596c115082 에서 1 → OPAQUE 10곳 확인; 스키마 열거값)
    - hp:connectLine@isReverseHV="0" → 속성 삭제 (스키마에 없는 속성, 한컴 저장본은 쓰지 않음 — 17e2f9dba979 13곳). 값이 1 이면 건드리지 않는다.
    추측으로 바꾸지 않는다: 한컴 값이 확인되지 않은 이탈(쪽 회전 중심의 원본 쓰레기 값, 바깥 여백 -1 등)은 그대로 둔다. 바꾼 곳 수를 돌려준다."""
    import re
    import zipfile
    subs = [
        (re.compile(r'(<hp:cellMargin\b[^>]*?\b(?:left|right|top|bottom)=")-1(")'), r"\g<1>4294967295\2"),
        (re.compile(r'(<hp:checkBtn\b[^>]*?\bbackStyle=")1(")'), r"\1OPAQUE\2"),
        (re.compile(r'(<hp:checkBtn\b[^>]*?\bbackStyle=")0(")'), r"\1TRANSPARENT\2"),
        (re.compile(r'(<hp:connectLine\b[^>]*?) isReverseHV="0"'), r"\1"),
    ]
    try:
        zin = zipfile.ZipFile(dst)
        out, total = {}, 0
        for zi in zin.infolist():
            if re.fullmatch(r"Contents/section\d+\.xml", zi.filename):
                x = zin.read(zi.filename).decode("utf-8")
                y = x
                for pat, rep in subs:
                    while True:   # 한 요소에 여러 속성이 있을 수 있어 바뀌지 않을 때까지
                        y2, k = pat.subn(rep, y)
                        total += k
                        if not k:
                            break
                        y = y2
                if y != x:
                    out[zi.filename] = y.encode("utf-8")
        if not out:
            zin.close()
            return 0
        tmp = dst + ".sv"
        with zipfile.ZipFile(tmp, "w") as zo:
            for zi in zin.infolist():
                zo.writestr(zi, out.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total
    except Exception as _e:
        ERRORS.append(f"sv {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _fix_compose(dst):
    """C102: 글자 겹치기(hp:compose)를 한컴이 같은 원본을 저장한 값과 맞춘다. 근거는 한컴 저장본 대조(438건 중 글자 겹치기가 있는 문서 전부)와 원본 레코드 바이트.
    ① 원본 레코드에 글자만 있고 뒤쪽(테두리·크기·펼침·글자모양 목록)이 없을 때 엔진은 charSz=0·SPREAD·charPrCnt=0(자식 없음, 스키마 위반)을 쓴다.
       한컴은 같은 레코드를 charSz=-4·OVERLAP·charPrCnt=10(모두 4294967295)으로 저장한다(5개 문서 33곳 모두 같음) → 그 값으로 채운다.
    ② 테두리가 없는(CHAR) 겹치기에서 글자가 UTF-16 단위 2개 이상이고 펼침 바이트가 0 이면 한컴은 OVERLAP 으로 쓰는데 엔진은 SPREAD 로 쓴다(4개 문서 15곳).
       글자 1자(a3e94e613a7d)·테두리 있는 도형형은 한컴도 SPREAD 이므로 건드리지 않는다.
    다른 값(원 테두리의 charSz=100 등)은 한컴 값의 규칙이 확인되지 않아 바꾸지 않는다. 바꾼 개수를 돌려준다."""
    import html
    import re
    import zipfile
    pat = re.compile(r'<hp:compose\b([^>]*)>(.*?)</hp:compose>', re.S)

    def fix(m):
        a, body = m.group(1), m.group(2)
        g = lambda k: (re.search(r'\b%s="([^"]*)"' % k, a) or [None, None])[1]
        if g("charPrCnt") == "0" and not body.strip() and g("charSz") == "0" and g("composeType") == "SPREAD":
            a2 = re.sub(r'\bcharSz="0"', 'charSz="-4"', a)
            a2 = re.sub(r'\bcomposeType="SPREAD"', 'composeType="OVERLAP"', a2)
            a2 = re.sub(r'\bcharPrCnt="0"', 'charPrCnt="10"', a2)
            return "<hp:compose%s>%s</hp:compose>" % (a2, '<hp:charPr prIDRef="4294967295"/>' * 10), 1
        if g("circleType") == "CHAR" and g("composeType") == "SPREAD" and len(html.unescape(g("composeText") or "").encode("utf-16-le")) >= 4:   # 원본 레코드의 글자 수는 UTF-16 단위(보조 평면 PUA 1자 = 2)
            return "<hp:compose%s>%s</hp:compose>" % (re.sub(r'\bcomposeType="SPREAD"', 'composeType="OVERLAP"', a), body), 1
        return m.group(0), 0

    try:
        zin = zipfile.ZipFile(dst)
        out, total = {}, 0
        for zi in zin.infolist():
            if re.fullmatch(r"Contents/section\d+\.xml", zi.filename):
                x = zin.read(zi.filename).decode("utf-8")
                if "<hp:compose" not in x:
                    continue
                cnt = [0]

                def rep(m):
                    r, k = fix(m)
                    cnt[0] += k
                    return r
                y = pat.sub(rep, x)
                if cnt[0]:
                    out[zi.filename] = y.encode("utf-8")
                    total += cnt[0]
        if not out:
            zin.close()
            return 0
        tmp = dst + ".cp"
        with zipfile.ZipFile(tmp, "w") as zo:
            for zi in zin.infolist():
                zo.writestr(zi, out.get(zi.filename) or zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return total
    except Exception as _e:
        ERRORS.append(f"compose {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _drop_dangling_manifest(dst):
    """C103: 원본의 OLE 가 데이터(BinData) 없이 저장돼 있으면 엔진이 content.hpf 에 파일 없는 그림 항목(href="", "O", "OL", "OLE")을 만든다
    (정적 구조 검사가 4f01f3a92750 에서 찾음, 이전 판부터 있던 결함). 한컴 저장본은 같은 문서에서 이런 항목을 쓰지 않는다.
    zip 안에 파일이 없고 어떤 본문·header 에서도 참조(binaryItemIDRef)하지 않는 항목만 지운다. 지운 수를 돌려준다."""
    import re
    import zipfile
    try:
        zin = zipfile.ZipFile(dst)
        names = set(zin.namelist())
        hpf = "Contents/content.hpf"
        if hpf not in names:
            zin.close()
            return 0
        x = zin.read(hpf).decode("utf-8")
        refs = set()
        for n in names:
            if n == "Contents/header.xml" or re.fullmatch(r"Contents/(section|masterPage)\d+\.xml", n):
                refs.update(re.findall(r'binaryItemIDRef="([^"]+)"', zin.read(n).decode("utf-8", "ignore")))
        k = [0]

        def rep(m):
            i, h = m.group(1), m.group(2)
            if i in refs or (h and (h in names or "Contents/" + h in names)):
                return m.group(0)
            k[0] += 1
            return ""
        y = re.sub(r'<opf:item\b(?=[^>]*\bmedia-type="application/octet-stream")[^>]*?\bid="([^"]*)"[^>]*?\bhref="([^"]*)"[^>]*/>', rep, x)
        if not k[0]:
            zin.close()
            return 0
        tmp = dst + ".mf"
        with zipfile.ZipFile(tmp, "w") as zo:
            for zi in zin.infolist():
                zo.writestr(zi, y.encode("utf-8") if zi.filename == hpf else zin.read(zi.filename), compress_type=zi.compress_type)
        zin.close()
        os.replace(tmp, dst)
        return k[0]
    except Exception as _e:
        ERRORS.append(f"mf {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def _store_incompressible(dst):
    """C96: 이미 압축된 그림(PNG·JPEG 등)을 deflate 로 다시 압축하면 압축본이 원본보다 커지는 멤버가 생긴다(zip 헤더의 「압축 후 크기 > 원래 크기」).
    제3자 검증기(python-hwpx)가 이를 보안 오류로 분류해 HWPX 열기를 거부했다(독립 검증, 11개 중 8개). 그런 멤버만 저장(STORED) 방식으로 다시 써서 없앤다.
    내용·순서는 그대로이고 해당 없으면 파일을 건드리지 않는다. 바꾼 멤버 수를 돌려준다."""
    import zipfile
    try:
        zin = zipfile.ZipFile(dst)
        bad = {i.filename for i in zin.infolist() if i.compress_type == zipfile.ZIP_DEFLATED and i.compress_size > i.file_size}
        if not bad:
            zin.close()
            return 0
        # 다시 쓸 때 파이썬 zlib 이 다른 멤버를 다시 deflate 하면 그 멤버가 새로 커질 수 있다(실측: image36.png 385→388).
        # 그래서 다시 쓰기 전에 모든 deflate 멤버를 같은 방식으로 압축해 보고 커지는 것도 함께 저장 방식으로 돌린다.
        import zlib
        for i in zin.infolist():
            if i.compress_type == zipfile.ZIP_DEFLATED and i.filename not in bad:
                c = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
                if len(c.compress(zin.read(i.filename)) + c.flush()) > i.file_size:
                    bad.add(i.filename)
        tmp = dst + ".stored"
        with zipfile.ZipFile(tmp, "w") as zo:
            for i in zin.infolist():
                data = zin.read(i.filename)
                zi = zipfile.ZipInfo(i.filename, i.date_time)
                zi.external_attr = i.external_attr
                zi.compress_type = zipfile.ZIP_STORED if i.filename in bad else i.compress_type
                zo.writestr(zi, data)
        zin.close()
        os.replace(tmp, dst)
        return len(bad)
    except Exception as _e:
        ERRORS.append(f"stored {type(_e).__name__}: {str(_e)[:80]}")
        return 0


def apply_all(src, dst):
    """뒤처리를 정해진 순서로 모두 적용하고 사용자에게 보여 줄 알림 목록을 돌려준다(데스크톱 엔진 래퍼·웹 시험판 공통)."""
    notes = []
    n = _restore_extensionless_images(src, dst)
    if n:
        notes.append(f"확장자 없는 그림 {n}개를 원본 BinData 에서 복원해 넣음(C86)")
    n = _fix_last_page_number_pos(src, dst)
    if n:
        notes.append(f"한 문단의 여러 쪽번호 위치 중 마지막(화면에 적용되는) 값으로 {n}곳을 바로잡음(C88)")
    n = _restore_symbol_codepoints(src, dst)
    if n:
        notes.append(f"한컴 기호 글꼴 문자 {n}자를 원본 코드(U+A000대)로 되돌림(C93)")
    n = _fix_note_autonum(dst)
    if n:
        notes.append(f"각주·미주 안의 자동 번호 {n}곳을 그 주석의 번호(쪽마다 다시 시작 등 반영값)와 맞춤(C92)")
    n = _fix_equation_child_order(dst)
    if n:
        notes.append(f"수식 {n}개의 하위 요소 순서를 OWPML·한컴 순서(sz·pos·outMargin 다음 script)로 맞춤(C107)")
    n = _fix_negative_out_margin(dst)
    if n:
        notes.append(f"음수 바깥 여백 {n}곳을 0 으로 바로잡음(C106, 한컴 저장본과 같게)")
    if os.environ.get("HWPAI_FIELDID", "1") == "1":
        n = _fix_field_ids(dst, src)
        if n:
            notes.append(f"필드 {n}개에 한컴 저장본과 같은 zorder·fieldid 속성을 채움(C112)")
    if os.environ.get("HWPAI_COLENUM", "1") == "1":
        n = _fix_column_enums(dst)
        if n:
            notes.append(f"다단 종류·단 구분선 {n}곳을 한컴 표기로 바로잡음(C116)")
    if os.environ.get("HWPAI_COLWIDTH", "1") == "1":
        n = _fix_column_widths(src, dst)
        if n:
            notes.append(f"단 너비를 따로 정한 다단 {n}곳에 원본 단 너비를 넣음(C118)")
    if os.environ.get("HWPAI_SHADOWMG", "1") == "1":
        n = _fix_shadow_margin(dst)
        if n:
            notes.append(f"그림자 있는 그리기 개체 {n}개의 바깥 여백을 한컴 표기(0)로 맞춤(C119)")
    if os.environ.get("HWPAI_EQSIZE", "1") == "1":
        n = _fix_equation_sizes(dst)
        if n:
            notes.append(f"옛 한글 조판으로 저장된 수식 {n}개의 크기를 한글 2024 값으로 맞춤(C121)")
    if os.environ.get("HWPAI_LSFOREIGN", "1") == "1":
        n = _fix_foreign_lineseg(dst)
        if n:
            notes.append(f"한컴이 아닌 생성기의 줄 배치 저장값 {n}곳을 지워 한글이 열 때 다시 계산하게 함(C120)")
    if os.environ.get("HWPAI_NOTESFX", "1") == "1":
        n = _fix_note_suffix(src, dst)
        if n:
            notes.append(f"각주·미주 번호 장식 문자 {n}곳을 원본 값으로 맞춤(C117)")
    if os.environ.get("HWPAI_CARET", "1") == "1":
        n = _fix_caret_position(src, dst)
        if n:
            notes.append("커서 위치를 원본 문서 속성 값으로 바꿈(C115)")
    if os.environ.get("HWPAI_SHY", "1") == "1":
        n = _fix_soft_hyphen(src, dst)
        if n:
            notes.append(f"하이픈 제어 문자 {n}개를 한컴 표기(hp:hypen)로 바꿈(C114)")
    if os.environ.get("HWPAI_SCRIPTID", "0") == "1":
        n = _fix_script_manifest_ids(dst)
        if n:
            notes.append("문서 스크립트의 목록 id 를 한컴 표기(headersc·sourcesc)로 바꿈(C113) — 한컴에서 열 때 스크립트가 실행됨")
    else:
        # C113 기본 꺼짐(보안): 한컴이 문서 스크립트로 읽으면 열 때 스크립트가 실행된다. 대량 판정에서 원본도 한글을 멈추게 한
        # 스크립트 문서(0a0392bd0703)와 열기 158초 문서(20c2df3431d5)가 변환본에서도 같은 증상을 보였다(시험V8). 공공 PC 에서는
        # 자동 실행을 막고 스크립트 원문은 패키지에 그대로 보존한다(필요하면 HWPAI_SCRIPTID=1).
        try:
            import zipfile as _zf
            with _zf.ZipFile(dst) as _z:
                if "Scripts/sourceScripts" in _z.namelist() and _z.getinfo("Scripts/sourceScripts").file_size > 2000:
                    notes.append("문서 스크립트는 원문 그대로 보존하고 자동 실행은 막아 둠(C113, 켜려면 HWPAI_SCRIPTID=1)")
        except Exception:
            pass
    n = _fix_revision_sign_field(dst)
    if n:
        notes.append(f"교정부호 필드($RevisionSign·$RevisionClipping) {n}개의 type 을 한컴 표기(PROOFREADING_MARKS_*)로 바로잡음(C90·C104)")
    try:
        from . import tracked as _tr
        n, sk, why = _tr.apply(src, dst)
    except Exception as _e:
        ERRORS.append(f"tracked {type(_e).__name__}: {str(_e)[:80]}")
        n, sk, why = 0, 0, ""
    if n or sk or why:
        notes.append(f"변경 추적 {n}개 문단의 삭제·삽입 이력을 한컴 표기(deleteBegin/insertBegin)로 실음" + (f", 글이 맞지 않아 건너뛴 문단 {sk}개" if sk else "") + (f" — {why}" if why else "") + "(C95)")
    n = _fix_borderfill_zero(dst)
    if n:
        notes.append(f"header 에 없는 테두리·배경 번호 0 을 가리키던 참조 {n}개를 「없음」 항목으로 연결(C99)")
    n = _align_schema_values(dst)
    if n:
        notes.append(f"OWPML 스키마에 맞지 않던 값 {n}곳을 한컴 저장본과 같은 표기로 맞춤(C101)")
    n = _fix_compose(dst)
    if n:
        notes.append(f"글자 겹치기 {n}곳의 모양 값을 한컴 저장 값과 맞춤(C102)")
    n = _drop_dangling_manifest(dst)
    if n:
        notes.append(f"파일도 참조도 없는 그림 목록 항목 {n}개를 지움(C103)")
    n = _strip_linesegarray(dst)
    if n:
        notes.append(f"줄 배치 캐시 {n}개를 지워 한글이 줄을 다시 나누게 함(C98, HWPAI_LINESEG=strip)")
    n = _store_incompressible(dst)
    if n:
        notes.append(f"압축하면 오히려 커지는 그림 {n}개를 저장 방식으로 다시 써 zip 구조 오류를 없앰(C96)")
    return notes
