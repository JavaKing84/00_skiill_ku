# 刷新浏览器登录态：关闭 Chrome → 复制 Cookies/Local State 到独立配置目录 → 以 9333 调试端口启动
# 用途：Folo/Reddit 浏览器会话采集（websession.py）。请在非采集时段手动执行。
$ErrorActionPreference = 'Continue'
$chrome  = 'C:\Users\26808\AppData\Local\Google\Chrome\Application\chrome.exe'
$src     = 'C:\Users\26808\AppData\Local\Google\Chrome\User Data'
$dst     = 'D:\00_skiill_ku\_browser_profile'
$port    = 9333

function Test-Cdp {
  try { return (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/json/version" -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}

Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

New-Item -ItemType Directory -Force -Path "$dst\Default\Network" | Out-Null
New-Item -ItemType Directory -Force -Path "$dst\Default\Local Storage\leveldb" | Out-Null
Copy-Item "$src\Local State" "$dst\Local State" -Force -ErrorAction SilentlyContinue
Copy-Item "$src\Default\Network\Cookies" "$dst\Default\Network\Cookies" -Force -ErrorAction SilentlyContinue
Copy-Item "$src\Default\Preferences" "$dst\Default\Preferences" -Force -ErrorAction SilentlyContinue
Get-ChildItem "$src\Default\Local Storage\leveldb" -File -ErrorAction SilentlyContinue |
  ForEach-Object { Copy-Item $_.FullName "$dst\Default\Local Storage\leveldb\$($_.Name)" -Force -ErrorAction SilentlyContinue }

if (-not (Test-Path "$dst\Default\Network\Cookies")) { 'COPY_FAILED'; exit 1 }

$cmd = '"' + $chrome + '" --remote-debugging-port=' + $port + ' --remote-allow-origins=* --user-data-dir="' + $dst + '" --no-first-run --no-default-browser-check about:blank'
$res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}

$ok = $false
for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Seconds 1; if (Test-Cdp) { $ok = $true; break } }
if ($ok) { 'CDP_READY' } else { 'CDP_TIMEOUT' }
