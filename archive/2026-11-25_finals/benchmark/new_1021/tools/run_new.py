#!/usr/bin/env python3
"""신규 HWP→HWPX 변환 도구 일괄 실행기 (채점 없음). 입력폴더 → 출력폴더/<도구>/<원본SHA256앞12>.hwpx + results.csv
사용: run_new.py <입력폴더> <출력폴더> [--tools a,b] [--jobs 2] [--timeout 120] [--limit N] [--resume]
 - 도구별 120초(기본) 제한, 실패·시간초과·빈 출력은 results.csv 에 상태(ok/fail/timeout/empty/diskfull)와 메시지로 기록.
 - 기존 4종(kordoc, hwp2hwpx, pyhwpxlib + 부가 hwpConverter)은 /home/claude/opentools/run_all.py 의 명령을 그대로 재사용(--tools 에 이름만 주면 됨).
 - 설치 위치는 환경변수 BCN(기본 /dev/shm/bcn). 설치가 없으면 install.sh 를 먼저 실행.
 - 출력은 항상 .hwpx (@ohah/hwpjs 는 text-only 손실 허용 모드라 ohah_textonly 로 따로 표기)."""
import argparse, csv, hashlib, os, shutil, signal, subprocess, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
BCN = Path(os.environ.get('BCN', '/dev/shm/bcn'))
NM = BCN / 'npm/node_modules'
W = HERE / 'wrappers'
PYV = str(BCN / 'venv/bin/python')
CP_ASI = f"{BCN}/asi/out:{BCN}/asi/hwp2hwpx-1.0.0.jar:{BCN}/asi/hwplib-1.1.10.jar:{BCN}/asi/hwpxlib-1.0.9.jar"
# 도구: (명령 생성(in,out), 출력이 파일 하나인가(False 면 출력 폴더를 만들어 그 안의 .hwpx 를 옮김))
TOOLS = {
 'rhwp':        lambda i, o: ['node', str(W/'rhwp_wasm_hwpx.mjs'), i, o],
 'hwpforge':    lambda i, o: [PYV, str(W/'hwpforge_conv.py'), i, o],
 'hwp-convert': lambda i, o: ['node', str(W/'npm_hwptohwpx.mjs'), 'hwp-convert', i, o],
 'hwpxjs':      lambda i, o: ['node', str(W/'npm_hwptohwpx.mjs'), '@ssabrojs/hwpxjs', i, o],
 'jhwpx':       lambda i, o: ['node', str(BCN/'src/jhwpx-converter-damulhan/dist/jhwpx-converter-cli.js'), i, o],
 'ahwp':        lambda i, o: [str(BCN/'bin/ahwp'), 'convert', i, '-o', o],
 'hwpx-js':     lambda i, o: ['node', str(W/'hwpxjs_rw.cjs'), i, o],
 'ohah_textonly': lambda i, o: ['node', str(NM/'@ohah/hwpjs/dist/hwpjs.mjs'), 'convert', i, '--to', 'hwpx', '--loss-policy', 'text-only', '--output', o],
 'h2h_asi':     lambda i, o: ['java', '-cp', CP_ASI, 'Hwp2HwpxCli', i, o],
 'h2h_kossembly': lambda i, o: [str(BCN/'venv/bin/hwp2hwpx'), i, '-o', o + '.d'],      # 출력 폴더 방식: 아래 post 처리
 'h2h_yuson':   lambda i, o: [str(BCN/'venv_yuson/bin/hwp2hwpx'), i, '-o', o + '.d'],
}
DIROUT = {'h2h_kossembly', 'h2h_yuson'}   # -o 가 폴더인 도구: o+'.d'/<원본이름>.hwpx 를 o 로 옮긴다
# 기존 도구(opentools/run_all.py)
try:
    sys.path.insert(0, '/home/claude/opentools'); import run_all as _old
    for k in ('kordoc', 'hwp2hwpx', 'pyhwpxlib', 'hwpConverter'):
        _mk = _old.TOOLS[k][1]; TOOLS[k] = _mk
    ENV_OLD = _old.ENV
except Exception as e:  # opentools 가 없어도 신규 도구는 돈다
    ENV_OLD = {}
