/* HWP AI 어댑터 웹판 — 「앱」(PWA) 연결: 오프라인 캐시 등록, 설치 단추, 휴대폰 화면 맞춤, 파일 열기 연결.
 * 문서 파일은 어디에도 보내지 않는다. 서비스 워커는 같은 출처의 정적 파일만 저장한다. */
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const mobile = window.matchMedia('(pointer:coarse)').matches || /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  window.HWPAI_PWA = { mobile, sw: 'none', installable: false };

  // 1) 오프라인 캐시 — http(s) 보안 컨텍스트에서만(file:// 로 열면 해당 없음)
  if ('serviceWorker' in navigator && window.isSecureContext && location.protocol !== 'file:') {
    navigator.serviceWorker.register('sw.js').then((r) => {
      window.HWPAI_PWA.sw = 'registered';
      navigator.serviceWorker.ready.then(() => { window.HWPAI_PWA.sw = 'ready'; });
    }).catch((e) => { window.HWPAI_PWA.sw = 'error: ' + e.message; });
  }

  // 2) 설치 단추 — 브라우저가 설치를 허락할 때만 보인다
  const top = document.querySelector('header.top');
  const btn = document.createElement('button');
  btn.id = 'btnInstall'; btn.type = 'button'; btn.className = 'btn'; btn.hidden = true;
  btn.textContent = '앱으로 설치';
  if (top) top.appendChild(btn);
  let deferred = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault(); deferred = e; btn.hidden = false; window.HWPAI_PWA.installable = true;
  });
  btn.addEventListener('click', async () => {
    if (!deferred) return;
    deferred.prompt(); await deferred.userChoice.catch(() => null); deferred = null; btn.hidden = true;
  });
  window.addEventListener('appinstalled', () => { btn.hidden = true; });

  // 3) 휴대폰 화면 — 끌어놓기 대신 「파일 선택」, 폴더 선택은 숨김, 파일 고르기 창에서 HWP 가 흐리게 보이지 않게
  if (mobile) {
    document.documentElement.classList.add('is-mobile');
    const t = $('.drop-title'); if (t) t.textContent = '「파일 선택」을 눌러 HWP 파일을 고르세요';
    const d = $('#pickDir'); if (d) d.hidden = true;
    const fi = $('#fileInput'); if (fi) fi.removeAttribute('accept'); // 휴대폰은 .hwp 형식을 몰라 고를 수 없게 막는 경우가 있다 — 확장자는 앱이 다시 거른다
  }

  // 4) 설치된 앱으로 HWP 파일 열기(파일 연결, 데스크톱 크롬·엣지)
  if ('launchQueue' in window) {
    window.launchQueue.setConsumer(async (params) => {
      if (!params.files || !params.files.length) return;
      const files = [];
      for (const h of params.files) { try { files.push(await h.getFile()); } catch (e) { /* */ } }
      const fi = $('#fileInput'); if (!fi || !files.length) return;
      const dt = new DataTransfer(); files.forEach((f) => dt.items.add(f));
      fi.files = dt.files; fi.dispatchEvent(new Event('change'));
    });
  }
})();
