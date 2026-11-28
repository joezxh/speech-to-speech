$c = Get-Content -Raw 'd:/work/qwen-audio-agent/speech-to-speech-src/console/design/console-refactor-demo.html'
$i = $c.IndexOf('const head')
Write-Output ("head helper: " + ($c.Substring($i, 400) -replace '\s+', ' '))
# 页面标题相关 CSS（.page-head / h1 / .desc）
foreach ($pat in @('page-head', '.desc', 'h1 {', 'h2 {')) {
  $j = $c.IndexOf($pat)
  if ($j -ge 0) {
    Write-Output ("=== " + $pat + " ===")
    Write-Output ($c.Substring([Math]::Max(0, $j - 80), 500) -replace '\s+', ' ')
  }
}