ENV = dict(os.environ, NODE_PATH=str(NM), PYTHONIOENCODING='utf-8', PYTHONUTF8='1', BCN_NODE_MODULES=str(NM))
ENV.pop('PYTHONPATH', None)

def short(t, n=400): return t if len(t) <= n else t[:n//2] + ' ... ' + t[-n//2:]
def sha12(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()[:12]

def run_one(tool, src, sha, outroot, timeout):
    od = outroot / tool; od.mkdir(parents=True, exist_ok=True)
    out = od / f'{sha}.hwpx'
    if out.exists(): out.unlink()
    if shutil.disk_usage(str(outroot)).free < 3 << 20:
        return [tool, src.name, 'diskfull', 0, 0, sha, '디스크 여유 3MB 미만이라 실행 안 함']
    t0 = time.time(); status = 'ok'; msg = ''
    env = ENV_OLD and dict(ENV_OLD, BCN_NODE_MODULES=str(NM)) if tool in ('kordoc', 'hwp2hwpx', 'pyhwpxlib', 'hwpConverter') else ENV
    try:
        p = subprocess.Popen(TOOLS[tool](str(src), str(out)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True, cwd=str(od))
        try:
            so, se = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); so, se = p.communicate(); status = 'timeout'; msg = f'>{timeout}s'
        else:
            if p.returncode != 0:
                status = 'fail'; msg = short(se.decode('utf-8', 'replace').strip() or so.decode('utf-8', 'replace').strip())
            elif se.strip(): msg = short(se.decode('utf-8', 'replace').strip(), 200)
    except Exception as e:
        status = 'fail'; msg = f'{type(e).__name__}: {e}'
    if tool in DIROUT:   # 폴더 출력 도구의 결과 파일을 표준 이름으로
        d = Path(str(out) + '.d'); c = d / (src.stem + '.hwpx')
        if c.exists(): c.replace(out)
        shutil.rmtree(d, ignore_errors=True)
    sec = round(time.time() - t0, 2); size = out.stat().st_size if out.exists() else 0
    if status == 'ok':
        if not out.exists(): status = 'fail'; msg = (msg + ' 출력 파일 없음').strip()
        elif size == 0: status = 'empty'
    if status == 'fail' and ('No space left' in msg or 'ENOSPC' in msg): status = 'diskfull'
    return [tool, src.name, status, sec, size, sha, msg.replace('\n', ' | ')]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--tools'); ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--resume', action='store_true'); ap.add_argument('--timeout', type=int, default=120); ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    inp = Path(a.inp).absolute(); files = sorted(inp.rglob('*.hwp')) if inp.is_dir() else [inp]
    if a.limit: files = files[:a.limit]
    tools = a.tools.split(',') if a.tools else [t for t in TOOLS if t not in ('kordoc', 'hwp2hwpx', 'pyhwpxlib', 'hwpConverter')]
    outroot = Path(a.out).absolute(); outroot.mkdir(parents=True, exist_ok=True)
    shas = {f: sha12(f) for f in files}; jobs = [(t, f) for f in files for t in tools]
    rf = outroot / 'results.csv'; keep = []
    if a.resume and rf.exists():
        keep = [r for r in csv.reader(open(rf, encoding='utf-8-sig')) if r and r[0] != '도구' and r[2] != 'diskfull']
        done = {(r[0], r[1]) for r in keep}; jobs = [(t, f) for t, f in jobs if (t, f.name) not in done]
    n = 0
    with open(rf, 'w', newline='', encoding='utf-8-sig') as fh, ThreadPoolExecutor(a.jobs) as ex:
        w = csv.writer(fh); w.writerow(['도구', '파일', '상태', '초', '출력크기', '원본SHA12', '메시지']); w.writerows(keep)
        futs = [ex.submit(run_one, t, f, shas[f], outroot, a.timeout) for t, f in jobs]
        for fu in futs:
            row = fu.result(); w.writerow(row); fh.flush(); n += 1
            if n % 50 == 0: print(f'{n}/{len(jobs)}', file=sys.stderr, flush=True)
    c = Counter((r[0], r[2]) for r in csv.reader(open(rf, encoding='utf-8-sig')) if r[0] != '도구')
    for t in tools: print(t, {s: c[(t, s)] for s in ('ok', 'fail', 'timeout', 'empty', 'diskfull') if c[(t, s)]})
if __name__ == '__main__': main()
