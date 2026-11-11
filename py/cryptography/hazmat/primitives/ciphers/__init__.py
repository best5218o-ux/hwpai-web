"""AES-128 ECB 복호 전용 대체(hwpai 웹). 실제 계산은 worker.js 의 hwpaiAesEcbDecrypt."""
from types import SimpleNamespace


class _AES:
    def __init__(self, key):
        self.key = bytes(key)


class _ECB:
    pass


algorithms = SimpleNamespace(AES=_AES)
modes = SimpleNamespace(ECB=_ECB)


class _Dec:
    def __init__(self, key):
        self.key = key
        self.buf = b""

    def update(self, data):
        import js
        from pyodide.ffi import to_js
        out = js.hwpaiAesEcbDecrypt(to_js(bytes(self.key)), to_js(bytes(data)))
        return bytes(out.to_py())

    def finalize(self):
        return b""


class Cipher:
    def __init__(self, algorithm, mode):
        if not isinstance(algorithm, _AES) or not isinstance(mode, _ECB):
            raise NotImplementedError("웹 버전은 AES-ECB 복호화만 지원")
        self.algorithm = algorithm

    def decryptor(self):
        return _Dec(self.algorithm.key)
