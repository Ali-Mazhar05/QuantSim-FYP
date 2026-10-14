# Gives Windows back the disk space Docker Desktop has freed. Docker keeps all images,
# containers and volumes in one virtual disk file that grows but never shrinks by itself,
# so C: can run low even after Jenkins' sweep has cleaned up inside Docker.
#
# Usage, in PowerShell started with "Run as administrator":
#   1. ci/jenkins/host.sh stop          (in Git Bash first, so Jenkins' state is handed over)
#   2. powershell -ExecutionPolicy Bypass -File ci\jenkins\compact-docker-disk.ps1
#   3. Start Docker Desktop normally from the Start menu (NOT as administrator), wait for
#      "Engine running", then ci/jenkins/host.sh start
#
# Takes a few minutes. Docker Desktop is stopped while it runs.

$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Error "Run this from PowerShell started with 'Run as administrator'."
}

$vhd = Get-ChildItem "$env:LOCALAPPDATA\Docker\wsl" -Recurse -Filter docker_data.vhdx -ErrorAction SilentlyContinue |
  Select-Object -First 1
if (-not $vhd) { Write-Error "Docker's disk file (docker_data.vhdx) was not found." }

"Docker disk before: {0:N1} GB" -f ($vhd.Length / 1GB)

"Stopping Docker Desktop"
Get-Process "Docker Desktop", "com.docker.backend", "com.docker.build" -ErrorAction SilentlyContinue |
  Stop-Process -Force
Start-Sleep 10
wsl --shutdown
Start-Sleep 5

"Compacting $($vhd.FullName)"
if (Get-Command Optimize-VHD -ErrorAction SilentlyContinue) {
  Optimize-VHD -Path $vhd.FullName -Mode Full
} else {
  # Windows editions without the Hyper-V module
  $script = New-TemporaryFile
  @(
    "select vdisk file=`"$($vhd.FullName)`""
    "attach vdisk readonly"
    "compact vdisk"
    "detach vdisk"
  ) | Set-Content -Encoding ascii $script
  diskpart /s $script
  Remove-Item $script
}

"Docker disk after: {0:N1} GB" -f ((Get-Item $vhd.FullName).Length / 1GB)
"Done. Start Docker Desktop normally (not as administrator), then: ci/jenkins/host.sh start"
