# Week 04 A7: collect Windows-side evidence for the security/functional test report.
# Run from an elevated PowerShell in the project folder:
#   powershell -ExecutionPolicy Bypass -File agent\scripts\collect-evidence.ps1
# Output: a timestamped folder under .\evidence with one text file per check.
# It only reads state; it never changes DNS, firewall, processes or the service.

$ErrorActionPreference = 'Continue'
$out = Join-Path (Get-Location) ("evidence\week04-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $out | Out-Null

function Save($name, [scriptblock]$block) {
    $file = Join-Path $out "$name.txt"
    "# $name  ($(Get-Date -Format o))" | Out-File $file -Encoding utf8
    try { & $block 2>&1 | Out-String -Width 200 | Out-File $file -Append -Encoding utf8 }
    catch { "ERROR: $_" | Out-File $file -Append -Encoding utf8 }
}

Save 'service-config'   { sc.exe qc OpenGuardKids; sc.exe qfailure OpenGuardKids; sc.exe qfailureflag OpenGuardKids }
Save 'service-dacl'     { sc.exe sdshow OpenGuardKids }
Save 'service-status'   { Get-Service OpenGuardKids | Format-List *; Get-CimInstance Win32_Service -Filter "Name='OpenGuardKids'" | Format-List ProcessId,StartMode,State,PathName }
Save 'data-acl'         { icacls "$env:ProgramData\OpenGuardKids" }
Save 'tray-process'     { Get-CimInstance Win32_Process | ? CommandLine -like '*agent_gui.py*' | Format-List ProcessId,SessionId,CommandLine }
Save 'dns-adapters'     { Get-NetAdapter | ? Status -eq 'Up' | % { Get-DnsClientServerAddress -InterfaceIndex $_.ifIndex } | Format-Table -AutoSize }
Save 'dns-listeners'    { Get-NetUDPEndpoint -LocalPort 53 -ErrorAction SilentlyContinue; Get-NetTCPConnection -LocalPort 53 -State Listen -ErrorAction SilentlyContinue }
Save 'firewall-rules'   { Get-NetFirewallRule -Group 'OpenGuardKids' | % { $_ | Select DisplayName,Action,Direction,Enabled; $_ | Get-NetFirewallPortFilter | Select Protocol,RemotePort; $_ | Get-NetFirewallAddressFilter | Select RemoteAddress } }
Save 'browser-policies' { 'Chrome','Microsoft\Edge','BraveSoftware\Brave','Mozilla\Firefox\DNSOverHTTPS' | % { $p = "HKLM:\SOFTWARE\Policies\$_"; "$p"; Get-ItemProperty $p -ErrorAction SilentlyContinue } }
Save 'nslookup'         {
    Clear-DnsClientCache
    foreach ($name in 'example.com','dns.google','use-application-dns.net','wikipedia.org','www.google.com') {
        "== $name"; Resolve-DnsName $name -DnsOnly -ErrorAction SilentlyContinue | Format-Table -AutoSize; if (-not $?) { $Error[0].Exception.Message }
    }
    "== direct 8.8.8.8 (expected: blocked by firewall)"
    Resolve-DnsName example.org -Server 8.8.8.8 -DnsOnly -QuickTimeout -ErrorAction SilentlyContinue; if (-not $?) { $Error[0].Exception.Message }
}
Save 'service-log-tail' { Get-Content "$env:ProgramData\OpenGuardKids\logs\service.log" -Tail 200 }
Save 'security-events'  {
    $db = "$env:ProgramData\OpenGuardKids\agent.db"
    & "$PSScriptRoot\..\..\.venv\Scripts\python.exe" -c "import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); [print(r) for r in d.execute('SELECT created_at,event_type,details FROM security_events ORDER BY id DESC LIMIT 50')]; [print('clock', r) for r in d.execute('SELECT * FROM clock_events ORDER BY id DESC LIMIT 20')]; [print('grace', r) for r in d.execute('SELECT * FROM grace_state')]" $db
}

Write-Host "Evidence written to $out"
