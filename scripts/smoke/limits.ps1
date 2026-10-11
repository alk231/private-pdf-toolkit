<#
.SYNOPSIS
  Real-limits test: runs the heaviest tools against the 512 MB docker compose service
  and records the peak memory seen by docker stats.
.EXAMPLE
  docker compose up --build            # terminal 1
  powershell -ExecutionPolicy Bypass -File .\scripts\smoke\limits.ps1   # terminal 2
  Exit code 0 = every job finished and the container survived, 1 = something failed.
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://localhost:8000',
    [string]$Service = 'api',
    [string]$Container = '',
    [string]$DockerImage = 'pdf-toolkit-api',
    [int]$JobTimeoutSec = 900,
    [int]$HeavyMb = 12,
    [int]$HeavyPages = 40,
    [switch]$KeepFiles
)

$ErrorActionPreference = 'Continue'
$BaseUrl = $BaseUrl.TrimEnd('/')
$WorkDir = Join-Path $PSScriptRoot '.work_limits'
if (Test-Path -LiteralPath $WorkDir) { Remove-Item -LiteralPath $WorkDir -Recurse -Force }
New-Item -ItemType Directory -Path $WorkDir | Out-Null
$DeviceId = [guid]::NewGuid().ToString()

if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { Write-Host 'curl.exe not found' -ForegroundColor Red; exit 2 }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host 'docker not found' -ForegroundColor Red; exit 2 }

if (-not $Container) {
    Push-Location (Resolve-Path (Join-Path $PSScriptRoot '..\..'))
    $Container = (& docker compose ps -q $Service 2>$null | Select-Object -First 1)
    Pop-Location
}
if (-not $Container) { Write-Host "Could not find the running '$Service' container. Start it with: docker compose up --build" -ForegroundColor Red; exit 2 }
Write-Host "Container: $Container"

# ---- helper (local python if possible, else the docker image)
$py = ''
foreach ($c in @('python', 'python3', 'py')) {
    if (Get-Command $c -ErrorAction SilentlyContinue) {
        & $c -c "import fitz, pikepdf, PIL" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
    }
}
function Invoke-Helper([string[]]$HelperArgs) {
    if ($py) { $o = & $py (Join-Path $PSScriptRoot 'smoke_helper.py') --workdir $WorkDir @HelperArgs 2>&1 }
    else { $o = & docker run --rm --user root --entrypoint python -v "${WorkDir}:/data" -v "${PSScriptRoot}:/smoke:ro" $DockerImage /smoke/smoke_helper.py --workdir /data @HelperArgs 2>&1 }
    $code = $LASTEXITCODE
    return [pscustomobject]@{ Code = $code; Output = (($o | ForEach-Object { "$_" }) -join ' ') }
}

# ---- memory and container state
function Get-MemMb {
    $line = & docker stats --no-stream --format '{{.MemUsage}}' $Container 2>$null
    if (-not $line) { return $null }
    $used = (("$line" -split '/')[0]).Trim()
    if ($used -notmatch '^([0-9.,]+)\s*([A-Za-z]+)$') { return $null }
    $num = [double]::Parse(($Matches[1] -replace ',', '.'), [Globalization.CultureInfo]::InvariantCulture)
    $factor = @{ 'B' = 1 / 1048576; 'kB' = 1000 / 1048576; 'KiB' = 1 / 1024; 'MB' = 1000000 / 1048576; 'MiB' = 1; 'GB' = 1000000000 / 1048576; 'GiB' = 1024 }[$Matches[2]]
    if (-not $factor) { return $null }
    return [math]::Round($num * $factor, 1)
}
function Get-State {
    $s = & docker inspect -f '{{.State.Running}}|{{.State.OOMKilled}}|{{.RestartCount}}|{{.State.ExitCode}}' $Container 2>$null
    $p = ("$s").Trim() -split '\|'
    if ($p.Count -lt 4) { return [pscustomobject]@{ Running = $false; Oom = $false; Restarts = 0; Exit = -1 } }
    return [pscustomobject]@{ Running = ($p[0] -eq 'true'); Oom = ($p[1] -eq 'true'); Restarts = [int]$p[2]; Exit = [int]$p[3] }
}

