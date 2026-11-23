"""rhwp(@rhwp/core, MIT) WASM 엔진을 Node.js 없이 파이썬(wasmtime)에서 돌리는 연결부.

변환(HWP→HWPX)에 필요한 연결만 구현한다. 1,000건 변환에서 엔진이 부른 외부 기능은
externref 표 초기화 하나뿐이었다(Node 계측). 나머지 브라우저 기능(캔버스 등)은 부르면
즉시 오류로 끝내 조용히 틀린 결과를 내지 않게 한다.
"""
import wasmtime as wt


class EngineError(Exception):
    pass


class _JSDate:
    """자바스크립트 Date 의 필요한 부분(시각 ms, 그 시각의 지역 시간대 차이). 문서 날짜 필드 서식에 쓰인다."""
    def __init__(self, ms):
        self.ms = ms

    def tz_offset(self):
        """JS getTimezoneOffset 과 같은 뜻: (UTC - 지역시각) 분. 그 시각의 지역 규칙(일광절약 포함)을 따른다."""
        import time as _t, datetime as _d
        try:
            return -_t.localtime(self.ms / 1000.0).tm_gmtoff / 60.0
        except (OverflowError, OSError, ValueError):
            off = _d.datetime.now().astimezone().utcoffset()
            return -off.total_seconds() / 60.0


def _load_js_bodies():
    """엔진과 함께 온 연결 코드(rhwp.js)에서 외부 기능 이름별 본문을 읽어, 이름만으로 구분이 안 되는 기능을 본문으로 가린다."""
    import os, re
    out = {}
    p = os.environ.get('HWPAI_RHWP_JS') or os.path.join(os.path.dirname(__file__), '..', '..', 'vendor', 'rhwp-core', 'rhwp.js')
    try:
        src = open(p, encoding='utf-8').read()
    except Exception:
        return out
    for m in re.finditer(r'\n        (__w\w+): function\(', src):
        start = m.end()
        nxt = src.find('\n        __w', start)
        out[m.group(1)] = src[start: nxt if nxt > 0 else start + 600]
    return out


_JS_BODY = _load_js_bodies()


def _cache_path(wasm_path):
    import hashlib, os
    h = hashlib.sha256(open(wasm_path, 'rb').read()).hexdigest()[:16]
    base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), '.cache')
    d = os.path.join(base, 'hwpai', 'engine-cache')
    return os.path.join(d, f'rhwp-{h}-wt{getattr(wt, "__version__", "")}.cwasm')


def _load_module(engine, wasm_path):
    """첫 실행 때 한 번 기계어로 바꿔(약 15초) 사용자 PC 캐시에 두고, 다음부터는 바로 읽는다.
    캐시는 엔진 파일 해시로 이름을 붙여 엔진이 바뀌면 새로 만든다. 캐시가 깨졌으면 다시 만든다."""
    import os
    cp = _cache_path(wasm_path)
    if os.path.exists(cp):
        try:
            return wt.Module.deserialize_file(engine, cp)
        except Exception:
            pass
    m = wt.Module.from_file(engine, wasm_path)
    try:
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        tmp = cp + '.part'
        with open(tmp, 'wb') as f:
            f.write(m.serialize())
        os.replace(tmp, cp)
    except Exception:
        pass
    return m


