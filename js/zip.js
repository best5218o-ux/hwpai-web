/* hwpai 웹 — 최소 ZIP 기록기(무압축 저장, UTF-8 이름). 외부 라이브러리 없음.
 * HWPX 는 이미 압축된 ZIP 이라 다시 압축하지 않는다. 항목은 {name, blob, crc, size} — 데이터는 Blob 그대로 이어 붙여 메모리를 아낀다. */
(function () {
  'use strict';
  const T = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; T[n] = c >>> 0; }
  function crc32(u8, c0) {
    let c = (c0 === undefined ? 0 : c0) ^ 0xFFFFFFFF;
    for (let i = 0; i < u8.length; i++) c = T[(c ^ u8[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function dos(d) {
    const t = ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xFFFF;
    const dt = (((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xFFFF;
    return [t, dt];
  }
  const enc = new TextEncoder();
  /** entries: [{name, bytes?:Uint8Array, blob?:Blob, crc?, size?}] → Blob */
  function makeZip(entries, when) {
    const [tm, dt] = dos(when || new Date());
    const parts = [], central = [];
    let off = 0, n = 0;
    for (const e of entries) {
      const name = enc.encode(String(e.name).replace(/\\/g, '/').replace(/^\/+/, ''));
      let size, crc, body;
      if (e.bytes) { body = e.bytes; size = body.length; crc = e.crc != null ? e.crc : crc32(body); }
      else { body = e.blob; size = e.size; crc = e.crc; }
      if (size >= 0xFFFFFFFF || off >= 0xFFFFFFFF || n >= 0xFFFF) throw new Error('ZIP 한도 초과(4GB·65535개) — 나누어 내려받으세요');
      const lh = new DataView(new ArrayBuffer(30 + name.length));
      lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true); lh.setUint16(8, 0, true);
      lh.setUint16(10, tm, true); lh.setUint16(12, dt, true); lh.setUint32(14, crc, true); lh.setUint32(18, size, true); lh.setUint32(22, size, true);
      lh.setUint16(26, name.length, true); lh.setUint16(28, 0, true);
      new Uint8Array(lh.buffer).set(name, 30);
      parts.push(lh.buffer, body);
      const ch = new DataView(new ArrayBuffer(46 + name.length));
      ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint16(8, 0x0800, true); ch.setUint16(10, 0, true);
      ch.setUint16(12, tm, true); ch.setUint16(14, dt, true); ch.setUint32(16, crc, true); ch.setUint32(20, size, true); ch.setUint32(24, size, true);
      ch.setUint16(28, name.length, true); ch.setUint32(42, off, true);
      new Uint8Array(ch.buffer).set(name, 46);
      central.push(ch.buffer);
      off += lh.byteLength + size; n++;
    }
    let cs = 0; for (const c of central) cs += c.byteLength;
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, n, true); end.setUint16(10, n, true); end.setUint32(12, cs, true); end.setUint32(16, off, true);
    return new Blob([...parts, ...central, end.buffer], { type: 'application/zip' });
  }
  window.HwpaiZip = { makeZip, crc32 };
})();
