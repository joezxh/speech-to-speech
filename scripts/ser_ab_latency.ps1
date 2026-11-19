# 同条件延迟取证：本地 SenseVoice SER vs emotion2vec 代理
# 用法: .\scripts\ser_ab_latency.ps1 -Provider local|proxy [-Rounds 20] [-Seconds 10]
param(
  [ValidateSet('local','proxy')][string]$Provider = 'local',
  [int]$Rounds = 20,
  [int]$Seconds = 10,
  [string]$BaseUrl = 'http://127.0.0.1:8765'
)
$ErrorActionPreference = 'Stop'

# 生成真实音频（正弦近似），WAV 常驻临时目录
$tmp = Join-Path $PSScriptRoot '.ser_ab_tmp'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$wav = Join-Path $tmp "seg_${Seconds}s.wav"
$frames = 16000 * $Seconds
$fs = [System.IO.File]::Open($wav, [System.IO.FileMode]::Create)
$bw = New-Object System.IO.BinaryWriter($fs)
$bw.Write([byte[]][char[]]'RIFF'); $bw.Write([int](36 + $frames * 2))
$bw.Write([byte[]][char[]]'WAVEfmt '); $bw.Write([int]16)
$bw.Write([System.Int16]1); $bw.Write([System.Int16]1)
$bw.Write([int]16000); $bw.Write([int]32000); $bw.Write([System.Int16]2); $bw.Write([System.Int16]16)
$bw.Write([byte[]][char[]]'data'); $bw.Write([int]($frames * 2))
for ($i = 0; $i -lt $frames; $i++) { $bw.Write([System.Int16](8000 * [math]::Sin(2 * [math]::PI * 220 * $i / 16000))) }
$bw.Dispose(); $fs.Dispose()

$path = if ($Provider -eq 'local') { '/recognize' } else { '/v1/audio/emotion' }
$samples = @()
try {
  for ($i = 0; $i -lt $Rounds; $i++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $null = (& curl.exe -s -o NUL -w '%{http_code}' -X POST -F "file=@$wav;type=audio/wav" "$BaseUrl$path" | Out-String).Trim()
    $sw.Stop()
    $samples += $sw.Elapsed.TotalMilliseconds
  }
  $sorted = $samples | Sort-Object
  $p50 = $sorted[[int]($sorted.Count * 0.5)]
  $p95 = $sorted[[int]($sorted.Count * 0.95)]
  Write-Output ("provider={0} seconds={1} rounds={2} P50={3:N0}ms P95={4:N0}ms" -f $Provider, $Seconds, $Rounds, $p50, $p95)
} finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
