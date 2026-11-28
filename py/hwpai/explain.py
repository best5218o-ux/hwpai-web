"""검증서 쉬운 설명 — 판정 코드를 사람이 읽는 말로 풀고, 다른 곳·원인·해결법을 보여 준다.

판정 기준은 바꾸지 않는다. audit 가 이미 기록한 코드·차이 위치를 읽기 쉽게 다시 쓸 뿐이다.
원인은 「그럴 가능성이 큽니다」로 쓴다(자동 판정이 원인까지 확인하지는 못하므로).
"""
from __future__ import annotations

# 코드 → (무엇이 다른가, 왜 생길 수 있나, 어떻게 하면 되나)
CAUSE = {
    "TEXT_LOSS": ("원본에 있던 글이 변환본에서 빠졌거나 다른 글로 바뀌었습니다.",
                  "글상자·도형 안의 글, 특수한 개체, 손상된 문단이 변환 엔진에서 읽히지 않았거나, 변환한 뒤에 변환본의 글이 고쳐졌을 수 있습니다.",
                  "빠지거나 바뀐 글(「다른 부분」)을 원본과 견주어 보세요. 중요한 문서는 이 변환본을 쓰지 말고 한글에서 직접 HWPX로 저장하세요."),
    "TEXT_DIFF": ("글이 일부 다릅니다(문단 나뉨·순서·더해진 글 등 — 원본 글이 빠진 것은 아님).",
                  "문단이 다르게 나뉘었거나 자리가 옮겨졌을 가능성이 큽니다.",
                  "아래 「다른 부분」을 원본과 견주어 보세요."),
    "TABLE_COUNT": ("표의 개수가 다릅니다.", "표가 글로 풀리거나 중첩 표가 합쳐졌을 가능성이 큽니다.",
                    "원본과 변환본의 표 개수를 세어 보고, 표가 많은 문서는 한글에서 직접 저장하세요."),
    "TABLE_CELL": ("표 칸 안의 글이 다릅니다.", "칸이 합쳐지거나 칸 안 줄이 나뉘어 글이 다른 칸으로 옮겨졌을 가능성이 큽니다.",
                   "아래 「다른 부분」의 표 행·열을 원본 표와 비교하세요."),
    "TABLE_GRID_HWP3": ("옛 형식(HWP 3.0) 표의 칸 합치기(병합) 모양이 원본과 다릅니다.", "칸 수와 칸마다의 글은 같습니다. 0.1mm 안팎으로 어긋난 줄·칸 경계를 엔진이 다르게 묶었을 가능성이 큽니다.", "한글에서 변환본을 열어 표 모양을 원본과 견주어 보세요."),
    "TABLE_SPAN": ("표의 칸 합치기(병합) 모양이 다릅니다.", "병합된 칸을 엔진이 다르게 해석했을 가능성이 큽니다.",
                   "표가 깨져 보이면 한글에서 직접 저장하거나 표 데이터(get_tables)로 읽으세요."),
    "CELL_SOFT_DIFF": ("표 칸의 기호·자동 번호 저장값만 다릅니다(기호 개수는 같음).", "글꼴에 따라 같은 기호가 다른 코드로 저장됐을 가능성이 큽니다.",
                       "한글에서 열어 ○·☑ 같은 기호가 원본과 같은 모양인지 확인하세요."),
    "IMAGE_MISSING": ("그림이 빠졌습니다.", "특수 형식 그림이나 연결만 있던 그림이 변환에서 빠졌을 가능성이 큽니다.",
                      "원본의 그림 개수와 비교하고, 그림이 중요하면 한글에서 직접 저장하세요."),
    "IMAGE_EXTRA": ("그림이 원본보다 늘었습니다.", "한 그림이 여러 개체로 나뉘어 저장됐을 가능성이 큽니다.", "내용 손실은 아닙니다."),
    "IMAGE_HASH": ("그림 파일 내용이 원본과 다릅니다(개수는 같음).", "그림을 다시 압축·변환했을 가능성이 큽니다.", "그림이 선명한지 눈으로 확인하세요."),
    "IMAGE_REF_NO_DATA": ("원본에서 그림 파일이 없는 참조가 있었습니다.", "원본 자체에 그림 데이터가 없는 빈 참조입니다.", "원본에도 그림이 없던 것이라 보통 문제 없습니다."),
    "FOOTNOTE_COUNT": ("각주 개수가 다릅니다.", "각주가 본문으로 풀렸거나 빠졌을 가능성이 큽니다.", "각주가 있는 쪽을 원본과 비교하세요."),
    "ENDNOTE_COUNT": ("미주 개수가 다릅니다.", "미주가 본문으로 풀렸거나 빠졌을 가능성이 큽니다.", "미주가 있는 쪽을 원본과 비교하세요."),
    "EQUATION_COUNT": ("수식 개수가 다릅니다.", "수식이 그림이나 글로 바뀌었을 가능성이 큽니다.", "수식이 많은 문서는 한글에서 직접 저장하세요."),
    "EQUATION_SCRIPT": ("수식 내용(스크립트)이 조금 다릅니다.", "수식 표기 방식이 다르게 저장됐을 가능성이 큽니다.", "수식 모양을 눈으로 확인하세요."),
    "EQUATION_CAPTION": ("수식 번호·설명(캡션)이 빠지거나 바뀌었습니다.", "캡션 자동 번호가 다시 매겨졌을 가능성이 큽니다.", "수식 옆 번호를 원본과 비교하세요."),
    "AUTONUM_DIFF": ("자동 번호(캡션·각주 번호)의 저장값만 다릅니다.", "한글은 열 때 번호를 다시 매기지만, AI·검색은 저장된 번호를 그대로 읽습니다.",
                     "한글에서 열면 문제없습니다. AI에 쓸 때는 번호가 다를 수 있음을 알아 두세요."),
    "SYMBOL_MAPPED": ("특수 기호의 문자 코드만 다릅니다.", "글꼴에 따라 같은 기호가 다른 코드로 저장됐을 가능성이 큽니다.", "한글에서 열어 기호 모양만 확인하세요."),
    "HEADER_FOOTER_COUNT": ("머리말·꼬리말 개수가 다릅니다.", "빈 머리말·꼬리말이 정리됐을 가능성이 큽니다(글은 같음).", "보통 문제 없습니다."),
    "FIELD_LOST": ("쪽 번호·날짜 같은 자동 입력 칸이 빠졌습니다.", "자동 입력 필드가 일반 글로 바뀌었을 가능성이 큽니다.", "쪽 번호·날짜가 필요하면 한글에서 직접 저장하세요."),
    "PAGENUM_LOST": ("쪽 번호 표시가 빠졌습니다.", "쪽 번호 개체가 변환에서 빠졌을 가능성이 큽니다.", "쪽 번호가 필요하면 한글에서 직접 저장하세요."),
    "SHAPE_MISSING": ("도형·글상자가 빠졌습니다.", "엔진이 지원하지 않는 도형이었을 가능성이 큽니다.", "도형 안 글이 중요하면 한글에서 직접 저장하세요."),
    "SHAPE_KIND": ("도형 종류가 바뀌었습니다.", "비슷한 도형으로 대체됐을 가능성이 큽니다.", "모양을 눈으로 확인하세요."),
    "SHAPE_DESC": ("도형 설명 글이 다릅니다.", "대체 글(설명)이 다시 쓰였을 가능성이 큽니다.", "내용 손실은 아닙니다."),
    "HIDDEN_COMMENT": ("숨은 메모(주석)가 빠졌습니다.", "화면에 안 보이는 메모가 변환에서 빠졌을 가능성이 큽니다.", "메모가 중요하면 원본을 따로 보관하세요."),
    "BOOKMARK_LOST": ("책갈피가 빠졌습니다.", "문서 안 이동 표시가 변환에서 빠졌을 가능성이 큽니다.", "보통 문제 없습니다."),
    "TRACK_LOST": ("변경 추적(고친 흔적)이 빠졌습니다.", "수정 이력이 변환에서 정리됐을 가능성이 큽니다.", "수정 이력이 필요하면 원본을 보관하세요."),
    "TRACK_CHECK_ERROR": ("변경 추적 이력을 비교하지 못했습니다.", "이력 구조가 특이했을 가능성이 큽니다.", "변경 이력이 중요하면 직접 확인하세요."),
    "INVENTORY_ERROR": ("일부 개체 목록을 비교하지 못했습니다.", "문서 구조가 특이했을 가능성이 큽니다.", "나머지 항목은 정상 비교되었습니다. 중요한 문서는 직접 확인하세요."),
    "PRV_LOW": ("한글이 저장한 미리보기 글이 변환본에 일부만 있습니다.", "미리보기에는 있지만 본문에서 읽히지 않은 글이 있을 가능성이 큽니다.", "변환본 글을 원본과 비교하세요."),
    "PRV_MISSING": ("한글이 저장한 미리보기 글이 변환본에 없습니다.", "본문 일부가 읽히지 않았을 가능성이 큽니다.", "원본과 비교하고 한글에서 직접 저장하세요."),
    "ENGINE_LOSS": ("변환 엔진이 일부 요소를 지원하지 않는다고 알렸습니다.", "엔진이 알려진 한계에 닿았습니다.", "지원 안 된 요소가 있는 쪽을 확인하세요."),
    "CONV_READ_WARN": ("변환본을 읽다가 경고가 났습니다.", "변환본 구조가 일부 특이합니다.", "한글에서 열어 보세요."),
    "ORIG_READ_WARN": ("원본을 읽다가 경고가 났습니다.", "원본 일부가 손상됐거나 특이한 구조일 수 있습니다.", "원본을 한글에서 열어 보세요."),
    "ORIG_UNVERIFIABLE": ("원본과 대조하지 못했습니다.", "원본을 판독하지 못해 비교 기준이 없습니다.", "원본이 한글에서 열리는지 확인하세요."),
    "CONV_EMPTY": ("변환본이 비어 있습니다.", "변환 엔진이 문서를 읽지 못했을 가능성이 큽니다.", "원본이 한글에서 열리는지 확인하고 다시 변환하세요."),
    "CONV_STRUCTURE": ("변환본 파일 안의 구조(XML)가 깨져 있습니다.", "변환·뒤처리 중 파일이 잘못 쓰였을 가능성이 큽니다.", "이 변환본은 한글에서 열리지 않을 수 있습니다. 다시 변환하고, 반복되면 한글에서 직접 저장하세요."),
    "SPACING_DIFF": ("띄어쓰기(빈칸) 수가 원본과 다릅니다.", "낱말 사이 빈칸이 변환에서 빠지거나 더해졌을 가능성이 큽니다.", "변환본을 열어 낱말이 붙어 있지 않은지 확인하세요."),
    "CONV_NOT_HWPX": ("변환본이 HWPX 형식이 아닙니다.", "저장 중 오류가 났을 가능성이 큽니다.", "다시 변환하세요."),
    "CONV_UNREADABLE": ("변환본을 읽을 수 없습니다.", "변환본이 손상됐을 가능성이 큽니다.", "다시 변환하고, 반복되면 한글에서 직접 저장하세요."),
}
ITEMS = [("text", "글"), ("tables", "표"), ("images", "그림"), ("footnotes", "각주"), ("endnotes", "미주"), ("equations", "수식")]
HEAD = {
    "PASS": ("✔ 정상 변환", "글·표·그림이 원본과 모두 같습니다. 그대로 쓰셔도 됩니다."),
    "WARN": ("▲ 확인 필요", "큰 손실은 없지만 일부가 다릅니다. 아래 「다른 부분」을 한번 보세요."),
    "FAIL": ("✖ 변환 실패", "원본과 다른 곳이 있어 이 변환본은 그대로 쓰면 안 됩니다. 아래 「왜 그런가」를 보세요."),
}


