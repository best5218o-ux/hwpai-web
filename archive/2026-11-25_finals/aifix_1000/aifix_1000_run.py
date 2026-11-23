"""검증서 → AI 수정 1,000건 실증: 실제 정부 HWP 1,000건의 변환본에 변환 오류를 넣고,
검증서(쉬운설명.AI가_고치려면)만으로 고친 뒤 다시 검증해 정상 변환이 되는지 센다."""
import sys, os, json, random, zipfile, shutil, tempfile, re, time, collections
sys.path.insert(0, '/home/claude/hwpai_v9/app')
from lxml import etree
from hwpai.audit import audit
from hwpai.edit import replace_text
HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
ns = {'hp': HP}
src_dir, conv_dir, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
rnd = random.Random(20261123)

def garble(s):
    i = rnd.randrange(0, max(1, len(s) - 4)); n = min(4, len(s) - i)
    return s[:i] + '□' * n + s[i + n:]

def inject(hwpx, dst, kind):
    zin = zipfile.ZipFile(hwpx)
    name = 'Contents/section0.xml'
    root = etree.fromstring(zin.read(name))
    ts = root.findall('.//hp:t', ns)
    def in_tbl(e):
        p = e.getparent()
        while p is not None:
            if p.tag == '{%s}tbl' % HP: return True
            p = p.getparent()
        return False
    def ok_text(t):
        return t.text and len(t.text.strip()) >= 8 and len(t) == 0 and '□' not in t.text
    what = None
    if kind == '글 바뀜':
        c = [t for t in ts if ok_text(t) and not in_tbl(t)]
        if c:
            t = rnd.choice(c); old = t.text; t.text = garble(old); what = (old, t.text)
    elif kind == '표 칸 글 바뀜':
        c = [t for t in ts if ok_text(t) and in_tbl(t)]
        if c:
            t = rnd.choice(c); old = t.text; t.text = garble(old); what = (old, t.text)
    elif kind == '문단 빠짐':
        ps = [p for p in root.findall('hp:p', ns)[1:]
              if not p.xpath('.//hp:tbl|.//hp:pic|.//hp:ctrl|.//hp:rect|.//hp:container|.//hp:equation', namespaces=ns)
              and len(''.join(p.xpath('.//hp:t/text()', namespaces=ns)).strip()) >= 8]
        if ps:
            p = rnd.choice(ps); what = (''.join(p.xpath('.//hp:t/text()', namespaces=ns)), ''); root.remove(p)
    if what is None:
        return None
    data = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(dst, 'w') as zout:
        for it in zin.infolist():
            b = data if it.filename == name else zin.read(it.filename)
            zout.writestr(it, b)
    return what

kinds = ['글 바뀜', '표 칸 글 바뀜', '문단 빠짐']
res = {}; tmp = tempfile.mkdtemp(prefix='aifix_')
files = sorted(f for f in os.listdir(conv_dir) if f.endswith('.hwpx'))
t0 = time.time()
for i, f in enumerate(files):
    stem = f[:-5]; orig = os.path.join(src_dir, stem + '.hwp'); conv = os.path.join(conv_dir, f)
    r = {'kind': None}
    try:
        base = audit(orig, conv).to_dict()['verdict']
        r['base'] = base
        if base != 'PASS':
            r['skip'] = 'base not PASS'; res[stem] = r; continue
        ks = kinds[i % 3:] + kinds[:i % 3]
        dmg = os.path.join(tmp, 'd.hwpx'); w = None
        for k in ks:
            w = inject(conv, dmg, k)
            if w: r['kind'] = k; r['what'] = w; break
        if not w:
            r['skip'] = 'no target'; res[stem] = r; continue
        d = audit(orig, dmg).to_dict(); r['damaged'] = d['verdict']
        fix = d['쉬운설명']['AI가_고치려면']
        r['n_fix'] = len(fix['수정안']); r['auto'] = sum(1 for x in fix['수정안'] if x['자동수정'])
        if not fix['replace_text_한번에']:
            r['fixed'] = 'no auto fix'; res[stem] = r; continue
        fixed = os.path.join(tmp, 'f.hwpx')
        if os.path.exists(fixed): os.remove(fixed)
        r['map'] = fix['replace_text_한번에']
        rr = replace_text(dmg, fix['replace_text_한번에'], fixed)
        r['nf'] = rr['not_found']
        d2 = audit(orig, rr['out']).to_dict(); r['fixed'] = d2['verdict']
        r['text_exact'] = d2['checks'].get('text_exact'); r['why2'] = [x['msg'][:200] for x in d2['reasons']][:2]
        os.remove(rr['out'])
    except Exception as e:
        r['err'] = f'{type(e).__name__}: {str(e)[:150]}'
    res[stem] = r
    if i % 100 == 0:
        print(i, round(time.time() - t0), flush=True)
json.dump(res, open(out_json, 'w'), ensure_ascii=False)
c = collections.Counter((v.get('kind'), v.get('damaged'), v.get('fixed')) for v in res.values())
for k, n in sorted(c.items(), key=lambda x: -x[1]): print(n, k)
print('elapsed', round(time.time() - t0))
