# 시스템 상태 스냅샷 → JSON. 섹션마다 {키: 값} — 호스트 winbox.py diff()가 섹션별로 비교한다.
# 애드인 시험(Office 등록·XLSTART·AddIns)과 동적 분석(자동실행·서비스·예약작업·연결·DNS)을 같이 본다.
param([Parameter(Mandatory)][string]$Out)
$ErrorActionPreference = 'SilentlyContinue'

$files = @{}
$roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData, $env:APPDATA, $env:LOCALAPPDATA,
           "$env:USERPROFILE\Desktop", "$env:USERPROFILE\Documents", "$env:windir\System32\drivers", "$env:windir\Tasks")
foreach ($root in $roots | Where-Object { $_ -and (Test-Path $_) }) {
    foreach ($f in Get-ChildItem -LiteralPath $root -Recurse -File -Force) {
        $files[$f.FullName] = "$($f.Length)|$($f.LastWriteTimeUtc.Ticks)"
    }
}

$reg = @{}
function Add-Key($k) {
    $reg["$($k.Name)\"] = ''
    foreach ($v in $k.GetValueNames()) { $reg["$($k.Name)\\$v"] = "$($k.GetValue($v, $null, 'DoNotExpandEnvironmentNames'))" }
}
$keys = 'HKCU:\Software', 'HKLM:\SOFTWARE\Microsoft\Office', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Office',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run', 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run', 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon',
        'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options', 'HKLM:\SOFTWARE\Policies'
foreach ($p in $keys | Where-Object { Test-Path $_ }) {
    $top = Get-Item $p; Add-Key $top
    foreach ($k in Get-ChildItem $p -Recurse) { Add-Key $k }
}

$clsid = @{}  # COM 등록(COM·VSTO 애드인) — 키 이름만
foreach ($p in 'HKLM:\SOFTWARE\Classes\CLSID', 'HKLM:\SOFTWARE\WOW6432Node\Classes\CLSID') {
    foreach ($k in Get-ChildItem $p) { $clsid[$k.Name] = "$($k.GetValue(''))" }
}

$services = @{}
foreach ($s in Get-CimInstance Win32_Service) { $services[$s.Name] = "$($s.State)|$($s.StartMode)|$($s.PathName)" }

$tasks = @{}
foreach ($t in Get-ScheduledTask) { $tasks["$($t.TaskPath)$($t.TaskName)"] = (($t.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' ; ') }

$procs = @{}  # 이름|경로 → 개수 (PID는 매번 달라 비교 키로 못 씀)
foreach ($p in Get-CimInstance Win32_Process) { $k = "$($p.Name)|$($p.ExecutablePath)"; $procs[$k] = [int]$procs[$k] + 1 }
$names = @{}; foreach ($p in Get-Process) { $names[$p.Id] = $p.ProcessName }

$net = @{}
foreach ($c in Get-NetTCPConnection) {
    if ($c.State -in 'Listen', 'Established', 'SynSent') {
        $net["tcp $($c.State) $($c.LocalPort)->$($c.RemoteAddress):$($c.RemotePort)"] = $names[[int]$c.OwningProcess]
    }
}
$dns = @{}; foreach ($d in Get-DnsClientCache) { $dns[$d.Entry] = "$($d.Data)" }

$snap = [ordered]@{ files = $files; registry = $reg; clsid = $clsid; services = $services; tasks = $tasks
                    processes = $procs; network = $net; dns = $dns }
[IO.File]::WriteAllText($Out, ($snap | ConvertTo-Json -Depth 3 -Compress), (New-Object System.Text.UTF8Encoding $false))
($snap.Keys | ForEach-Object { "$_=$($snap[$_].Count)" }) -join ' '