def _clip(s: str, n: int = 60) -> str:
    s = (s or "").replace("\n", " ").strip()
    if not s:
        return "(없음)"
    return s if len(s) <= n else s[:n] + "…"


def _small_pairs(orig: str, conv: str, ctx: int = 6) -> list:
    """원본 글과 변환본 글에서 실제로 다른 곳만 앞뒤 몇 글자와 함께 짝으로 뽑는다(찾는 글 → 바꿀 글).
    긴 문단·여러 문단으로 된 표 칸 글을 통째로 바꾸려 하면 문단 경계를 넘어 찾지 못하므로, 다른 곳만 좁혀 바꾼다.
    앞뒤 글은 띄어쓰기에서 멈춘다(표 칸 안 문단은 띄어쓰기로 이어 붙여 비교하므로 그 너머는 다른 문단일 수 있다)."""
    import difflib
    out = []
    if not orig or not conv:
        return out
    ops = [o for o in difflib.SequenceMatcher(None, conv, orig, autojunk=False).get_opcodes() if o[0] != "equal"]
    spans = []
    for _, i1, i2, j1, j2 in ops:   # 가까운 차이는 하나로 묶는다
        if spans and i1 - spans[-1][1] <= ctx:
            spans[-1] = (spans[-1][0], i2, spans[-1][2], j2)
        else:
            spans.append((i1, i2, j1, j2))
    for i1, i2, j1, j2 in spans:
        def grow(stop_at_space):
            k, r = i1, i2
            while k > 0 and i1 - k < ctx and not (stop_at_space and conv[k - 1].isspace()):
                k -= 1
            while r < len(conv) and r - i2 < ctx and not (stop_at_space and conv[r].isspace()):
                r += 1
            return k, r
        k, r = grow(True)
        if (i1 - k) + (r - i2) < 1 and (i2 - i1) < 3:   # 바뀐 글이 짧고 앞뒤 글도 없으면 띄어쓰기를 넘어 넓힌다
            k, r = grow(False)
        key, val = conv[k:r], conv[k:i1] + orig[j1:j2] + conv[i2:r]
        if "\n" in key or not key.strip() or key == val:
            continue
        out.append((key, val))
    return out

