"""대량표본 비교 집계: raw/ind_c*·fmt_c*·conv_c* 와 PC manifest 분류를 합쳐 도구별 csv·요약 md 를 만든다."""
import json, glob, csv, os, collections, sys, statistics
R = '/home/claude/bulk_compare_5th'
TOOLS = ['hwpai', 'kordoc', 'hwp2hwpx', 'pyhwpxlib']
MET = ["core_recall", "core_precision", "bigram_recall", "bigram_precision", "char_recall", "char_precision",
       "cell_text_recall", "cell_text_precision", "bin_recall", "bin_precision"]
FI = (["page", "cols", "para_pair", "para", "para.align", "para.line_spacing", "para.indent", "para.margin_lr",
       "para.space_prev_next", "para.break_kor", "char", "char.font", "char.size", "char.bold", "char.italic",
       "char.underline", "char.color", "char.spacing", "char.ratio", "tbl", "tbl.span", "tbl.width", "tbl.height",
       "tbl.border", "tbl.fill", "tbl.shape", "tbl.place", "obj", "obj.size", "obj.pos", "obj.wrap"])
P = 0.99
# 분류: manifest (개발사용여부 Y = 쓴 1,993 / 보류표본여부 Y = 532 / 둘 다 N = 37 → 안 쓴 569)
split = {}
for r in csv.DictReader(open(f'{R}/manifest_split.csv', encoding='utf-8-sig')):
    split[r['sha12']] = r['split']
ind = {t: {} for t in TOOLS}; fmt = {t: {} for t in TOOLS}
for t in TOOLS:
    for p in sorted(glob.glob(f'{R}/raw/ind_c*/{t}.jsonl')):
        for l in open(p, encoding='utf-8'):
            x = json.loads(l); ind[t][x['doc']] = x
    for p in sorted(glob.glob(f'{R}/raw/fmt_c*/{t}.jsonl')):
        for l in open(p, encoding='utf-8'):
            x = json.loads(l); fmt[t][x['key']] = x
keys = sorted(set(ind['hwpai']) & set(fmt['hwpai']))
# 변환 단계 상태
conv = {t: {} for t in TOOLS}
for p in sorted(glob.glob(f'{R}/raw/conv_c*/opentools_results.csv')):
    for r in csv.reader(open(p, encoding='utf-8-sig')):
        if r and r[0] in TOOLS: conv[r[0]][r[5]] = (r[2], r[6][:150])
for p in sorted(glob.glob(f'{R}/raw/conv_c*/hwpai_conv.log')):
    for l in open(p, encoding='utf-8'):
        if l.startswith('FAIL '):
            parts = l.rstrip().split(' ', 2); conv['hwpai'][parts[1]] = ('fail', parts[2] if len(parts) > 2 else '')

def text_pass(x, ref):
    if x is None: return False
    if x['status'] in ('no_output', 'unreadable'): return False
    m = x.get(ref)
    if not isinstance(m, dict): return False
    if not x.get('hwpx_parse_ok'): return False
    return all((m.get(k) is not None and m[k] >= P) for k in MET) and bool(m['cnt_match_all'])

def failing_text(x, ref):
    m = x.get(ref)
    if x['status'] in ('no_output', 'unreadable'): return [x['status']]
    if not isinstance(m, dict): return ['no_ref']
    out = [f'{k}={m[k]:.3f}' for k in MET if m.get(k) is not None and m[k] < P]
    if not m['cnt_match_all']:
        out += [f"cnt_{c[4:]}={m[c][0]}->{m[c][1]}" for c in m if c.startswith('cnt_') and c != 'cnt_match_all' and isinstance(m[c], list) and m[c][0] != m[c][1]]
    return out

def failing_fmt(f):
    if f['status'] != 'ok': return [f['status']]
    return [f'{k}={f[k]:.3f}' for k in FI if f.get(k) is not None and f[k] < P]

