"""경량판(Node.js 없음) Windows 기능 실기 — 화면(끌어놓기)·폴더 감시·AI 연결(MCP)·시각 비교·자가 점검.
원본은 사본으로만 시험한다. 결과: lite_func_result.txt"""
import os, sys, json, time, shutil, subprocess, urllib.request, urllib.parse, re, glob, threading, queue

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'lite4', 'hwpai-portable-win64')
PY = os.path.join(ROOT, 'python', 'python.exe')
if os.name != 'nt':
    PY = sys.executable
APP = os.path.join(ROOT, 'app')
SAMPLES = sorted(glob.glob(os.path.join(HERE, 'in1000', '*.hwp')))[:20]
W = os.path.join(HERE, 'func_work4')
LOG = open(os.path.join(HERE, 'lite_func_result4.txt'), 'w', encoding='utf-8')
ENV = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
ENV['PATH'] = os.pathsep.join(x for x in ENV.get('PATH', '').split(os.pathsep) if 'nodejs' not in x.lower())   # 설치된 Node.js 를 숨겨 Node 없는 PC 를 재현
ENV.pop('HWPAI_NODE', None); ENV.pop('HWPAI_RHWP_CORE', None)
RES = {}


def L(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True); LOG.write(s + '\n'); LOG.flush()


def fresh(name, n=5):
    d = os.path.join(W, name)
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for f in SAMPLES[:n]:
        shutil.copy(f, d)
    return d


def run(args, timeout=900):
    t = time.time()
    p = subprocess.run([PY, '-B', '-m', 'hwpai'] + args, cwd=APP, env=ENV, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=timeout)
    return p.returncode, p.stdout + p.stderr, round(time.time() - t, 1)


shutil.rmtree(W, ignore_errors=True); os.makedirs(W)
L('== 경량판 기능 실기', time.strftime('%Y-%m-%d %H:%M:%S'), '==')
L('node 폴더 있음?', os.path.isdir(os.path.join(ROOT, 'node')), '· 시험 PATH 의 node:', shutil.which('node', path=ENV['PATH']))
L('입력 표본', len(SAMPLES), '건 (대량표본 원본 앞에서)')

# 1 자가 점검
rc, out, s = run(['doctor'], 600)
ok = rc == 0 and '실패' not in re.sub(r'실패 0', '', out.split('결과')[-1] if '결과' in out else out)
L('\n[1 자가 점검 doctor] rc', rc, f'{s}초'); L(out[-1500:])
RES['doctor'] = rc == 0

# 2 화면(끌어놓기) — 화면 서버를 띄우고 브라우저가 하는 것과 같은 요청(올리기→변환→상태)
L('\n[2 화면 끌어놓기 gui]')
g = subprocess.Popen([PY, '-B', '-m', 'hwpai', 'gui', '--no-browser', '--port', '8798'], cwd=APP, env=ENV,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
url = None; t0 = time.time()
while time.time() - t0 < 60:
    line = g.stdout.readline()
    m = re.search(r'(http://127\.0\.0\.1:\d+/\?t=[\w-]+)', line or '')
    if m:
        url = m.group(1); break
try:
    base, tok = url.split('/?t=')
    def req(path, data=None, raw=None):
        u = f'{base}{path}{"&" if "?" in path else "?"}t={tok}'
        body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
        r = urllib.request.Request(u, data=body, method='POST' if body is not None else 'GET')
        return json.loads(urllib.request.urlopen(r, timeout=120).read().decode('utf-8'))
    page = urllib.request.urlopen(url, timeout=30).read().decode('utf-8')
    L('화면 열림:', len(page), '바이트')
    files = [{'rel': os.path.basename(f), 'size': os.path.getsize(f), 'mtime': int(os.path.getmtime(f) * 1000)} for f in SAMPLES[:10]]
    up = req('/api/upload/begin', {'name': '경량판끌어놓기시험', 'files': files})
    for f in SAMPLES[:10]:
        req('/api/upload/file?id=' + up['id'] + '&rel=' + urllib.parse.quote(os.path.basename(f)), raw=open(f, 'rb').read())
    req('/api/start', {'upload': up['id'], 'jobs': 2})
    t1 = time.time(); st = {}
    while time.time() - t1 < 900:
        st = req('/api/status')
        if st.get('status') not in ('실행 중', '대기'):
            break
        time.sleep(2)
    L('상태', st.get('status'), '· 처리', st.get('done'), '/', st.get('total'), '· 통계', json.dumps(st.get('stats'), ensure_ascii=False)[:300])
    eng = {r.get('엔진') for r in (st.get('rows') or []) if isinstance(r, dict)}
    L('엔진', eng)
    RES['gui'] = st.get('done') == 10 and not st.get('error')
except Exception as e:
    L('화면 시험 오류', type(e).__name__, e); RES['gui'] = False
finally:
    g.terminate()

# 3 폴더 감시(자동 변환 + 제자리 교체 기본)
L('\n[3 폴더 감시 watch]')
d3 = fresh('감시 폴더', 0)
w = subprocess.Popen([PY, '-B', '-m', 'hwpai', 'watch', d3, '--interval', '5', '--rounds', '6'], cwd=APP, env=ENV,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
time.sleep(8)
for f in SAMPLES[:5]:
    shutil.copy(f, d3)          # 감시 중에 새 HWP 가 들어옴
try:
    wout = w.communicate(timeout=600)[0]
except subprocess.TimeoutExpired:
    w.kill(); wout = w.communicate()[0]
hx = glob.glob(os.path.join(d3, '*.hwpx')); hw = glob.glob(os.path.join(d3, '*.hwp'))
arc = glob.glob(d3 + '_원본보관*' + os.sep + '**' + os.sep + '*.hwp', recursive=True)
L(wout[-1200:]); L('감시 폴더: HWPX', len(hx), '· 남은 HWP', len(hw), '· 보관된 원본', len(arc))
RES['watch'] = len(hx) == 5

# 4 AI 연결(MCP) — AI 앱이 하는 것과 같은 JSON-RPC 요청
L('\n[4 AI 연결 MCP]')
d4 = fresh('MCP 폴더', 3)
m = subprocess.Popen([PY, '-B', '-m', 'hwpai', 'mcp'], cwd=APP, env=dict(ENV, HWPAI_MCP_ROOTS=W),
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
def call(i, method, params):
    m.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}, ensure_ascii=False) + '\n'); m.stdin.flush()
    return json.loads(m.stdout.readline())
