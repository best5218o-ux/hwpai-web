HWP AI 어댑터 - HWP를 AI가 바로 읽고 HWPX로 바꾸는 어댑터 (명령 hwpai) - 휴대용 폴더

설치·관리자 권한·인터넷이 필요 없습니다. 폴더째 아무 곳에 풀어 쓰세요.

1) check.bat 을 두 번 누르면 설치 점검과 시험 변환을 합니다(마지막 줄이 '사용할 수 있습니다' 이면 준비 끝).
2) 가장 쉬운 방법: HWP 가 든 폴더(하위 폴더 포함)나 파일 여러 개를 hwpai.bat 아이콘 위로 끌어다 놓으세요.
   '<폴더>_hwpx변환' 에 변환본·검증서·이관대장.xlsx 가 생기고, 끝나면 결과 폴더와 요약이 열립니다. 원본은 바뀌지 않습니다.
   처음에는 sample_data 폴더를 끌어다 놓아 보세요(합성 문서 4건 모두 PASS, 번호가 든 시험 문서 1건은 이관대장에 '확인 필요'로 남고 사람이 확인하기 전에는 AI 로 보내지 않습니다).
3) hwpai.bat 을 두 번 누르면 브라우저에 화면이 열립니다(이 컴퓨터 안에서만, 127.0.0.1). 화면에 폴더를 끌어다 놓고 '변환 시작'.

명령창(폴더 주소창에 cmd 입력 후 Enter):
  hwpai.bat convert <폴더> / hwpai.bat drop <폴더|파일> ... / hwpai.bat read <파일.hwp> / hwpai.bat audit <원본.hwp> <변환.hwpx> / hwpai.bat doctor
AI 앱(Claude 데스크톱 등) 연결: hwpai_ai_connect.bat
민감정보 확인 요청: 변환·검증은 이 컴퓨터 안에서만 하므로 막지 않습니다. 등급이 없는 문서에서 휴대전화·주민번호·계좌번호·이메일·성명 표기·문서 속성(작성자)이 나오면 '확인 필요'로 적고, 사람이 확인(hwpai.bat sens review 폴더)하기 전에는 AI 에 보내지 않습니다.
자세한 내용: docs\guide.md   라이선스: LICENSE, NOTICE, THIRD_PARTY_LICENSES.md
