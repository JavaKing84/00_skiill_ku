# bossauto 定时调度包装（保号版）
# 用法: powershell -ExecutionPolicy Bypass -File run_scheduled.ps1 [-Batch morning] [-Manual]
#   -Manual : 手动运行，跳过随机启动延迟
param(
  [ValidateSet('morning','afternoon','evening')][string]$Batch = 'morning',
  [switch]$Manual
)
$ErrorActionPreference = 'Continue'
$dir    = 'D:\00_skiill_ku\07_bossauto'
$logDir = 'D:\00_skiill_ku\_logs\bossauto'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp  = Get-Date -Format 'yyyyMMdd_HHmm'
$dow    = (Get-Date).DayOfWeek
$runLog = Join-Path $logDir ("run_{0}_{1}.log" -f $stamp, $Batch)

function W($msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
  $line | Tee-Object -FilePath $runLog -Append
}

# STEP0: 封禁冷却闸门（最高优先级，早于任何网络动作）
$state = $null
try { $state = Get-Content (Join-Path $dir 'state.json') -Raw | ConvertFrom-Json } catch {}
if ($state -and $state.banned_until) {
  $bannedUntil = $null
  try { $bannedUntil = [datetime]::Parse($state.banned_until) } catch {}
  if ($bannedUntil -and (Get-Date) -lt $bannedUntil) {
    W "COOLDOWN_BLOCK 账号处于封禁冷却期，禁止运行（至 $bannedUntil）"
    exit 8
  }
}

# 周末不投
if ($dow -in @('Saturday','Sunday')) { W "SKIP weekend ($dow)"; exit 0 }

# 今日启动随机化：默认 0-45 分钟内随机延迟，避免每天固定时刻触发风控画像
if (-not $Manual) {
  $maxDelay = 45
  try {
    $tcfg = Get-Content (Join-Path $dir 'tiers.json') -Raw | ConvertFrom-Json
    if ($tcfg.humanize.startRandomDelayMaxMin) { $maxDelay = [int]$tcfg.humanize.startRandomDelayMaxMin }
  } catch {}
  if ($maxDelay -gt 0) {
    $delay = Get-Random -Minimum 0 -Maximum ($maxDelay + 1)
    if ($delay -gt 0) {
      W "RANDOM_START_DELAY ${delay}min (window 9:00-11:00)"
      Start-Sleep -Seconds ($delay * 60)
      # 延迟后再查一次封禁（期间可能被人工更新）
      $state2 = $null
      try { $state2 = Get-Content (Join-Path $dir 'state.json') -Raw | ConvertFrom-Json } catch {}
      if ($state2 -and $state2.banned_until) {
        $bu2 = $null
        try { $bu2 = [datetime]::Parse($state2.banned_until) } catch {}
        if ($bu2 -and (Get-Date) -lt $bu2) { W "COOLDOWN_BLOCK(after delay) 至 $bu2"; exit 8 }
      }
    }
  }
}

# STEP1: Chrome CDP 就绪
W "STEP1 ensure_chrome begin"
& powershell -ExecutionPolicy Bypass -File (Join-Path $dir 'ensure_chrome.ps1') 2>&1 | ForEach-Object { W "chrome: $_" }
$cdp = $false
try { $r = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9222/json/version' -TimeoutSec 3; $cdp = ($r.StatusCode -eq 200) } catch {}
if (-not $cdp) { W "ABORT CDP_NOT_READY"; exit 3 }
W "STEP1 CDP ready"

# STEP2: 扩展资产校验（招呼语由插件维护；只校验简历图存在）
W "STEP2 sync assets begin"
$syncOut = (& node (Join-Path $dir 'bossctl.js') sync 2>&1 | Out-String)
$syncOut.TrimEnd() | Out-File $runLog -Append
$imgOk = $false
if ($syncOut -match 'SYNC\s+(\{[\s\S]*\})') {
  try {
    $j = $Matches[1] | ConvertFrom-Json
    $imgOk = [bool]($j.imgOk)
  } catch { W "WARN parse SYNC json failed: $_" }
}
if (-not $imgOk) { W "ABORT_ASSETS imgOk=$imgOk"; exit 2 }
W "STEP2 assets OK (imgOk=$imgOk)"

# STEP3: 逐份投递（每日上限 10，每份间隔 5-10 分钟，内部由 bossctl 控制）
$cap = 10
try {
  $tiers = Get-Content (Join-Path $dir 'tiers.json') -Raw | ConvertFrom-Json
  if ($tiers.batchCap.$Batch) { $cap = [int]$tiers.batchCap.$Batch }
} catch {}
W "STEP3 daily batch=$Batch cap=$cap begin"
& node (Join-Path $dir 'bossctl.js') daily $cap 2>&1 | ForEach-Object { W "daily: $_" }
$code = $LASTEXITCODE
W "DONE batch=$Batch exit=$code"
exit $code
