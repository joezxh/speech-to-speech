# U5 人检取数：批量 wav -> CSV，含 emotion/confidence/margin/AED 事件/rawLabel/latency
# 用法: .\scripts\ser_ab_smoke.ps1 -WavDir <dir> -OutCsv <path> [-Provider local|proxy]
param(
  [Parameter(Mandatory=$true)][string]$WavDir,
  [Parameter(Mandatory=$true)][string]$OutCsv,
  [ValidateSet('local','proxy')][string]$Provider = 'local',
  [string]$BaseUrl = 'http://127.0.0.1:8765'
)
$ErrorActionPreference = 'Stop'
$path = if ($Provider -eq 'local') { '/recognize' } else { '/v1/audio/emotion' }
$rows = New-Object System.Collections.Generic.List[string]
$rows.Add('file,provider,emotion,confidence,margin,laughter,rawLabel,latencyMs,http_code,human_label')
$tmp = Join-Path $PSScriptRoot '.ser_ab_tmp'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$out = Join-Path $tmp 'r.json'
try {
  Get-ChildItem $WavDir -Filter *.wav | ForEach-Object {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $code = (& curl.exe -s -o $out -w '%{http_code}' -X POST -F "file=$($_.FullName);type=audio/wav" "$BaseUrl$path" | Out-String).Trim()
    $sw.Stop()
    $j = if (Test-Path $out) { Get-Content $out -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
    $emo = if ($j.emotion) { $j.emotion } elseif ($j.error.code) { "REJECT:$($j.error.code)" } else { '' }
    $conf = if ($j.confidence) { $j.confidence } else { '' }
    $margin = if ($j.margin) { $j.margin } else { '' }
    $laugh = if ($j.events.laughter) { $j.events.laughter } else { $false }
    $raw = if ($j.rawLabel) { $j.rawLabel } else { '' }
    $csv = '{0},{1},{2},{3},{4},{5},{6},{7},{8},' -f $_.Name, $Provider, $emo, $conf, $margin, $laugh, $raw, [int]$sw.Elapsed.TotalMilliseconds, $code
    $rows.Add($csv)
  }
  $rows | Set-Content $OutCsv -Encoding UTF8
  Write-Output "wrote $($rows.Count - 1) rows to $OutCsv"
} finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