class RhwpEngine:
    def __init__(self, wasm_path):
        cfg = wt.Config()
        self.engine = wt.Engine(cfg)
        self.store = wt.Store(self.engine)
        self.module = _load_module(self.engine, wasm_path)
        self.ex = None
        imports = []
        for imp in self.module.imports:
            ft = imp.type
            name = imp.name
            imports.append(wt.Func(self.store, ft, self._make(name, ft)))
        inst = wt.Instance(self.store, self.module, imports)
        self.ex = inst.exports(self.store)
        self.mem = self.ex['memory']
        self.ex['__wbindgen_start'](self.store)

    # ---- 외부 기능(import) ----
    def _make(self, name, ft):
        base = name.rsplit('_', 1)[0] if len(name.rsplit('_', 1)[-1]) == 16 else name
        nparams = len(ft.params)
        if base == '__wbindgen_init_externref_table':
            def f():
                t = self.ex['__wbindgen_externrefs']
                off = t.grow(self.store, 4, wt.Val.externref(None))
                t.set(self.store, 0, wt.Val.externref(None))
                t.set(self.store, off + 0, wt.Val.externref(None))
                t.set(self.store, off + 1, wt.Val.externref(None))
                t.set(self.store, off + 2, wt.Val.externref(True))
                t.set(self.store, off + 3, wt.Val.externref(False))
            return f
        js = _JS_BODY.get(name, '')
        if base == '__wbindgen_cast' and nparams == 2:
            def f(p, n):   # 문자열 → 엔진 쪽 값(주로 오류 메시지)
                return wt.Val.externref(self._str(p, n))
            return f
        if base == '__wbindgen_cast' and nparams == 1:
            def f(v):      # 숫자 등 → 엔진 쪽 값
                return wt.Val.externref(v)
            return f
        if base == '__wbg___wbindgen_throw':
            def f(p, n):
                raise EngineError(self._str(p, n))
            return f
        if 'new Date()' in js:
            def f():
                import time as _t
                return wt.Val.externref(_JSDate(_t.time() * 1000.0))
            return f
        if 'new Date(arg0)' in js:
            def f(v):
                return wt.Val.externref(_JSDate(float(v)))
            return f
        if '.getTimezoneOffset()' in js:
            def f(d):
                return float(d.tz_offset())
            return f
        if '.getTime()' in js:
            def f(d):
                return float(d.ms)
            return f
        if 'new Error()' in js:
            def f():
                return wt.Val.externref({'error': ''})
            return f
        if base == '__wbg_stack':
            def f(retp, _obj):
                self._put_str(retp, '')
            return f
        if base == '__wbg_error' and 'console.error' in js:
            def f(p, n):
                self.ex['__wbindgen_free'](self.store, p, n, 1)
            return f

        def unsupported(*a):
            raise EngineError('엔진이 지원하지 않는 외부 기능을 불렀습니다: ' + base)
        return unsupported

    # ---- 메모리 도우미 ----
    def _str(self, p, n):
        return bytes(self.mem.read(self.store, p, p + n)).decode('utf-8')

    def _put_bytes(self, data):
        p = self.ex['__wbindgen_malloc'](self.store, len(data), 1)
        self.mem.write(self.store, data, p)
        return p

    def _put_str(self, retp, s):
        b = s.encode('utf-8')
        p = self._put_bytes(b) if b else 0
        self.mem.write(self.store, int(len(b)).to_bytes(4, 'little'), retp + 4)
        self.mem.write(self.store, int(p).to_bytes(4, 'little'), retp)

    def _take_err(self, idx):
        t = self.ex['__wbindgen_externrefs']
        v = t.get(self.store, idx)
        self.ex['__externref_table_dealloc'](self.store, idx)
        v = v.value if isinstance(v, wt.Val) else v
        return EngineError(str(v))

    # ---- 변환 ----
    def hwp_to_hwpx(self, data: bytes, password: str = None):
        """HWP 바이트 → (HWPX 바이트, 내용손실 JSON 문자열)"""
        s, ex = self.store, self.ex
        p = self._put_bytes(data)
        if password:
            pb = password.encode('utf-8')
            q = self._put_bytes(pb)
            r = ex['hwpdocument_openWithPassword'](s, p, len(data), q, len(pb))
        else:
            r = ex['hwpdocument_new'](s, p, len(data))
        if r[2]:
            raise self._take_err(r[1])
        doc = r[0]
        try:
            r = ex['hwpdocument_exportHwpxWithReport'](s, doc)
            if r[2]:
                raise self._take_err(r[1])
            de = r[0]
            try:
                c = ex['documentexport_contentLoss'](s, de)
                loss = self._str(c[0], c[1])
                ex['__wbindgen_free'](s, c[0], c[1], 1)
                t = ex['documentexport_takeBytes'](s, de)
                if t[3]:
                    raise self._take_err(t[2])
                out = bytes(self.mem.read(s, t[0], t[0] + t[1]))
                ex['__wbindgen_free'](s, t[0], t[1], 1)
            finally:
                ex['__wbg_documentexport_free'](s, de, 0)
        finally:
            ex['__wbg_hwpdocument_free'](s, doc, 0)
        return out, loss

    def _take_str_ret(self, r):
        """(ptr, len, err_idx, is_err) 꼴 문자열 반환 처리"""
        if r[3]:
            raise self._take_err(r[2])
        s = self._str(r[0], r[1])
        self.ex['__wbindgen_free'](self.store, r[0], r[1], 1)
        return s

    def blank(self, text=None, as_hwp=False):
        """엔진 내장 빈 서식 문서(자가 점검용) — HWP 또는 HWPX 바이트"""
        s, ex = self.store, self.ex
        doc = ex['hwpdocument_createEmpty'](s)
        try:
            self._take_str_ret(ex['hwpdocument_createBlankDocument'](s, doc))
            if text:
                b = text.encode('utf-8')
                p = self._put_bytes(b)
                self._take_str_ret(ex['hwpdocument_insertText'](s, doc, 0, 0, 0, p, len(b)))
            if as_hwp:
                t = ex['hwpdocument_exportHwp'](s, doc)
                if t[3]:
                    raise self._take_err(t[2])
                out = bytes(self.mem.read(s, t[0], t[0] + t[1]))
                ex['__wbindgen_free'](s, t[0], t[1], 1)
                return out
            r = ex['hwpdocument_exportHwpxWithReport'](s, doc)
            if r[2]:
                raise self._take_err(r[1])
            de = r[0]
            try:
                t = ex['documentexport_takeBytes'](s, de)
                if t[3]:
                    raise self._take_err(t[2])
                out = bytes(self.mem.read(s, t[0], t[0] + t[1]))
                ex['__wbindgen_free'](s, t[0], t[1], 1)
            finally:
                ex['__wbg_documentexport_free'](s, de, 0)
            return out
        finally:
            ex['__wbg_hwpdocument_free'](s, doc, 0)

    def render_svgs(self, data: bytes, max_pages: int):
        """문서를 쪽별 SVG 문자열로 — 변환 전후 시각 비교(visual)용. (쪽 수, [svg...])"""
        s, ex = self.store, self.ex
        p = self._put_bytes(data)
        r = ex['hwpdocument_new'](s, p, len(data))
        if r[2]:
            raise self._take_err(r[1])
        doc = r[0]
        try:
            n = ex['hwpdocument_pageCount'](s, doc) & 0xFFFFFFFF
            svgs = [self._take_str_ret(ex['hwpdocument_renderPageSvg'](s, doc, i)) for i in range(min(n, max_pages or 5))]
            return n, svgs
        finally:
            ex['__wbg_hwpdocument_free'](s, doc, 0)