def plain_report(d: dict) -> dict:
    ck, det = d.get("checks", {}), d.get("details", {})
    label, line = HEAD.get(d.get("verdict"), ("— 판정 없음", ""))
    compared = []
    def row(name, a, b, ok, note=""):
        compared.append({"항목": name, "원본": a, "변환본": b, "결과": "같음" if ok else "다름", "설명": note})
    if "text_chars" in ck:
        row("글", f"{ck['text_chars']}자", f"{ck.get('conv_chars')}자", bool(ck.get("text_exact")) or ck.get("text_lost_spots", 0) == 0 and ck.get("text_diff_spots", 0) == 0,
            "" if ck.get("text_exact") else f"{ck.get('text_diff_spots', 0)}곳 다름 · 빠진 곳 {ck.get('text_lost_spots', 0)}곳")
    if "tables" in ck:
        bad = ck.get("table_cells_bad", 0) + ck.get("table_span_bad", 0)
        row("표", f"{ck['tables'][0]}개", f"{ck['tables'][1]}개", ck["tables"][0] == ck["tables"][1] and not bad,
            f"칸 {ck.get('table_cells', 0)}개 중 다른 칸 {ck.get('table_cells_bad', 0)}개")
    for k, nm in (("images", "그림"), ("footnotes", "각주"), ("endnotes", "미주"), ("equations", "수식")):
        if k in ck:
            row(nm, f"{ck[k][0]}개", f"{ck[k][1]}개", ck[k][0] == ck[k][1] and not (k == "images" and ck.get("images_hash_unmatched")))
    diffs = []
    for x in det.get("text_diffs", [])[:12]:
        diffs.append({"종류": x["op"], "위치": x.get("where_orig") or "", "원본": _clip(x.get("orig")), "변환본": _clip(x.get("conv")),
                      "중요": bool(x.get("lost"))})
    for t in det.get("tables", []):
        for c in t.get("cell_diffs", [])[:8]:
            diffs.append({"종류": "표 칸 다름", "위치": f"표 {t['orig_id']} · {c['row']}행 {c['col']}열" if c.get("row") is not None else f"표 {t['orig_id']}",
                          "원본": _clip(c.get("orig")), "변환본": _clip(c.get("conv")), "중요": True})
    fixes, mapping, ins = [], {}, []
    def add_fix(kind, where, orig, conv, how, auto):
        n = len(fixes) + 1
        f = {"번호": n, "종류": kind, "위치": where, "원본에_있던_글": orig, "변환본의_글": conv, "방법": how, "자동수정": auto}
        if auto and orig and conv:
            pairs = _small_pairs(orig, conv) if orig != conv else []
            if not pairs:
                f["자동수정"] = False   # 보이는 글은 같고 다른 곳을 좁힐 수 없다 — 사람에게 넘긴다
            f["replace_text"] = {}
            for k, v in pairs:
                if k not in mapping:
                    mapping[k] = v
                    f["replace_text"][k] = v
        fixes.append(f)
    for x in det.get("text_diffs", []):
        o, c, op = (x.get("orig") or "").strip(), (x.get("conv") or "").strip(), x.get("op")
        w = x.get("where_orig") or x.get("where_conv") or ""
        if op == "바뀜" and o and c:
            add_fix("글 바로잡기", w, o, c, "변환본의 글을 원본 글로 바꿉니다(replace_text). 바꾼 뒤 다시 검증하세요.", True)
        elif op == "빠짐" and o and x.get("anchor_conv"):
            f = add_fix("빠진 글 채우기", f"{w} (변환본에서는 {x.get('where_conv') or ''})", o, "",
                        "앞 문단 글을 「앞 문단 글 + 줄바꿈 + 빠진 글」로 바꿔(replace_text) 그 뒤에 새 문단으로 넣습니다.", True)
            key = x["anchor_conv"]
            o_raw = (x.get("orig") or "").strip("\n")   # 문단 앞 띄어쓰기까지 원본 그대로 넣는다
            if key not in mapping:
                mapping[key] = key + "\n" + o_raw
            else:
                mapping[key] += "\n" + o_raw
            fixes[-1]["replace_text"] = {key: mapping[key]}
        elif op == "빠짐" and o:
            add_fix("빠진 글 채우기", f"{w} (변환본에서는 {x.get('where_conv') or ''})", o, "", "변환본의 해당 위치에 원본 글을 새 문단으로 넣어야 합니다. 앞 문단을 하나로 정할 수 없어 자동으로 넣지 못합니다. 한글에서 직접 넣어 주세요.", False)
        elif op == "더해짐" and c:
            add_fix("남는 글 지우기", x.get("where_conv") or "", "", c, "원본에 없는 글입니다. 필요 없으면 지웁니다(replace_text 로 빈 글로 바꾸기).", False)
    for t in det.get("tables", []):
        for c in t.get("cell_diffs", []):
            where = f"표 {t['orig_id']} · {c['row']}행 {c['col']}열"
            o, v = (c.get("orig") or "").strip(), (c.get("conv") or "").strip()
            if c.get("kind") == "글 다름" and o and v:
                add_fix("표 칸 글 바로잡기", where, o, v, "그 칸의 글을 원본 글로 바꿉니다(replace_text).", True)
            elif c.get("kind") == "글 다름" and o and not v:
                add_fix("표 칸 채우기", where, o, "", "그 칸이 비어 있습니다. 원본 글을 그 칸에 넣으세요(fill_form 또는 한글에서 직접).", False)
            else:
                add_fix("표 칸 구조", where, o, v, f"칸 {c.get('kind')}: 표 구조가 달라졌습니다. 이 표는 한글에서 직접 맞추는 것이 안전합니다.", False)
    seen, causes = set(), []
    for r in d.get("reasons", []):
        code = r.get("code")
        if code in seen:
            continue
        seen.add(code)
        what, why, todo = CAUSE.get(code, (r.get("msg", ""), "자동 설명이 준비되지 않은 항목입니다.", "자세한 기록(전문가용)을 보세요."))
        causes.append({"등급": "문제" if r.get("level") == "FAIL" else "참고", "코드": code, "무엇이": what, "왜": why, "어떻게": todo, "원문": r.get("msg", "")})
    ai = {"안내": "이 검증서만으로 AI가 고칠 수 있습니다. 순서: ① 수정안 중 자동수정=true 인 것의 replace_text_한번에 를 replace_text 도구에 한 번에 넣는다 ② 결과(새 HWPX)를 다시 audit 한다 ③ 판정이 PASS 가 되면 끝, 아니면 남은 수정안을 사람에게 보여 준다. 원본 HWP는 절대 덮어쓰지 않는다.",
          "replace_text_한번에": mapping, "수정안": fixes, "다시_검증": "audit(원본, 수정본)  — 판정이 PASS 이고 다른 부분이 0이면 끝"}
    return {"AI가_고치려면": ai, "결론": label, "쉽게 말하면": line, "비교한 것": compared, "다른 부분": diffs, "왜 그런가": causes,
            "검증 방법": "원본과 변환본을 각각 따로 읽어 글·표·그림·각주·수식을 하나씩 맞춰 봅니다. 파일 지문(SHA-256)은 같은 파일인지 확인하는 번호입니다."}


