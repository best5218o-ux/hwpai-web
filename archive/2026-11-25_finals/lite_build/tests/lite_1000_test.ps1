# 경량판 1,000건 Windows 실증 2차 — 같은 프로그램 코드로 실행기만 바꿔 비교
#  기존: Node.js + 원본 엔진(v9 동봉)   경량: 파이썬 wasmtime + 최적화 엔진
$ErrorActionPreference = 'Continue'
$env:PYTHONUTF8 = '1'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log  = Join-Path $here 'lite_result2.txt'
"== 2nd run $(Get-Date -Format s) ==" | Out-File $log -Encoding utf8
function L($m) { $m | Out-File $log -Append -Encoding utf8; Write-Host $m }
$L = Join-Path $here 'lite\hwpai-portable-win64'
$V = (Resolve-Path (Join-Path $here '..\hwpai_settle_win_시험\v9')).Path
$in = Join-Path $here 'in1000'
function Run($tag, $engine, $out) {
  if (Test-Path $out) { Remove-Item -Recurse -Force $out }
  $sw = [Diagnostics.Stopwatch]::StartNew()
  Push-Location "$L\app"
  & "$L\python\python.exe" -B -m hwpai convert $in --out $out --jobs 2 --engine $engine 2>&1 | Select-Object -Last 2 | ForEach-Object { L "  $_" }
  Pop-Location
  $sw.Stop(); L ("[$tag] {0:N1} s" -f $sw.Elapsed.TotalSeconds)
}
$env:HWPAI_NODE = "$V\node\node.exe"; $env:HWPAI_RHWP_CORE = "$V\app\vendor\rhwp-core"
Run 'node+original' 'rhwp-wasm' (Join-Path $here 'outN2')
Remove-Item Env:HWPAI_NODE; Remove-Item Env:HWPAI_RHWP_CORE
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\hwpai\engine-cache" -ErrorAction SilentlyContinue
Run 'lite first run' 'rhwp-py' (Join-Path $here 'outL3')
& "$L\python\python.exe" -B (Join-Path $here 'compare.py') (Join-Path $here 'outN2') (Join-Path $here 'outL3') 2>&1 | ForEach-Object { L $_ }
L "== end =="
