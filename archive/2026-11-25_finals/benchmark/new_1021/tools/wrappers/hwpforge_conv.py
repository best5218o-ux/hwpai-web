"""hwpforge(PyPI, Rust 바인딩) convert_hwp5: HWP5 -> HWPX. 사용: python hwpforge_conv.py <in.hwp> <out.hwpx>"""
import sys, hwpforge
r = hwpforge.convert_hwp5(open(sys.argv[1], 'rb').read())
res = r[0] if isinstance(r, tuple) else r
data = res.data if hasattr(res, 'data') else (res if isinstance(res, (bytes, bytearray)) else None)
if data is None and hasattr(res, 'document'): data = res.document.to_bytes() if hasattr(res.document, 'to_bytes') else None
open(sys.argv[2], 'wb').write(data)
