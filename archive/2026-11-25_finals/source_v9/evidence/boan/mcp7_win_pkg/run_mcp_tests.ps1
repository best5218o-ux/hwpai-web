# hwpai MCP Windows 자동 시험 (합성 문서만 사용). 사용자는 Gemini·Codex 로그인만 한다.
# 모든 설치·설정은 이 폴더 안에서만 한다(전역 설치·관리자 권한·사용자 기존 설정 변경 없음).
param([switch]$Force)
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$T = $PSScriptRoot
$R = Join-Path $T '결과'
# 이전 결과가 있으면 날짜별로 보관한다. 직접 구동 시험이 모두 통과했으면 이번에는 건너뛴다(-Force 를 주면 다시 한다).
$prevSummary = $null
if (Test-Path "$R\10_직접구동_요약.json") {
  try { $pj = Get-Content "$R\10_직접구동_요약.json" -Raw -Encoding UTF8 | ConvertFrom-Json; if (@($pj | Where-Object { $_[1] -ne '통과' }).Count -eq 0 -and @($pj).Count -gt 0) { $prevSummary = $pj } } catch {}
}
if (Test-Path $R) {
  $arch = Join-Path $T ('결과_보관\' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
  New-Item -ItemType Directory -Force -Path $arch | Out-Null
  Get-ChildItem $R | Move-Item -Destination $arch -Force
  if ($prevSummary -and -not $Force) { foreach ($f in '10_직접구동_결과.txt', '10_직접구동_요약.json') { if (Test-Path "$arch\$f") { Copy-Item "$arch\$f" $R -Force } } }
}
New-Item -ItemType Directory -Force -Path $R | Out-Null
$skipDirect = ($prevSummary -and -not $Force)
$utf8 = New-Object System.Text.UTF8Encoding($false)
function W($f, $s) { [IO.File]::WriteAllText($f, $s, $utf8) }
function Log($s) { $l = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $s; Write-Host $l; [IO.File]::AppendAllText((Join-Path $R '00_진행로그.txt'), $l + "`r`n", $utf8) }
$rows = New-Object System.Collections.ArrayList
function Row($item, $res, $note) { [void]$rows.Add([pscustomobject]@{ 항목 = $item; 결과 = $res; 비고 = $note }) }
Start-Transcript -Path (Join-Path $R '01_transcript.txt') -Force | Out-Null
Log "시작. 시험 폴더: $T"
Log "PC: $([Environment]::OSVersion.VersionString), 기본 코드페이지(OEM) $([Console]::OutputEncoding.CodePage)"

# ---------- 0. 휴대용 폴더(파이썬·노드) 찾기, v9 설치 ----------
$cands = @("$T\..\hwpai-portable-win64\hwpai-portable-win64", "$T\..\hwpai-portable-win64")
$PORT = $null
foreach ($c in $cands) { if (Test-Path "$c\python\python.exe") { $PORT = (Resolve-Path $c).Path; break } }
$V = Join-Path $T 'v9'
try {
  if (-not $PORT) { throw '휴대용 폴더(python\python.exe)를 찾지 못했다' }
  Log "휴대용 폴더: $PORT"
  if (-not (Test-Path "$V\app\hwpai\mcp.py")) {
    New-Item -ItemType Directory -Force -Path $V | Out-Null
    Expand-Archive -Path "$T\hwpai_v9_시험본.zip" -DestinationPath $V -Force
  }
  if (-not (Test-Path "$V\python\python.exe")) { robocopy "$PORT\python" "$V\python" /E /NFL /NDL /NJH /NJS /NP | Out-Null }
  if (-not (Test-Path "$V\node\node.exe")) { robocopy "$PORT\node" "$V\node" /E /NFL /NDL /NJH /NJS /NP | Out-Null }
  $n = (Get-Content "$V\app\hwpai\mcp.py" -Encoding UTF8).Count
  Log "v9 시험 사본 준비: mcp.py $n 줄 (구판 휴대용은 307줄)"
  Row 'v9 사본 준비(휴대용 python·node 사용)' '통과' "mcp.py $n 줄"
} catch { Log "준비 실패: $_"; Row 'v9 사본 준비' '실패' "$_" }

$sample = "$T\sample_data\sample_plan.hwp"
$koDir = "$T\한글 공백 폴더\하위 폴더"
New-Item -ItemType Directory -Force -Path $koDir | Out-Null
Copy-Item $sample "$koDir\공고문 샘플.hwp" -Force

# ---------- 1. MCP 서버 직접 구동 시험 (hwpai.bat / python.exe, 시작 시간 3회) ----------
Log '=== [1] 서버 직접 구동 시험 (hwpai.bat·python.exe) ==='
if ($skipDirect) {
  Log '이전 직접 구동 시험이 모두 통과해 건너뜀(-Force 로 다시 실행). 이전 결과를 가져와 표에 넣는다.'
  foreach ($j in $prevSummary) { Row $j[0] ($j[1] + '(이전 실행)') $j[2] }
} else {
try {
  Remove-Item Env:PYTHONUTF8, Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
  & "$V\python\python.exe" "$T\mcp_direct_test.py" $V $R $sample "$koDir\공고문 샘플.hwp" 2>&1 | ForEach-Object { Log "  $_" }
  if (Test-Path "$R\10_직접구동_요약.json") {
    $js = Get-Content "$R\10_직접구동_요약.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($j in $js) { Row $j[0] $j[1] $j[2] }
  } else { Row '직접 구동 시험' '실패' '요약 파일이 만들어지지 않음' }
} catch { Log "직접 구동 시험 오류: $_"; Row '직접 구동 시험' '실패' "$_" }
}

# ---------- 2. Node(npm) 확보 + Gemini CLI·Codex 를 이 폴더 안에 설치 ----------
Log '=== [2] Gemini CLI·Codex 로컬 설치 (이 폴더 안, 전역 설치 아님) ==='
$NODEV = 'v22.11.0'
$NT = Join-Path $T 'tools'
$NDIR = Join-Path $NT "node-$NODEV-win-x64"
$GEM = $null; $COD = $null
$NODEBIN = $NDIR
$diagTop = New-Object System.Collections.ArrayList
$DG = "$R\02_diag.txt"
$G1 = '@google/gemini-cli@0.70.0'; $G2 = '@openai/codex@0.171.0'

# cmd 래퍼: 한글 경로를 안전하게 쓰려고 UTF-8 .cmd 파일을 만들어 실행(첫 줄에서 chcp 65001). 출력·종료코드는 cmd 리디렉션으로 파일에 남긴다.
function Run-Wrapper($name, $lines) {
  $w = Join-Path $R ('_w_' + $name + '.cmd')
  $body = "@echo off`r`nchcp 65001 >nul`r`n" + ($lines -join "`r`n") + "`r`n"
  [IO.File]::WriteAllText($w, $body, $utf8)
  & $w | Out-Null
  return $LASTEXITCODE
}
function Diag-Node($label, $ndir, $workdir, $outfile) {
  $node = "$ndir\node.exe"; $npmcli = "$ndir\node_modules\npm\bin\npm-cli.js"
  $npmlib = ("$ndir\node_modules\npm\lib\cli.js") -replace '\\', '/'
  $L = @("set `"PATH=$ndir;%PATH%`"", "cd /d `"$workdir`"", "echo ##### $label  cwd=%CD% >> `"$outfile`"", "chcp >> `"$outfile`" 2>&1")
  $cases = @(
    @('node --version', "`"$node`" --version"),
    @('node -e (version, cwd)', "`"$node`" -e `"console.log(process.version, process.cwd())`""),
    @('node -p (홈 폴더, 플랫폼)', "`"$node`" -p `"require('os').homedir() + ' ' + process.platform`""),
    @('npm-cli.js 파일 확인', "dir `"$npmcli`""),
    @('npm-cli.js --version', "`"$node`" `"$npmcli`" --version"),
    @('npm-cli.js --version (--trace-uncaught)', "`"$node`" --trace-uncaught `"$npmcli`" --version"),
    @('npm lib/cli.js 직접 호출 --version', "`"$node`" -e `"process.argv=[process.argv[0],'npm','--version'];require('$npmlib')(process)`""),
    @('npm-cli.js config get registry', "`"$node`" `"$npmcli`" config get registry"),
    @('npm-cli.js config get cache', "`"$node`" `"$npmcli`" config get cache"))
  foreach ($c in $cases) {
    $L += "echo ===== $($c[0]) ===== >> `"$outfile`""
    $L += "$($c[1]) >> `"$outfile`" 2>&1"
    $L += "echo ERRORLEVEL=%ERRORLEVEL% >> `"$outfile`""
  }
  $L += 'exit /b 0'
  [void](Run-Wrapper ('diag_' + ($label -replace '[^A-Za-z0-9]', '_')) $L)
}
# npm install: cmd /c 로 실행하고 종료코드는 $LASTEXITCODE 로 읽는다. 출력(stdout+stderr)은 한 로그에 모은다.
function Do-Install($label, $ndir, $npmp, $cache, $logs, $log, $homeEnv) {
  $node = "$ndir\node.exe"; $npmcli = "$ndir\node_modules\npm\bin\npm-cli.js"
  New-Item -ItemType Directory -Force -Path $npmp, $cache, $logs | Out-Null
  if (-not (Test-Path "$npmp\package.json")) { W "$npmp\package.json" '{"name":"mcp-test-tools","version":"1.0.0","private":true}' }
  $L = @("set `"PATH=$ndir;%PATH%`"")
  if ($homeEnv) { $L += "set `"USERPROFILE=$homeEnv`"", "set `"HOME=$homeEnv`"", "set `"APPDATA=$homeEnv\AppData\Roaming`"", "set `"LOCALAPPDATA=$homeEnv\AppData\Local`"", "set `"TEMP=$homeEnv\tmp`"", "set `"TMP=$homeEnv\tmp`"" }
  $L += "cd /d `"$npmp`""
  $L += "echo [$label] node=$node >> `"$log`""
  $L += "`"$node`" `"$npmcli`" install --prefix `"$npmp`" --no-audit --no-fund --loglevel verbose --cache `"$cache`" --logs-dir `"$logs`" $G1 $G2 >> `"$log`" 2>&1"
  $L += 'set RC=%ERRORLEVEL%'
  $L += "echo EXITCODE=%RC% >> `"$log`""
  $L += 'exit /b %RC%'
  $rc = Run-Wrapper ('install_' + $label) $L
  return $rc
}
try {
  New-Item -ItemType Directory -Force -Path $NT | Out-Null
  if (-not (Test-Path "$NDIR\npm.cmd")) {
    $zip = "$NT\node.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Log "Node.js $NODEV(npm 포함) 내려받는 중: nodejs.org"
    Invoke-WebRequest -Uri "https://nodejs.org/dist/$NODEV/node-$NODEV-win-x64.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $NT -Force
  }
  $npmCli = "$NDIR\node_modules\npm\bin\npm-cli.js"
  Log "npm-cli.js 존재: $(Test-Path $npmCli) ; 경로에 한글 있음: $([bool]($NDIR -match '[^\x00-\x7F]'))"
  try { $wr = Invoke-WebRequest -Uri 'https://registry.npmjs.org/@openai%2fcodex' -UseBasicParsing -Method Head -TimeoutSec 30; $net = "registry 접속 HTTP $($wr.StatusCode)" } catch { $net = "registry 접속 실패: $($_.Exception.Message)" }
  Log $net
  # --- 진단: 한글 경로 작업폴더 / ASCII 작업폴더 두 곳에서 node·npm 이 실제로 도는지
  [IO.File]::WriteAllText($DG, "npm 진단 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`r`n$net`r`n", $utf8)
  $asciiWork = $env:PUBLIC
  Diag-Node '한글경로' $NDIR $T $DG
  Diag-Node 'ASCII작업폴더' $NDIR $asciiWork $DG
  $dtxt = [IO.File]::ReadAllText($DG, $utf8)
  Log ("진단(02_diag.txt) 요약: " + (($dtxt -split "`r?`n" | Where-Object { $_ -match '^(v22|10\.|11\.|ERRORLEVEL)' } | Select-Object -First 12) -join ' | '))
  [void]$diagTop.Add("진단 02_diag.txt: npm-cli.js --version 출력 " + $(if ($dtxt -match '(?s)npm-cli\.js --version =====\r?\n(\d+\.\d+\.\d+)') { $Matches[1] } else { '(비어 있음)' }))

  # --- 1차 설치: 이 폴더(한글 경로)
  Log "npm install 1차(시험 폴더, 한글 경로) $G1 $G2 — 몇 분 걸릴 수 있음. 출력: 결과\02_npm_install.log"
  $NPMP = Join-Path $T 'tools\npm_local'
  $logs1 = Join-Path $R 'npm_logs'
  $nrc = Do-Install '한글경로' $NDIR $NPMP (Join-Path $T 'tools\npm_cache') $logs1 "$R\02_npm_install.log" $null
  Log "npm install 1차 종료코드(LASTEXITCODE): $nrc"
  if (Test-Path "$NPMP\node_modules\.bin\gemini.cmd") { $GEM = "$NPMP\node_modules\.bin\gemini.cmd" }
  if (Test-Path "$NPMP\node_modules\.bin\codex.cmd") { $COD = "$NPMP\node_modules\.bin\codex.cmd" }
  [void]$diagTop.Add("npm 1차(한글 경로) 종료코드 $nrc ; gemini.cmd=$([bool]$GEM) codex.cmd=$([bool]$COD)")

  # --- 2차 설치(1차 실패 시): 사용자 쓰기 가능한 짧은 ASCII 경로 C:\Users\Public\hwpai_npm (관리자 권한 불필요)
  if (-not ($GEM -and $COD)) {
    $AB = Join-Path $env:PUBLIC 'hwpai_npm'
    Log "1차 실패 → ASCII 경로 $AB 에서 2차 시도"
    New-Item -ItemType Directory -Force -Path "$AB\home\AppData\Roaming", "$AB\home\AppData\Local", "$AB\home\tmp" | Out-Null
    if (-not (Test-Path "$AB\node\node.exe")) { robocopy $NDIR "$AB\node" /E /NFL /NDL /NJH /NJS /NP | Out-Null }
    Diag-Node 'ASCII설치경로' "$AB\node" $AB $DG
    $nrc2 = Do-Install 'ASCII경로' "$AB\node" "$AB\npm_local" "$AB\cache" "$AB\logs" "$AB\npm_install.log" "$AB\home"
    Log "npm install 2차 종료코드(LASTEXITCODE): $nrc2"
    if (Test-Path "$AB\npm_install.log") { Copy-Item "$AB\npm_install.log" "$R\02_npm_install_ASCII경로.log" -Force }
    if (Test-Path "$AB\npm_local\node_modules\.bin\gemini.cmd") { $GEM = "$AB\npm_local\node_modules\.bin\gemini.cmd"; $NODEBIN = "$AB\node" }
    if (Test-Path "$AB\npm_local\node_modules\.bin\codex.cmd") { $COD = "$AB\npm_local\node_modules\.bin\codex.cmd"; $NODEBIN = "$AB\node" }
    [void]$diagTop.Add("npm 2차(ASCII 경로 $AB) 종료코드 $nrc2 ; gemini.cmd=$([bool]$GEM) codex.cmd=$([bool]$COD)")
  }
  # --- 실패 단서(로그에서 찾은 것만)
  $allt = ''
  foreach ($f in "$R\02_npm_install.log", "$R\02_npm_install_ASCII경로.log", $DG) { if (Test-Path $f) { $allt += [IO.File]::ReadAllText($f, $utf8) } }
  $diag = @(); foreach ($k in 'ENOTFOUND', 'ETIMEDOUT', 'ECONNRESET', 'ECONNREFUSED', 'E403', ' 403 ', 'E407', 'E404', 'EACCES', 'EPERM', 'SELF_SIGNED_CERT', 'UNABLE_TO_VERIFY', 'EBUSY', 'ENOSPC', 'Cannot find module', 'SyntaxError') { if ($allt -match [regex]::Escape($k)) { $diag += $k } }
  if (-not ($GEM -and $COD)) {
    Log "npm 실패 단서(로그에서 찾은 키워드): $($diag -join ',')"
    Get-ChildItem $logs1 -Filter *.log -ErrorAction SilentlyContinue | ForEach-Object { Log "  npm 디버그 로그: $($_.FullName)" }
    Log ('  npm 로그 마지막 줄들: ' + ((Get-Content "$R\02_npm_install.log" -Tail 8 -ErrorAction SilentlyContinue) -join ' | '))
    Row 'npm install 원인 단서' '실패' ("키워드: " + ($diag -join ',') + "; $net; 02_diag.txt·02_npm_install.log 참고")
  }
  Row 'Gemini CLI 로컬 설치' ($(if ($GEM) { '통과' } else { '실패' })) "$GEM"
  Row 'Codex 로컬 설치' ($(if ($COD) { '통과' } else { '실패' })) "$COD"
} catch { Log "설치 단계 오류: $_"; Row 'Gemini·Codex 로컬 설치' '실패' "$_"; [void]$diagTop.Add("설치 단계 예외: $_") }

$env:PATH = "$NODEBIN;" + $env:PATH   # gemini.cmd·codex.cmd 가 node 를 찾도록

# ---------- 3. 격리된 HOME 과 hwpai MCP 등록 ----------
$H = Join-Path $T 'home'
New-Item -ItemType Directory -Force -Path "$H\.gemini", "$H\.codex", "$H\AppData\Roaming", "$H\AppData\Local" | Out-Null
$env:USERPROFILE = $H; $env:HOME = $H; $env:GEMINI_CLI_HOME = $H; $env:CODEX_HOME = "$H\.codex"
$env:APPDATA = "$H\AppData\Roaming"; $env:LOCALAPPDATA = "$H\AppData\Local"
$batPath = "$V\hwpai.bat"
$gl = "$R\gradelog_AI"
$bj = ($batPath -replace '\\', '\\')
$rj = ($T -replace '\\', '\\'); $gj = ($gl -replace '\\', '\\')
$gset = @"
{
  "mcpServers": {
    "hwpai": {
      "command": "$bj",
      "args": ["mcp"],
      "timeout": 600000,
      "trust": true,
      "env": { "HWPAI_MCP_ROOTS": "$rj", "HWPAI_GRADE_LOG": "$gj" }
    }
  },
  "security": { "auth": { "selectedType": "oauth-personal" }, "folderTrust": { "enabled": false } },
  "general": { "enableAutoUpdate": false }
}
"@
W "$H\.gemini\settings.json" $gset
$ctoml = @"
[mcp_servers.hwpai]
command = '$batPath'
args = ['mcp']
startup_timeout_sec = 60
tool_timeout_sec = 600

[mcp_servers.hwpai.env]
HWPAI_MCP_ROOTS = '$T'
HWPAI_GRADE_LOG = '$gl'
"@
W "$H\.codex\config.toml" $ctoml
Log "격리 HOME: $H (사용자 기존 설정은 건드리지 않음). hwpai 등록: Gemini settings.json, Codex config.toml"

$promptFile = "$R\prompt_AI.txt"
$outG = "$R\변환_gemini"; $outC = "$R\변환_codex"
function Prompt($outdir) {
  return "합성 시험 문서 한 개가 $sample 에 있다. hwpai MCP 도구만 사용해서 다음을 해라. " +
         "1) 이 HWP 의 표를 읽어 한국어로 짧게 요약한다. " +
         "2) 이 HWP 를 HWPX 로 변환해 결과 폴더를 $outdir 로 한다. " +
         "3) 마지막 줄에 '사용한 도구:' 로 실제로 호출한 hwpai 도구 이름을 적는다."
}
function Wait-File($path, $minutes) {
  $end = (Get-Date).AddMinutes($minutes)
  while ((Get-Date) -lt $end) { if (Test-Path $path) { return $true }; Start-Sleep -Seconds 3 }
  return $false
}
function Run-Tool($exe, $argstr, $stdinFile, $outFile, $errFile, $minutes) {
  # cmd 래퍼로 실행(입출력 리디렉션은 cmd 가 한다). 종료코드는 래퍼가 파일(.rc)에 적고, Start-Process 의 ExitCode 는 Handle 을 먼저 잡은 뒤 읽는다.
  $rcFile = $outFile + '.rc'
  Remove-Item $rcFile -ErrorAction SilentlyContinue
  $L = @("set `"PATH=$NODEBIN;%PATH%`"", "cd /d `"$T`"", "call `"$exe`" $argstr < `"$stdinFile`" > `"$outFile`" 2> `"$errFile`"", 'set RC=%ERRORLEVEL%', "echo RC=%RC%> `"$rcFile`"", 'exit /b %RC%')
  $w = Join-Path $R ('_w_run_' + [IO.Path]::GetFileNameWithoutExtension($outFile) + '.cmd')
  [IO.File]::WriteAllText($w, ("@echo off`r`nchcp 65001 >nul`r`n" + ($L -join "`r`n") + "`r`n"), $utf8)
  $p = Start-Process -FilePath $w -WorkingDirectory $T -PassThru -NoNewWindow
  $null = $p.Handle
  if (-not $p.WaitForExit($minutes * 60000)) { try { & taskkill /PID $p.Id /T /F | Out-Null } catch {}; return 'timeout' }
  $code = $null
  try { $code = $p.ExitCode } catch {}
  if ($null -eq $code -and (Test-Path $rcFile)) { $code = ([IO.File]::ReadAllText($rcFile).Trim() -replace '^RC=', '') }
  return $code
}
function Tool-Evidence($files) {
  $txt = ''
  foreach ($f in $files) { if (Test-Path $f) { $txt += [IO.File]::ReadAllText($f, $utf8) } }
  $hit = @(); foreach ($n in 'read_hwp', 'get_tables', 'search_chunks', 'convert_to_hwpx', 'audit') { if ($txt -match $n) { $hit += $n } }
  return ,$hit
}

# ---------- 4. Gemini ----------
Log '=== [3] Gemini CLI: 로그인 후 모델이 hwpai 도구를 부르는지 ==='
if ($GEM) {
  try {
    $cred = "$H\.gemini\oauth_creds.json"
    if (-not (Test-Path $cred)) {
      Log '*** Gemini 로그인 창이 열립니다. 새 창에서 「Login with Google」을 고르고 브라우저에서 로그인하세요. 로그인이 끝나면 이 시험이 자동으로 이어집니다(최대 15분 대기). ***'
      $gp = Start-Process -FilePath $GEM -WorkingDirectory $T -PassThru
      $ok = Wait-File $cred 15
      Start-Sleep -Seconds 3
      try { & taskkill /PID $gp.Id /T /F 2>$null | Out-Null } catch {}
      if (-not $ok) { throw 'Gemini 로그인 시간 초과(15분)' }
    }
    Log 'Gemini 로그인 확인. 비대화형 실행.'
    W $promptFile (Prompt $outG)
    $rc = Run-Tool $GEM '-p "Follow the instructions given on stdin." --output-format stream-json' $promptFile "$R\20_gemini_출력.txt" "$R\20_gemini_오류.txt" 15
    if ($rc -ne 0) {
      Log "stream-json 실행 종료코드 $rc — 일반 출력으로 다시 실행"
      $rc = Run-Tool $GEM '-p "Follow the instructions given on stdin."' $promptFile "$R\20_gemini_출력_일반.txt" "$R\20_gemini_오류_일반.txt" 15
    }
    $hit = Tool-Evidence @("$R\20_gemini_출력.txt", "$R\20_gemini_출력_일반.txt")
    $hw = @(Get-ChildItem $outG -Filter *.hwpx -Recurse -ErrorAction SilentlyContinue)
    Log "Gemini 종료코드 $rc, 출력에서 확인된 hwpai 도구: $($hit -join ',') ; 변환 결과 hwpx $($hw.Count)개"
    Row 'Gemini CLI 모델 경유 호출' ($(if ($hit.Count -gt 0 -and $hw.Count -gt 0) { '통과' } elseif ($hit.Count -gt 0) { '부분(도구 호출됨, 변환 결과 파일 없음)' } else { '실패' })) "종료코드 $rc; 도구 $($hit -join ',')"
  } catch { Log "Gemini 단계 오류: $_"; Row 'Gemini CLI 모델 경유 호출' '미실시' "$_" }
} else { Row 'Gemini CLI 모델 경유 호출' '미실시' '설치 실패' }

# ---------- 5. Codex ----------
Log '=== [4] Codex: 로그인 후 모델이 hwpai 도구를 부르는지 ==='
if ($COD) {
  try {
    $auth = "$H\.codex\auth.json"
    if (-not (Test-Path $auth)) {
      Log '*** Codex 로그인 브라우저 창이 열립니다. ChatGPT 계정으로 로그인하세요. 완료되면 자동으로 이어집니다(최대 15분 대기). ***'
      $cp = Start-Process -FilePath $COD -ArgumentList 'login' -WorkingDirectory $T -PassThru
      $ok = Wait-File $auth 15
      Start-Sleep -Seconds 3
      try { & taskkill /PID $cp.Id /T /F 2>$null | Out-Null } catch {}
      if (-not $ok) { throw 'Codex 로그인 시간 초과(15분)' }
    }
    $st = & $COD login status 2>&1; Log "codex login status: $st"
    $ml = & $COD mcp list 2>&1; Log "codex mcp list: $($ml -join ' | ')"
    W $promptFile (Prompt $outC)
    $rc = Run-Tool $COD 'exec --skip-git-repo-check --json -s workspace-write -c approval_policy="never" -' $promptFile "$R\30_codex_출력.txt" "$R\30_codex_오류.txt" 15
    $hit = Tool-Evidence @("$R\30_codex_출력.txt")
    $hw = @(Get-ChildItem $outC -Filter *.hwpx -Recurse -ErrorAction SilentlyContinue)
    Log "Codex 종료코드 $rc, 출력에서 확인된 hwpai 도구: $($hit -join ',') ; 변환 결과 hwpx $($hw.Count)개"
    Row 'Codex 모델 경유 호출' ($(if ($hit.Count -gt 0 -and $hw.Count -gt 0) { '통과' } elseif ($hit.Count -gt 0) { '부분(도구 호출됨, 변환 결과 파일 없음)' } else { '실패' })) "종료코드 $rc; 도구 $($hit -join ',')"
  } catch { Log "Codex 단계 오류: $_"; Row 'Codex 모델 경유 호출' '미실시' "$_" }
} else { Row 'Codex 모델 경유 호출' '미실시' '설치 실패' }

# ---------- 6. 결과표 ----------
$tbl = ($rows | Format-Table -AutoSize -Wrap | Out-String -Width 220)
$top = "【npm 설치 진단 요약】`r`n" + (($diagTop | ForEach-Object { "  - $_" }) -join "`r`n") + "`r`n`r`n"
W "$R\99_결과표.txt" ("hwpai MCP Windows 시험 결과표 " + (Get-Date -Format 'yyyy-MM-dd HH:mm') + "`r`n`r`n" + $top + $tbl)
Log "`r`n$tbl"
Stop-Transcript | Out-Null
W "$R\FINISHED" ("끝: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Write-Host "`n모두 끝났습니다. 이 창을 닫고 Claude 에게 '끝났다'고 알려 주세요."
