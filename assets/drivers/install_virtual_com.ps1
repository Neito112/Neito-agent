$ErrorActionPreference = "Continue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installerPath = Join-Path $scriptDir "Setup_com0com_x64_signed.exe"
$com0comDir = "${env:ProgramFiles(x86)}\com0com"
if (-not (Test-Path $com0comDir)) {
    $com0comDir = "$env:ProgramFiles\com0com"
}
$setupc = Join-Path $com0comDir "setupc.exe"

if (-not (Test-Path $setupc)) {
    if (Test-Path $installerPath) {
        Write-Host "Installing signed com0com virtual serial driver..."
        $env:CNC_INSTALL_CNCA0_CNCB0_PORTS = "YES"
        $env:CNC_INSTALL_COMX_COMX_PORTS = "NO"
        Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait
        Start-Sleep -Seconds 3
    }
}

$com0comDir = "${env:ProgramFiles(x86)}\com0com"
if (-not (Test-Path $com0comDir)) {
    $com0comDir = "$env:ProgramFiles\com0com"
}
$setupc = Join-Path $com0comDir "setupc.exe"

if (Test-Path $setupc) {
    Push-Location $com0comDir
    $listOut = & $setupc list 2>&1 | Out-String
    if ($listOut -match "CNCA0") {
        & $setupc change CNCA0 PortName=COM9,EmuBR=yes,EmuOverrun=yes | Out-Null
        & $setupc change CNCB0 PortName=COM10,EmuBR=yes,EmuOverrun=yes | Out-Null
    } elseif ($listOut -notmatch "COM9") {
        & $setupc install PortName=COM9,EmuBR=yes,EmuOverrun=yes PortName=COM10,EmuBR=yes,EmuOverrun=yes | Out-Null
    }
    Pop-Location
    Start-Sleep -Seconds 2
}

# Update FriendlyName in Registry so Chrome Web Serial Chooser shows "THE MOCHI - Neito Agent (COM9)"
$enumRoot = "HKLM:\SYSTEM\CurrentControlSet\Enum\com0com"
if (Test-Path $enumRoot) {
    Get-ChildItem -Path $enumRoot -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
        $devPath = $_.PSPath
        $paramsPath = Join-Path $devPath "Device Parameters"
        if (Test-Path $paramsPath) {
            $portName = (Get-ItemProperty -Path $paramsPath -Name "PortName" -ErrorAction SilentlyContinue).PortName
            if ($portName -eq "COM9") {
                Set-ItemProperty -Path $devPath -Name "FriendlyName" -Value "THE MOCHI - Neito Agent (COM9)" -ErrorAction SilentlyContinue
                Set-ItemProperty -Path $devPath -Name "DeviceDesc" -Value "THE MOCHI - Neito Agent" -ErrorAction SilentlyContinue
            } elseif ($portName -eq "COM10") {
                Set-ItemProperty -Path $devPath -Name "FriendlyName" -Value "Neito Agent Internal Bridge (COM10)" -ErrorAction SilentlyContinue
                Set-ItemProperty -Path $devPath -Name "DeviceDesc" -Value "Neito Agent Internal Bridge" -ErrorAction SilentlyContinue
            }
        }
    }
}

Write-Host "Virtual COM pair COM9 <-> COM10 configured successfully."