try:
    r = call(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
    m.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n'); m.stdin.flush()
    tl = call(2, 'tools/list', {})
    names = [t['name'] for t in tl['result']['tools']]
    L('도구', len(names), names)
    rc_ = call(3, 'tools/call', {'name': 'convert_to_hwpx', 'arguments': {'path': d4, 'out': os.path.join(W, 'MCP 결과')}})
    txt = rc_['result']['content'][0]['text']; L('convert_to_hwpx →', txt[:300])
    one = sorted(glob.glob(os.path.join(W, 'MCP 결과', '*.hwpx')))[0]
    orig = os.path.join(d4, os.path.basename(one)[:-5] + '.hwp')
    ra = call(4, 'tools/call', {'name': 'audit', 'arguments': {'original': orig, 'converted': one}})
    at = ra['result']['content'][0]['text']; L('audit →', at[:200].replace('\n', ' '))
    rr = call(5, 'tools/call', {'name': 'read_hwp', 'arguments': {'path': orig, 'max_chars': 300}})
    L('read_hwp →', rr['result']['content'][0]['text'][:150].replace('\n', ' '))
    RES['mcp'] = len(names) >= 8 and 'PASS' in txt and ('정상' in at or 'PASS' in at)
except Exception as e:
    L('MCP 오류', type(e).__name__, e, m.stderr.read()[-800:] if m.poll() is not None else ''); RES['mcp'] = False
finally:
    m.kill()

# 5 시각 비교(렌더) — Node 없이 렌더 일꾼
L('\n[5 시각 비교 visual]')
try:
    one = sorted(glob.glob(os.path.join(W, 'MCP 결과', '*.hwpx')))[0]
    orig = os.path.join(d4, os.path.basename(one)[:-5] + '.hwp')
    rc, out, s = run(['visual', orig, one, '--out', os.path.join(W, '시각비교.html'), '--pages', '3'], 600)
    L('rc', rc, f'{s}초', out[-600:])
    RES['visual'] = rc == 0 and os.path.exists(os.path.join(W, '시각비교.html'))
except Exception as e:
    L('시각 비교 오류', e); RES['visual'] = False

# 6 끌어놓기 명령(drop) — 바탕화면 아이콘에 끌어놓을 때 쓰는 경로
L('\n[6 끌어놓기 명령 drop]')
d6 = fresh('끌어놓기 폴더', 5)
rc, out, s = run(['drop', d6, '--no-open'], 900)
L('rc', rc, f'{s}초', out[-500:])
import csv
led = glob.glob(d6 + '*_hwpx변환' + os.sep + '이관대장.csv')
engs = sorted({r['엔진'] for r in csv.DictReader(open(led[0], encoding='utf-8-sig'))}) if led else []
L('drop 이관대장 엔진:', engs)
RES['drop_engine_py'] = engs == ['rhwp-py']
RES['drop'] = rc == 0 and len(glob.glob(os.path.join(d6, '*.hwpx'))) + len(glob.glob(d6 + '*_hwpx변환' + os.sep + '*.hwpx')) >= 5

L('\n== 결과 ==')
for k, v in RES.items():
    L(f'{k}: {"통과" if v else "실패"}')
L('== 끝 ==')