# ---- HTTP
function Get-Json([string]$Url) {
    $t = & curl.exe -s -m 20 $Url 2>$null
    if (-not $t) { return $null }
    try { return ($t | ConvertFrom-Json) } catch { return $null }
}
function Submit([string]$Tool, [string[]]$Files, [string]$Options) {
    $body = Join-Path $WorkDir 'submit.body'
    $ca = @('-s', '--max-time', '600', '-o', $body, '-w', '%{http_code}', '-H', "X-Device-Id: $DeviceId")
    foreach ($f in $Files) { $ca += @('-F', ("files=@" + (Join-Path $WorkDir $f))) }
    if ($Options) {
        $of = Join-Path $WorkDir 'opt.json'
        [IO.File]::WriteAllText($of, $Options, (New-Object Text.UTF8Encoding($false)))
        $ca += @('-F', "options=<$of")
    }
    $ca += "$BaseUrl/v1/tools/$Tool"
    $code = & curl.exe @ca 2>$null
    $j = $null
    try { $j = Get-Content -LiteralPath $body -Raw | ConvertFrom-Json } catch { }
    return [pscustomobject]@{ Code = [int]("0" + "$code".Trim()); Json = $j }
}

# ---- run
$h = Invoke-Helper @('samples')
if ($h.Code -ne 0) { Write-Host "samples failed: $($h.Output)" -ForegroundColor Red; exit 2 }
$h = Invoke-Helper @('heavy', '--mb', "$HeavyMb", '--pages', "$HeavyPages", '--photos', '6')
if ($h.Code -ne 0) { Write-Host "heavy files failed: $($h.Output)" -ForegroundColor Red; exit 2 }
Write-Host $h.Output -ForegroundColor DarkGray

$health = Get-Json "$BaseUrl/v1/health"
if (-not $health -or $health.status -ne 'ok') { Write-Host 'Server is not healthy.' -ForegroundColor Red; exit 2 }
$idle = Get-MemMb
Write-Host ("Idle memory: {0} MiB" -f $idle)

$photos = @('photo_big_1.jpg', 'photo_big_2.jpg', 'photo_big_3.jpg', 'photo_big_4.jpg', 'photo_big_5.jpg', 'photo_big_6.jpg')
$jobs = @(
    @{ Name = 'compress ebook, heavy_doc.pdf'; Tool = 'compress'; Files = @('heavy_doc.pdf'); Options = '{"level":"ebook"}' },
    @{ Name = 'pdf-to-images 300 dpi jpg, pages 1-20'; Tool = 'pdf-to-images'; Files = @('heavy_doc.pdf'); Options = '{"format":"jpg","dpi":300,"pages":"1-20"}' },
    @{ Name = 'pdf-to-images 300 dpi png, pages 1-5'; Tool = 'pdf-to-images'; Files = @('heavy_doc.pdf'); Options = '{"format":"png","dpi":300,"pages":"1-5"}' },
    @{ Name = 'page-numbers on heavy_doc.pdf'; Tool = 'page-numbers'; Files = @('heavy_doc.pdf'); Options = '{"format":"page_n_of_total"}' },
    @{ Name = 'watermark text on heavy_doc.pdf'; Tool = 'watermark'; Files = @('heavy_doc.pdf'); Options = '{"type":"text","text":"DRAFT"}' },
    @{ Name = 'watermark image on heavy_doc.pdf'; Tool = 'watermark'; Files = @('heavy_doc.pdf', 'logo.png'); Options = '{"type":"image","scale":50}' },
    @{ Name = 'images-to-pdf 6 large photos, quality high'; Tool = 'images-to-pdf'; Files = $photos; Options = '{"page_size":"a4","quality":"high"}' }
)