def to_plain_markdown(d: dict) -> str:
    p = plain_report(d)
    L = ["## 쉬운 설명", "", f"**{p['결론']}** — {p['쉽게 말하면']}", "", "### 무엇을 비교했나", "", "| 항목 | 원본 | 변환본 | 결과 |", "|---|---|---|---|"]
    for c in p["비교한 것"]:
        L.append(f"| {c['항목']} | {c['원본']} | {c['변환본']} | {'✔ 같음' if c['결과'] == '같음' else '✖ 다름'}{(' — ' + c['설명']) if c['설명'] else ''} |")
    L.append("")
    if p["다른 부분"]:
        L += ["### 다른 부분 (어디가 달랐나)", ""]
        for i, x in enumerate(p["다른 부분"], 1):
            L.append(f"{i}. **{x['종류']}** · {x['위치']} — 원본: 「{x['원본']}」 → 변환본: 「{x['변환본']}」" + (" ⚠ 내용 손실" if x["중요"] and x["종류"] != "표 칸 다름" else ""))
        L.append("")
    elif d.get("verdict") == "PASS":
        L += ["### 다른 부분", "", "- 없음. 비교한 모든 항목이 같습니다.", ""]
    if p["왜 그런가"]:
        L += ["### 왜 그런가 · 어떻게 하면 되나", ""]
        for c in p["왜 그런가"]:
            L += [f"- **[{c['등급']}] {c['무엇이']}**", f"  - 왜: {c['왜']}", f"  - 어떻게: {c['어떻게']}"]
        L.append("")
    fx = p["AI가_고치려면"]["수정안"]
    if fx:
        L += ["### 고치려면 (사람·AI 공용)", "", "| 번호 | 무엇을 | 어디 | 원본 글 | 지금 변환본 글 | 방법 |", "|---|---|---|---|---|---|"]
        for f in fx:
            L.append(f"| {f['번호']} | {f['종류']}{' (자동 가능)' if f['자동수정'] else ''} | {f['위치']} | {_clip(f['원본에_있던_글'])} | {_clip(f['변환본의_글'])} | {f['방법']} |")
        L += ["", "AI에게는 이 검증서(.json)의 `쉬운설명.AI가_고치려면` 을 그대로 주면 됩니다. 고친 뒤에는 반드시 다시 검증합니다.", ""]
    L += ["### 검증은 이렇게 했습니다", "", p["검증 방법"], ""]
    return "\n".join(L)