rows = {t: [] for t in TOOLS}
for t in TOOLS:
    for k in keys:
        x, f = ind[t].get(k), fmt[t].get(k)
        if x is None or f is None: continue
        r = dict(key=k, split=split.get(k, '?'), conv=conv[t].get(k, ('ok', ''))[0] if t != 'hwpai' else conv[t].get(k, ('ok', ''))[0],
                 conv_msg=conv[t].get(k, ('', ''))[1], status=x['status'], hwpx_valid=x.get('hwpx_valid'), hwpx_parse_ok=x.get('hwpx_parse_ok'))
        for ref in ('a', 'b'):
            m = x.get(ref) if isinstance(x.get(ref), dict) else {}
            for mm in MET: r[f'{ref}_{mm}'] = m.get(mm)
            r[f'{ref}_cnt_match_all'] = m.get('cnt_match_all')
            r[f'text_pass_{ref}'] = text_pass(x, ref)
        r['fmt_status'] = f['status']; r['format'] = f.get('format'); r['format_min'] = f.get('format_min'); r['fmt_pass'] = bool(f.get('format_pass'))
        for it in FI: r['f_' + it] = f.get(it)
        r['all_pass'] = r['text_pass_a'] and r['fmt_pass']
        r['fail_text_a'] = ';'.join(failing_text(x, 'a')); r['fail_fmt'] = ';'.join(failing_fmt(f))
        rows[t].append(r)
for t in TOOLS:
    with open(f'{R}/{t}_docs.csv', 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[t][0].keys())); w.writeheader(); w.writerows(rows[t])

def mean_over(rs, getter):
    v = [getter(r) for r in rs]; v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None

def stats(rs, t):
    n = len(rs); s = collections.OrderedDict()
    s['문서 수'] = n
    s['변환 실패(출력 없음)'] = sum(r['status'] == 'no_output' for r in rs)
    s['읽기 불가(zip·XML 깨짐)'] = sum(r['status'] == 'unreadable' for r in rs)
    s['구조 유효(엄격)'] = sum(bool(r['hwpx_valid']) for r in rs)
    s['구조 파싱 성공'] = sum(bool(r['hwpx_parse_ok']) for r in rs)
    s['통과: 글·개수·그림(정답 a 한글저장본, 10지표 ≥0.99 + 개수 9종 일치 + 파싱)'] = sum(r['text_pass_a'] for r in rs)
    s['통과: 글·개수·그림(정답 b 원본 직접판독)'] = sum(r['text_pass_b'] for r in rs)
    s['통과: 서식(층1, 31항목 모두 ≥0.99)'] = sum(r['fmt_pass'] for r in rs)
    s['통과: 종합(글·개수 a + 서식)'] = sum(r['all_pass'] for r in rs)
    s['통과: 종합(글·개수 b 원본직접판독 + 서식)'] = sum(r['text_pass_b'] and r['fmt_pass'] for r in rs)
    s['글·개수(a) 미달 중 「그림 정밀도(bin_precision)」 하나만 미달'] = sum((not r['text_pass_a']) and r['status'] != 'no_output' and r['fail_text_a'].startswith('bin_precision') and ';' not in r['fail_text_a'] for r in rs)
    return s

def item_means(rs):
    d = collections.OrderedDict()
    for mm in MET:
        for ref in ('a', 'b'):
            vals = [0.0 if r['status'] in ('no_output', 'unreadable') else (r[f'{ref}_{mm}'] if r[f'{ref}_{mm}'] is not None else 0.0) for r in rs]
            d[f'{ref}_{mm}'] = sum(vals) / len(vals)
    d['cnt_match_all(a) 비율'] = sum(bool(r['a_cnt_match_all']) for r in rs) / len(rs)
    for it in ['format', 'format_min'] + FI:
        vals = []
        for r in rs:
            if r['fmt_status'] != 'ok': vals.append(0.0)
            elif r.get('f_' + it if it in FI else it) is not None: vals.append(r['f_' + it] if it in FI else r[it])
        d['fmt_' + it] = (sum(vals) / len(vals)) if vals else None
    return d

