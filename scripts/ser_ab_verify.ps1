# SenseVoice 内嵌 SER 契约验证（对齐本地 /recognize + /health）
# 用法: .\scripts\ser_ab_verify.ps1 [-BaseUrl http://127.0.0.1:8765]
param([string]$BaseUrl = 'http://127.0.0.1:8765')
$ErrorActionPreference = 'Stop'

function New-Wav16k([string]$path, [int]$seconds, [bool]$withTone) {
  $frames = 16000 * $seconds
  $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Create)
  $bw = New-Object System.IO.BinaryWriter($fs)
  try {
    $bw.Write([byte[]][char[]]'RIFF'); $bw.Write([int](36 + $frames * 2))
    $bw.Write([byte[]][char[]]'WAVEfmt ')
    $bw.Write([int]16); $bw.Write([System.Int16]1); $bw.Write([System.Int16]1)
    $bw.Write([int]16000); $bw.Write([int]32000)
    $bw.Write([System.Int16]2); $bw.Write([System.Int16]16)
    $bw.Write([byte[]][char[]]'data'); $bw.Write([int]($frames * 2))
    for ($i = 0; $i -lt $frames; $i++) {
      $v = 0
      if ($withTone) { $v = [int](8000 * [math]::Sin(2 * [math]::PI * 440 * $i / 16000)) }
      $bw.Write([System.Int16]$v)
    }
  } finally { $bw.Dispose(); $fs.Dispose() }
}

$tmp = Join-Path $PSScriptRoot '.ser_ab_tmp'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$tone = Join-Path $tmp 'tone.wav'
$silent = Join-Path $tmp 'silent.wav'
$out = Join-Path $tmp 'resp.json'
try {
  New-Wav16k $tone 2 $true
  New-Wav16k $silent 3 $false

  Write-Output '[1/4] /v1/audio/emotion/health'
  $h = Invoke-RestMethod -Uri "$BaseUrl/v1/audio/emotion/health" -TimeoutSec 5
  Write-Output ("  provider={0} ready={1} labels={2}" -f $h.provider, $h.ready, ($h.labels_supported -join ','))

  Write-Output '[2/4] POST /recognize (audio)'
  $code = (& curl.exe -s -o $out -w '%{http_code}' -X POST -F "file=@$tone;type=audio/wav" -F 'sample_rate=16000' -F 'language=zh' "$BaseUrl/recognize" | Out-String).Trim()
  $body = Get-Content $out -Raw -Encoding UTF8
  Write-Output "  HTTP $code $body"

  Write-Output '[3/4] POST /v1/audio/emotion alias'
  $code2 = (& curl.exe -s -o $out -w '%{http_code}' -X POST -F "file=@$tone;type=audio/wav" "$BaseUrl/v1/audio/emotion" | Out-String).Trim()
  Write-Output "  HTTP $code2"

  Write-Output '[4/4] silence -> 409 structured'
  $code3 = (& curl.exe -s -o $out -w '%{http_code}' -X POST -F "file=@$silent;type=audio/wav" "$BaseUrl/recognize" | Out-String).Trim()
  $b3 = Get-Content $out -Raw -Encoding UTF8
  Write-Output "  HTTP $code3 $b3"
  if ($code -notin @('200','409')) { throw "unexpected recognize code $code" }
  if ($code3 -ne '409') { throw "silence should be 409, got $code3" }
  Write-Output 'VERIFY PASS'
} finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