def render_main():
    """render_worker.mjs 와 같은 약속의 파이썬 렌더 일꾼."""
    import sys, os, json, time
    eng = RhwpEngine(os.path.join(sys.argv[2], 'rhwp_bg.wasm'))
    out = sys.stdout
    out.write(json.dumps({'ready': True}) + '\n'); out.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line); t0 = time.perf_counter(); res = {'ok': False}
        try:
            n, svgs = eng.render_svgs(open(req['src'], 'rb').read(), req.get('maxPages') or 5)
            res['pages'] = n
            os.makedirs(req['outdir'], exist_ok=True)
            for i, sv in enumerate(svgs):
                with open(os.path.join(req['outdir'], f'p{i}.svg'), 'w', encoding='utf-8') as f:
                    f.write(sv)
            res.update(rendered=len(svgs), ok=True)
        except Exception as e:
            res['error'] = str(e)[:300]
        res['ms'] = round((time.perf_counter() - t0) * 1000, 1)
        out.write(json.dumps(res, ensure_ascii=False) + '\n'); out.flush()


def main():
    """rhwp_worker.mjs 와 같은 약속(한 줄 JSON 요청 → 한 줄 JSON 응답)의 파이썬 일꾼."""
    import sys, os, json, time
    core = sys.argv[1]
    eng = RhwpEngine(os.path.join(core, 'rhwp_bg.wasm'))
    try:
        version = json.load(open(os.path.join(core, 'package.json'), encoding='utf-8')).get('version', '?')
    except Exception:
        version = '?'
    out = sys.stdout
    out.write(json.dumps({'ready': True, 'engine': 'rhwp-py', 'version': version}) + '\n'); out.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except Exception:
            out.write(json.dumps({'ok': False, 'error': 'bad request'}) + '\n'); out.flush(); continue
        t0 = time.perf_counter()
        res = {'id': req.get('id'), 'ok': False}
        try:
            dst = req['dst']
            if req.get('op') == 'empty':
                b = eng.blank(req.get('text'), as_hwp=dst.lower().endswith('.hwp'))
                loss = None
            else:
                t1 = time.perf_counter()
                b, ls = eng.hwp_to_hwpx(open(req['src'], 'rb').read(), req.get('password'))
                res['load_ms'] = round((time.perf_counter() - t1) * 1000, 1)
                try:
                    loss = json.loads(ls)
                except Exception:
                    loss = None
            os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
            tmp = dst + '.part'
            with open(tmp, 'wb') as f:
                f.write(b)
            os.replace(tmp, dst)
            res.update(ok=True, bytes=len(b))
            if loss is not None:
                res['loss'] = loss
        except Exception as e:
            res['error'] = str(e)[:500]
            try:
                eng = RhwpEngine(os.path.join(core, 'rhwp_bg.wasm'))   # 엔진 상태가 깨졌을 수 있으니 새로 올린다(캐시라 빠름)
            except Exception:
                pass
        res['ms'] = round((time.perf_counter() - t0) * 1000, 1)
        out.write(json.dumps(res, ensure_ascii=False) + '\n'); out.flush()


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == '--render':
        render_main()
    else:
        main()
