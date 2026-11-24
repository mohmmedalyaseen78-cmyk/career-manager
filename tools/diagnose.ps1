# GRAFECO - Device diagnostic (read-only, no install, no network)
# Run: right-click > Run with PowerShell, or run diagnose.bat
$out = Join-Path $PSScriptRoot "device_report.txt"
$lines = @()
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$os  = Get-CimInstance Win32_OperatingSystem
$gpu = Get-CimInstance Win32_VideoController
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
$phys = Get-PhysicalDisk -ErrorAction SilentlyContinue
$lines += "Date: $(Get-Date -Format s)"
$lines += "CPU: $($cpu.Name) | Cores: $($cpu.NumberOfCores) | Threads: $($cpu.NumberOfLogicalProcessors) | MaxMHz: $($cpu.MaxClockSpeed)"
$lines += "RAM total MB: $([math]::Round($os.TotalVisibleMemorySize/1024)) | free MB: $([math]::Round($os.FreePhysicalMemory/1024))"
$lines += "OS: $($os.Caption) $($os.Version) $($os.OSArchitecture)"
foreach($g in $gpu){ $lines += "GPU: $($g.Name) | VRAM MB: $([math]::Round($g.AdapterRAM/1MB)) | Driver: $($g.DriverVersion)" }
foreach($d in $disk){ $lines += "Disk $($d.DeviceID) free GB: $([math]::Round($d.FreeSpace/1GB,1)) of $([math]::Round($d.Size/1GB,1))" }
if($phys){ foreach($d in $phys){ $lines += "PhysicalDisk: $($d.FriendlyName) | Type: $($d.MediaType)" } }
# .NET Framework 4.x release
$rel = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" -ErrorAction SilentlyContinue).Release
$lines += ".NET Framework 4 release key: $rel (528040+ = 4.8)"
# WebView2 runtime
$wv = Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue
if(-not $wv){ $wv = Get-ItemProperty "HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue }
$lines += "WebView2 Runtime: $(if($wv){$wv.pv}else{'NOT FOUND'})"
# SSE4.1/AVX hint (Core 2 E7500 has SSE4.1, no AVX)
$lines += "Note: E7500 expected SSE4.1 yes / AVX no. Binaries must not require AVX."
$lines | Tee-Object -FilePath $out
Write-Host "`nSaved: $out"
