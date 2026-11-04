#!/usr/bin/env pwsh
# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
#
# Zuke launcher for a build another SDK hosts (PowerShell).
#
#   .\zuke.ps1               # run the default target
#   .\zuke.ps1 <target>      # run one target and its prerequisites
#   .\zuke.ps1 --list        # list every target
#
# Runs zuke 2.4.0, which carries the engine and every tool wrapper, so
# this project needs nothing installed but its own SDK's tools. On first use
# it downloads that release, checksum-verified, into ZUKE_INSTALL.
#
# Honoured environment variables:
#   ZUKE_INSTALL       where zuke releases are kept (default: ~/.zuke)
#   ZUKE_RELEASES_URL  a mirror of https://github.com/zuke-build/zuke/releases/download;
#                      what it serves is verified against the pin below

$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

# The pinned release, and the SHA-256 of its Windows archive, from the
# SHA256SUMS of https://github.com/zuke-build/zuke/releases/download/cli-v2.4.0.
# Moved by `zuke upgrade --engine`, which rewrites this file; never hand-edit.
$ZukeVersion = "2.4.0"
$ZukeSha256 = "ba9b52b5c5ca7ceed1f983d1ff5a7b6b13d8fe6ee0da37a72e7bb351aacf8a2d"

if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) {
  throw "zuke: zuke.ps1 runs the Windows release; on this OS run ./zuke instead."
}
$install = if ($env:ZUKE_INSTALL) { $env:ZUKE_INSTALL } else { Join-Path $HOME ".zuke" }
$zuke = Join-Path $install "releases\$ZukeVersion\zuke.exe"

if (-not (Test-Path $zuke)) {
  Write-Host "zuke: zuke $ZukeVersion is not here yet - downloading it..."
  # Arm64 Windows runs the x64 release under emulation; nothing else is built.
  $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
  if ($arch -ne "X64" -and $arch -ne "Arm64") {
    throw "zuke: no zuke release is built for the $arch architecture."
  }
  $asset = "zuke-$ZukeVersion-x86_64-pc-windows-msvc.zip"
  $base = if ($env:ZUKE_RELEASES_URL) { $env:ZUKE_RELEASES_URL } else { "https://github.com/zuke-build/zuke/releases/download" }
  $downloadUrl = "$base/cli-v$ZukeVersion/$asset"
  $workDir = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid())
  New-Item -ItemType Directory -Path $workDir | Out-Null
  $archive = Join-Path $workDir $asset
  try {
    # The progress bar slows a large download severalfold in Windows PowerShell.
    $ProgressPreference = "SilentlyContinue"
    # The network is occasionally flaky (a transient 5xx from the CDN), so a
    # blip is retried with backoff rather than failing the run.
    $maxAttempts = 4
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
      try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $archive -UseBasicParsing
        break
      } catch {
        if ($attempt -ge $maxAttempts) {
          throw "zuke: failed to download $downloadUrl after $maxAttempts attempts: $_"
        }
        $delay = $attempt * 3
        Write-Host "zuke: download failed (attempt $attempt/$maxAttempts); retrying in ${delay}s..."
        Start-Sleep -Seconds $delay
      }
    }

    # .NET directly, not the hashing and archive cmdlets: those come from
    # script modules, which Windows PowerShell started from a PowerShell 7
    # session (whose module path it inherits) cannot load.
    $stream = [System.IO.File]::OpenRead($archive)
    try {
      $digest = [System.Security.Cryptography.SHA256]::Create().ComputeHash($stream)
    } finally {
      $stream.Dispose()
    }
    $actualSha256 = -join ($digest | ForEach-Object { $_.ToString("x2") })
    if ($actualSha256 -ne $ZukeSha256) {
      throw "zuke: checksum mismatch for ${asset}: expected $ZukeSha256, got $actualSha256"
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($archive, (Join-Path $workDir "unpacked"))
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $zuke) | Out-Null
    # Copied beside the target first, which may cross volumes, then renamed in
    # one step, so a run interrupted mid-copy never leaves a binary behind
    # that later runs would trust without verifying.
    $staged = "$zuke.$PID"
    Move-Item -Force -Path (Join-Path $workDir "unpacked\zuke.exe") -Destination $staged
    try {
      Move-Item -Force -Path $staged -Destination $zuke
    } catch {
      # A run started alongside this one put it there first, and may be
      # running it, which Windows will not let this replace.
      Remove-Item -Force $staged -ErrorAction SilentlyContinue
      if (-not (Test-Path $zuke)) { throw }
    }
  } finally {
    Remove-Item -Recurse -Force $workDir -ErrorAction SilentlyContinue
  }
}

# zuke runs the build here itself rather than this launcher again, and does not
# hold this directory to the trust gate: running the launcher named it.
$env:ZUKE_FORWARDED = "1"
$env:ZUKE_LAUNCHER_ROOT = $dir
& $zuke @args
exit $LASTEXITCODE