$rows = @()
$overall = 0.0
$abort = $false
foreach ($job in $jobs) {
    if ($abort) { $rows += [pscustomobject]@{ Job = $job.Name; Result = 'not run'; Peak = '-'; Sec = '-'; Out = '-' }; continue }
    Write-Host ("--- {0}" -f $job.Name) -ForegroundColor Cyan
    $t0 = Get-Date
    $peak = 0.0
    $result = ''
    $outMb = '-'
    $sub = Submit $job.Tool $job.Files $job.Options
    if ($sub.Code -ne 202 -or -not $sub.Json.job_id) {
        $ec = ''
        if ($sub.Json -and $sub.Json.error) { $ec = $sub.Json.error.code }
        $result = "submit failed HTTP $($sub.Code) $ec"
    }
    else {
        $id = [string]$sub.Json.job_id
        while ($true) {
            $m = Get-MemMb
            if ($null -ne $m -and $m -gt $peak) { $peak = $m }
            $st = Get-Json "$BaseUrl/v1/jobs/$id"
            if ($st -and ($st.status -eq 'done' -or $st.status -eq 'failed')) {
                if ($st.status -eq 'done') {
                    $out = Join-Path $WorkDir 'limits_out.bin'
                    $dc = & curl.exe -s -m 300 -o $out -w '%{http_code}' "$BaseUrl/v1/jobs/$id/result"
                    $size = 0
                    if (Test-Path -LiteralPath $out) { $size = (Get-Item -LiteralPath $out).Length; Remove-Item -LiteralPath $out -Force }
                    $outMb = '{0:N1}' -f ($size / 1MB)
                    if ("$dc" -eq '200' -and $size -gt 0) { $result = 'OK' } else { $result = "download HTTP $dc" }
                }
                else { $result = "failed: $($st.error.code)" }
                break
            }
            if (-not $st) {
                $state = Get-State
                if (-not $state.Running) { $result = 'CONTAINER DIED'; break }
            }
            if (((Get-Date) - $t0).TotalSeconds -gt $JobTimeoutSec) { $result = 'script timeout'; break }
        }
    }
    $sec = [int]((Get-Date) - $t0).TotalSeconds
    $state = Get-State
    if ($state.Oom) { $result += ' (OOMKilled)' }
    if (-not $state.Running) { $result = 'CONTAINER DIED ' + $result; $abort = $true }
    if ($peak -gt $overall) { $overall = $peak }
    $rows += [pscustomobject]@{ Job = $job.Name; Result = $result; Peak = ('{0:N0} MiB' -f $peak); Sec = $sec; Out = "$outMb MiB" }
    $col = 'Green'; if ($result -notlike 'OK*') { $col = 'Red' }
    Write-Host ("    {0}  peak {1:N0} MiB  {2} s" -f $result, $peak, $sec) -ForegroundColor $col
    Start-Sleep -Seconds 2
}

Write-Host ''
$rows | Format-Table -AutoSize
$final = Get-State
Write-Host ("Idle {0} MiB, highest peak seen {1:N0} MiB of 512 MiB. Container running={2} OOMKilled={3} restarts={4}" -f $idle, $overall, $final.Running, $final.Oom, $final.Restarts)
if ($overall -gt 435) { Write-Host 'Peak above ~85% of the limit: too tight for the free plan.' -ForegroundColor Yellow }
elseif ($overall -gt 0) { Write-Host 'Peak is comfortably under the limit (docker stats is sampled, so treat it as a lower bound).' }

$bad = @($rows | Where-Object { $_.Result -notlike 'OK*' })
if (-not $KeepFiles) { Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue }
if ($bad.Count -gt 0) { Write-Host ("{0} job(s) did not finish cleanly" -f $bad.Count) -ForegroundColor Red; exit 1 }
Write-Host 'ALL HEAVY JOBS FINISHED' -ForegroundColor Green
exit 0
