param([switch]$Force)
$ErrorActionPreference = "Stop"
$chrome  = "C:\Users\26808\AppData\Local\Google\Chrome\Application\chrome.exe"
$profile = "E:\AppCache\Temp\boss_auto"
$ext     = "E:\BossHelperPatched"

function Test-Cdp {
  try {
    $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:9222/json/version" -TimeoutSec 3
    return $r.StatusCode -eq 200
  } catch { return $false }
}

# 只清理 boss_auto 这个自动化实例的残留进程，绝不碰用户默认 Chrome
function Stop-BossChrome {
  $procs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*boss_auto*' }
  foreach ($p in $procs) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
  }
  if ($procs) { Start-Sleep -Seconds 2 }
}

if ($Force) { Stop-BossChrome }

if (-not (Test-Cdp)) {
  Stop-BossChrome
  $cmd = '"' + $chrome + '" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="' + $profile + '" --load-extension="' + $ext + '" --no-first-run --no-default-browser-check --start-maximized --force-renderer-accessibility --disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling "https://www.zhipin.com/web/geek/jobs?query=python%E5%AE%9E%E4%B9%A0&city=101010100&experience=108&jobType=1902"'
  $res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}
  Write-Output ("LAUNCH ret=" + $res.ReturnValue + " pid=" + $res.ProcessId)
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Cdp) { Write-Output "CDP_READY"; exit 0 }
  }
  Write-Output "CDP_TIMEOUT"
  exit 1
}
Write-Output "CDP_ALREADY_READY"
