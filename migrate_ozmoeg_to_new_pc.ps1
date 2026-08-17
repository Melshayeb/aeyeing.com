#requires -Version 5.1
<#
.SYNOPSIS
    One-click OzMoEg migration script for a new Windows PC.
.DESCRIPTION
    Clones the public website repo and the private skill repo,
    creates a Desktop junction if OneDrive/Desktop is used,
    starts the local trip_planner API server and cloudflared tunnel,
    and verifies the endpoints.
.PARAMETER SiteRepo
    Git URL for the website repo (default: public aeyeing.com repo).
.PARAMETER SkillRepo
    Git URL for the skill repo (default: private ozmoeg-money-maker repo).
.PARAMETER SiteDir
    Where to clone the website. Defaults to the correct Desktop path.
.PARAMETER SkillDir
    Where to clone the skill. Defaults to Hermes skill directory.
.PARAMETER NoStart
    If set, do not start the API server / tunnel after cloning.
#>
param(
    [string]$SiteRepo = "https://github.com/Melshayeb/aeyeing.com.git",
    [string]$SkillRepo = "https://github.com/Melshayeb/ozmoeg-money-maker.git",
    [string]$SiteDir = "",
    [string]$SkillDir = "$env:USERPROFILE\.hermes\skills\ozmoeg-money-maker",
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

function Get-DesktopPath {
    $regular = Join-Path $env:USERPROFILE "Desktop"
    $onedrive  = Join-Path $env:USERPROFILE "OneDrive\Desktop"
    if (Test-Path $onedrive -PathType Container) {
        return $onedrive
    }
    return $regular
}

function Ensure-Junction {
    param([string]$Link, [string]$Target)
    if (Test-Path $Link) {
        $item = Get-Item $Link -ErrorAction SilentlyContinue
        if ($item -and $item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            Write-Host "Junction already exists: $Link -> $Target" -ForegroundColor Green
            return
        }
        Write-Warning "$Link exists but is not a junction. Please resolve manually."
        return
    }
    if (-not (Test-Path $Target -PathType Container)) {
        New-Item -ItemType Directory -Path $Target -Force | Out-Null
    }
    cmd /c "mklink /J `"$Link`" `"$Target`"" | Out-Null
    Write-Host "Created junction: $Link -> $Target" -ForegroundColor Green
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# 1. Ensure git is available
if (-not (Test-Command "git")) {
    throw "git is not installed or not in PATH. Install Git for Windows first."
}

# 2. Resolve Desktop / site directory
$desktop = Get-DesktopPath
Ensure-Junction -Link (Join-Path $env:USERPROFILE "Desktop") -Target $desktop
if ([string]::IsNullOrWhiteSpace($SiteDir)) {
    $SiteDir = Join-Path $desktop "aeyeing.com"
}

# 3. Clone / update website repo
if (Test-Path (Join-Path $SiteDir ".git")) {
    Write-Host "Updating website repo at $SiteDir ..." -ForegroundColor Cyan
    git -C $SiteDir pull
} else {
    Write-Host "Cloning website repo into $SiteDir ..." -ForegroundColor Cyan
    git clone $SiteRepo $SiteDir
}

# 4. Clone / update skill repo
if (Test-Path (Join-Path $SkillDir ".git")) {
    Write-Host "Updating skill repo at $SkillDir ..." -ForegroundColor Cyan
    git -C $SkillDir pull
} else {
    Write-Host "Cloning skill repo into $SkillDir ..." -ForegroundColor Cyan
    git clone $SkillRepo $SkillDir
}

# 5. Ensure Python path used by cron exists (adapt if you install differently)
$pythonw = "$env:LOCALAPPDATA\Programs\Python\Python311\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Warning "pythonw not found at $pythonw. Check Python 3.11 install path."
}

# 6. Start local trip_planner API server
if (-not $NoStart) {
    $apiDir = "$env:LOCALAPPDATA\hermes\skills\ozmoeg\trip_planner\scripts"
    if (Test-Path "$apiDir\api.py") {
        $apiProc = Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -like "*api.py*"
        }
        if (-not $apiProc) {
            Write-Host "Starting trip_planner API server ..." -ForegroundColor Cyan
            Start-Process -FilePath $pythonw -ArgumentList "$apiDir\api.py" -WorkingDirectory $apiDir -WindowStyle Hidden
        } else {
            Write-Host "trip_planner API already running (PID $($apiProc.Id))" -ForegroundColor Green
        }
    } else {
        Write-Warning "api.py not found at $apiDir"
    }

    # 7. Start cloudflared tunnel (if service not already registered/running)
    $cf = "$env:LOCALAPPDATA\hermes\skills\ozmoeg\trip_planner\scripts\cloudflared.exe"
    if (Test-Path $cf) {
        $cfProc = Get-Process cloudflared -ErrorAction SilentlyContinue
        if (-not $cfProc) {
            Write-Host "Starting cloudflared tunnel ..." -ForegroundColor Cyan
            Start-Process -FilePath $cf -ArgumentList "tunnel","run" -WindowStyle Hidden
        } else {
            Write-Host "cloudflared already running (PID $($cfProc.Id))" -ForegroundColor Green
        }
    } else {
        Write-Warning "cloudflared.exe not found next to api.py"
    }
}

# 8. Verify local endpoint
Write-Host "Verifying local API ..." -ForegroundColor Cyan
Start-Sleep -Seconds 3
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8777/ozmoeg/ozmoeg-latest.json" -TimeoutSec 10
    $alerts = @($resp.scan_results | Where-Object { $_.status -in @('ALERT','ALERT/HALT') })
    Write-Host "Local API OK: $($alerts.Count) ALERT(s)" -ForegroundColor Green
} catch {
    Write-Warning "Could not reach local API: $_"
}

# 9. Verify website via browser hint
$siteUrl = "https://aeyeing.com/ozmoeg-trader-us.html?_cb=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
Write-Host "Open the site to confirm: $siteUrl" -ForegroundColor Cyan

Write-Host "`nMigration complete. If the site shows stale data, hard-refresh with Ctrl+Shift+R." -ForegroundColor Green
