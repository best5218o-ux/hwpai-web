"""변환 전후 시각 비교 보고서(HTML) — 원본 HWP 와 변환 HWPX 를 쪽별로 나란히 그려 보여 주고 쪽 수·쪽별 글·그림·선 수를 대조한다.

  python -m hwpai visual 원본.hwp 변환.hwpx [--out 보고서.html] [--pages 12]

방법: 같은 렌더러(rhwp)로 두 파일을 쪽별 SVG 로 그린다. 쪽 수, 쪽별 글자(SVG 글 요소를 모은 것), 그림·도형 요소 수가 같은지 본다.
한계(보고서에도 적는다): 두 쪽 모두 같은 렌더러가 그리므로 「한글 프로그램에서 보이는 모습」의 증명이 아니다 —
  변환이 쪽 구성·표·그림 배치를 바꾸었는지 잡아내는 용도이며, 한글 화면과의 차이는 사용자의 한글 확인이 필요하다(1분 체크리스트).
쪽 수가 다르거나 쪽별 글이 다르면 「확인 필요」로 표시한다.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import tempfile

from .engines import find_core, find_node, HERE


def _render(src: str, outdir: str, max_pages: int, timeout: float = 180.0) -> dict:
    core, node = find_core(), find_node()
    if not core:
        raise RuntimeError("변환 엔진(rhwp)을 찾지 못했습니다. hwpai doctor 로 점검하세요.")
    try:
        import wasmtime  # noqa: F401  경량판: Node 없이 파이썬(wasmtime) 렌더 일꾼을 먼저 쓴다
        import sys
        cmd = [sys.executable, os.path.join(HERE, "rhwp_py.py"), "--render", core]
    except ImportError:
        if not node:
            raise RuntimeError("변환 엔진 실행기(wasmtime 또는 Node.js)를 찾지 못했습니다. hwpai doctor 로 점검하세요.")
        cmd = [node, os.path.join(HERE, "render_worker.mjs"), core]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        p.stdout.readline()  # ready
        p.stdin.write(json.dumps({"src": src, "outdir": outdir, "maxPages": max_pages}) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()
        return json.loads(line) if line.strip() else {"ok": False, "error": "렌더 일꾼 응답 없음"}
    finally:
        try:
            p.stdin.close()
            p.wait(timeout=10)
        except Exception:
            p.kill()


def _svg_stats(svg: str) -> dict:
    txt = "".join(re.findall(r">([^<>]+)</text>", svg))
    txt = re.sub(r"\s+", "", html.unescape(txt))
    return {"text": txt, "images": len(re.findall(r"<image\b", svg)), "paths": len(re.findall(r"<(?:path|rect|line|polygon|ellipse)\b", svg))}


def compare(orig: str, conv: str, max_pages: int = 12) -> dict:
    with tempfile.TemporaryDirectory(prefix="hwpai_vis_") as d:
        ra = _render(orig, os.path.join(d, "a"), max_pages)
        rb = _render(conv, os.path.join(d, "b"), max_pages)
        out = {"orig": os.path.basename(orig), "conv": os.path.basename(conv), "ok": bool(ra.get("ok") and rb.get("ok")),
               "pages_orig": ra.get("pages"), "pages_conv": rb.get("pages"), "errors": [ra.get("error"), rb.get("error")], "rows": []}
        if not out["ok"]:
            return out
        for i in range(min(ra["rendered"], rb["rendered"])):
            a = open(os.path.join(d, "a", f"p{i}.svg"), encoding="utf-8").read()
            b = open(os.path.join(d, "b", f"p{i}.svg"), encoding="utf-8").read()
            sa, sb = _svg_stats(a), _svg_stats(b)
            out["rows"].append({"page": i + 1, "text_same": sa["text"] == sb["text"], "chars": [len(sa["text"]), len(sb["text"])],
                                "images": [sa["images"], sb["images"]], "shapes": [sa["paths"], sb["paths"]], "svg_a": a, "svg_b": b})
        out["pages_same"] = out["pages_orig"] == out["pages_conv"]
        out["verdict"] = "일치" if out["pages_same"] and all(r["text_same"] and r["images"][0] == r["images"][1] for r in out["rows"]) else "확인 필요"
        return out


def to_html(r: dict, assets: str | None = None) -> str:
    """assets: 쪽 그림(SVG) 파일을 둘 폴더(HTML 과 같은 위치 기준 상대로 참조). 없으면 HTML 안에 넣는다(큰 문서는 파일이 매우 커짐)."""
    if assets:
        os.makedirs(assets, exist_ok=True)
        rel = os.path.basename(assets)
        for x in r.get("rows", []):
            for side in ("a", "b"):
                with open(os.path.join(assets, f"p{x['page']}_{side}.svg"), "w", encoding="utf-8") as f:
                    f.write(x["svg_" + side])
                x["ref_" + side] = f"<img src=\"{rel}/p{x['page']}_{side}.svg\" alt=\"{x['page']}쪽 {'원본' if side == 'a' else '변환'}\" loading=lazy>"
    else:
        for x in r.get("rows", []):
            x["ref_a"], x["ref_b"] = x["svg_a"], x["svg_b"]
    css = ("<style>:root{color-scheme:light dark}body{font:14px system-ui,'Malgun Gothic',sans-serif;margin:20px}"
           ".pg{border:1px solid #8886;margin:14px 0;padding:8px;border-radius:6px}.pg.bad{border-color:#d33;background:#d331}"
           ".two{display:grid;grid-template-columns:1fr 1fr;gap:10px}.two>div{background:#fff;border:1px solid #8884;overflow:hidden}"
           ".two svg,.two img{width:100%;height:auto;display:block}small{opacity:.75}@media(max-width:700px){.two{grid-template-columns:1fr}}</style>")
    head = (f"<h1>변환 전후 시각 비교</h1><p>원본 <b>{html.escape(r['orig'])}</b> ({r['pages_orig']}쪽) → 변환 <b>{html.escape(r['conv'])}</b> ({r['pages_conv']}쪽)"
            f" · 판정 <b>{r.get('verdict', '렌더 실패')}</b></p>"
            "<p><small>같은 렌더러(rhwp)로 그린 비교입니다. 쪽 구성·표·그림 배치가 변환으로 바뀌었는지 잡는 용도이며, 한글 프로그램 화면과의 일치를 증명하지 않습니다 — 한글에서 열어 보는 확인이 필요합니다.</small></p>")
    if not r["ok"]:
        return "<!doctype html><meta charset=utf-8><title>시각 비교</title>" + css + head + f"<p>렌더 실패: {html.escape(str(r['errors']))}</p>"
    body = []
    for x in r["rows"]:
        bad = not x["text_same"] or x["images"][0] != x["images"][1]
        body.append(f"<div class=\"pg {'bad' if bad else ''}\"><b>{x['page']}쪽</b> · 글 {x['chars'][0]}→{x['chars'][1]}자 {'일치' if x['text_same'] else '다름'}"
                    f" · 그림 {x['images'][0]}→{x['images'][1]} · 선·도형 {x['shapes'][0]}→{x['shapes'][1]}"
                    f"<div class=two><div>{x['ref_a']}</div><div>{x['ref_b']}</div></div></div>")
    note = "" if r["pages_same"] else f"<p><b>쪽 수가 다릅니다(원본 {r['pages_orig']} → 변환 {r['pages_conv']}).</b></p>"
    return "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>변환 전후 시각 비교</title>" + css + head + note + "".join(body)


def cmd_visual(a):
    r = compare(a.orig, a.conv, a.pages)
    out = a.out or os.path.splitext(a.conv)[0] + "_시각비교.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(to_html(r, None if a.embed else os.path.splitext(out)[0] + "_쪽"))
    print(f"[{r.get('verdict', '렌더 실패')}] 쪽 {r['pages_orig']}→{r['pages_conv']} — {out}")
    return 0 if r.get("verdict") == "일치" else 1