parts = [('전체', None), ('개발에 안 쓴 569건(보류 532 + 신규 37)', 'held'), ('개발에 쓴 1,993건 중 한글 저장본 있는 건', 'dev')]
md = []
md.append(f'# hwpai 5차 보완판 대 공개 도구 3종 — 대량표본 비교 (독립 채점기 판 1.0, 2026-11-21)\n')
md.append(f'채점 문서 {len(rows["hwpai"])}건(원본 2,562건 중 한글 2024 저장본이 있는 건). 채점기 코드 무수정(`/home/claude/scorer`).\n')
allsum = {}
for title, sp in parts:
    md.append(f'\n## {title}\n')
    res = {}
    for t in TOOLS:
        rs = [r for r in rows[t] if sp is None or r['split'] == sp]
        res[t] = (stats(rs, t), item_means(rs), len(rs))
    allsum[title] = res
    n = res['hwpai'][2]
    md.append(f'문서 {n}건\n')
    md.append('| 항목 | ' + ' | '.join(TOOLS) + ' |\n|---|' + '---|' * len(TOOLS))
    for k in res['hwpai'][0]:
        if k == '문서 수': continue
        md.append(f'| {k} | ' + ' | '.join(str(res[t][0][k]) for t in TOOLS) + ' |')
    md.append('\n항목별 평균(실패 문서는 0점으로 분모 포함, 정답에 그 항목이 없는 문서는 분모 제외)\n')
    md.append('| 항목 | ' + ' | '.join(TOOLS) + ' |\n|---|' + '---|' * len(TOOLS))
    for k in res['hwpai'][1]:
        md.append(f'| {k} | ' + ' | '.join(('' if res[t][1][k] is None else f'{res[t][1][k]:.4f}') for t in TOOLS) + ' |')
json.dump({k: {t: [dict(v[0]), v[2]] for t, v in r.items()} for k, r in allsum.items()}, open(f'{R}/summary.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
# 나빠진/실패 문서
bad = []
for k in keys:
    rr = {t: next((r for r in rows[t] if r['key'] == k), None) for t in TOOLS} if False else None
idx = {t: {r['key']: r for r in rows[t]} for t in TOOLS}
with open(f'{R}/failed_docs.csv', 'w', encoding='utf-8-sig', newline='') as fh:
    w = csv.writer(fh); w.writerow(['key', 'split', 'tool', 'conv_status', 'text_pass_a', 'fmt_pass', 'fail_text_a', 'fail_fmt', 'other_tools_all_pass'])
    for k in keys:
        for t in TOOLS:
            r = idx[t].get(k)
            if r and not r['all_pass']:
                others = ','.join(o for o in TOOLS if o != t and idx[o].get(k) and idx[o][k]['all_pass'])
                w.writerow([k, r['split'], t, r['status'], r['text_pass_a'], r['fmt_pass'], r['fail_text_a'], r['fail_fmt'], others])
hw_worse = [k for k in keys if idx['hwpai'].get(k) and not idx['hwpai'][k]['all_pass'] and any(idx[o].get(k) and idx[o][k]['all_pass'] for o in TOOLS[1:])]
hw_fail = [k for k in keys if idx['hwpai'].get(k) and not idx['hwpai'][k]['all_pass']]
md.append(f'\n## hwpai 종합 통과 못한 문서: {len(hw_fail)}건, 그중 다른 도구는 통과한 문서(hwpai가 더 나쁜 문서): {len(hw_worse)}건 (목록: failed_docs.csv)\n')
open(f'{R}/_agg_md_body.md', 'w', encoding='utf-8').write('\n'.join(md))
print('\n'.join(md[:60]))
