# winbox 게스트 에이전트 — 샌드박스 안(또는 -Local 시 호스트)에서 우편함을 감시하며 PowerShell 요청을 실행한다.
param([string]$Root = 'C:\winbox', [switch]$Local, [int]$IdleMinutes = 30)
$ErrorActionPreference = 'Continue'
$mail = Join-Path $Root 'mail'; $req = Join-Path $mail 'req'; $res = Join-Path $mail 'res'
$tmpd = if ($Local) { Join-Path $Root 'tmp' } else { 'C:\winbox-tmp' }  # 스냅샷 대상 경로 밖
New-Item -ItemType Directory -Force $req, $res, (Join-Path $mail 'out'), $tmpd | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding $true

function Stop-Box {
    # 호스트를 끄는 사고 방지: 샌드박스 전용 계정일 때만 종료
    if (-not $Local -and $env:USERNAME -eq 'WDAGUtilityAccount') { Stop-Computer -Force }
    exit 0
}

function Invoke-Exec($r) {
    $ps1 = Join-Path $tmpd ("$([guid]::NewGuid().ToString('N')).ps1")
    $pre = '[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference="SilentlyContinue"' + "`r`n"
    [IO.File]::WriteAllText($ps1, $pre + $r.command, $utf8)
    $psi = New-Object Diagnostics.ProcessStartInfo 'powershell.exe'
    $psi.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$ps1`""
    $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = [Diagnostics.Process]::Start($psi)
    $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
    $t = [int]$r.timeout; if ($t -le 0) { $t = 120 }
    $timedOut = -not $p.WaitForExit($t * 1000)
    if ($timedOut) { try { $p.Kill() } catch {} ; $p.WaitForExit(5000) | Out-Null }
    Remove-Item $ps1 -Force -ErrorAction SilentlyContinue
    @{ exit = $(if ($timedOut) { -1 } else { $p.ExitCode }); stdout = $o.Result; stderr = $e.Result
       timed_out = $timedOut; ms = $sw.ElapsedMilliseconds }
}

[IO.File]::WriteAllText((Join-Path $mail 'ready'), "$env:COMPUTERNAME $env:USERNAME $(Get-Date -Format o)", $utf8)
$last = Get-Date
while ($true) {
    foreach ($f in @(Get-ChildItem $req -Filter *.json -ErrorAction SilentlyContinue)) {
        try { $r = [IO.File]::ReadAllText($f.FullName) | ConvertFrom-Json } catch { continue }
        Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
        if ($r.op -eq 'stop') { Stop-Box }
        try { $out = Invoke-Exec $r } catch { $out = @{ exit = -2; stdout = ''; stderr = "agent: $_"; timed_out = $false } }
        $tmp = Join-Path $res "$($f.BaseName).tmp"
        [IO.File]::WriteAllText($tmp, ($out | ConvertTo-Json -Compress), $utf8)
        Move-Item $tmp (Join-Path $res "$($f.BaseName).json") -Force
        $last = Get-Date
    }
    if (((Get-Date) - $last).TotalMinutes -gt $IdleMinutes) { Stop-Box }
    Start-Sleep -Milliseconds 200
}
