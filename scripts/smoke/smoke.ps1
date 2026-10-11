<#
.SYNOPSIS
  Smoke test for every Wave 1 endpoint of the PDF Toolkit API.

.EXAMPLE
  .\scripts\smoke\smoke.ps1
  .\scripts\smoke\smoke.ps1 -BaseUrl https://my-service.onrender.com
  powershell -ExecutionPolicy Bypass -File .\scripts\smoke\smoke.ps1 -HelperMode docker

  Exit code 0 = all checks passed, 1 = at least one check failed, 2 = setup problem.
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://localhost:8000',
    [ValidateSet('auto', 'local', 'docker')][string]$HelperMode = 'auto',
    [string]$Python = '',
    [string]$DockerImage = 'pdf-toolkit-api',
    [int]$ColdStartSec = 90,
    [int]$JobTimeoutSec = 240,
    [switch]$SkipBigUpload,
    [switch]$KeepFiles
)

$ErrorActionPreference = 'Continue'
$BaseUrl = $BaseUrl.TrimEnd('/')
$WorkDir = Join-Path $PSScriptRoot '.work'
$script:ReqNo = 0
$script:PostCount = 0
$script:DeviceId = [guid]::NewGuid().ToString()
$script:Pass = 0
$script:Fail = 0
$script:FailedNames = @()
$script:MaxFileMb = 25
$script:UseDocker = $false
$script:PythonExe = ''
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# ---------------------------------------------------------------- setup

if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Write-Host 'curl.exe was not found (it ships with Windows 10/11).' -ForegroundColor Red
    exit 2
}

if (-not (Test-Path -LiteralPath $WorkDir)) { New-Item -ItemType Directory -Path $WorkDir | Out-Null }
Get-ChildItem -LiteralPath $WorkDir -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

function Test-LocalPython([string]$Exe) {
    if (-not (Get-Command $Exe -ErrorAction SilentlyContinue)) { return $false }
    & $Exe -c "import fitz, pikepdf, PIL" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

if ($HelperMode -ne 'docker') {
    $cands = @()
    if ($Python) { $cands += $Python }
    $cands += @('python', 'python3', 'py')
    foreach ($c in $cands) {
        if (Test-LocalPython $c) { $script:PythonExe = $c; break }
    }
}
if (-not $script:PythonExe) {
    if ($HelperMode -eq 'local') {
        Write-Host 'No local Python with PyMuPDF, pikepdf and Pillow found. Run: pip install -r backend/requirements.txt' -ForegroundColor Red
        exit 2
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host 'No usable Python and no docker command. Install the backend requirements in your venv.' -ForegroundColor Red
        exit 2
    }
    & docker image inspect $DockerImage 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker image '$DockerImage' not found. Build it: docker build -t $DockerImage ./backend" -ForegroundColor Red
        exit 2
    }
    $script:UseDocker = $true
}

function Invoke-Helper {
    param([string[]]$HelperArgs)
    if ($script:UseDocker) {
        $out = & docker run --rm --user root --entrypoint python -v "${WorkDir}:/data" -v "${PSScriptRoot}:/smoke:ro" $DockerImage /smoke/smoke_helper.py --workdir /data @HelperArgs 2>&1
    }
    else {
        $out = & $script:PythonExe (Join-Path $PSScriptRoot 'smoke_helper.py') --workdir $WorkDir @HelperArgs 2>&1
    }
    $code = $LASTEXITCODE
    $text = (($out | ForEach-Object { "$_" }) -join ' ').Trim()
    return [pscustomobject]@{ Code = $code; Output = $text }
}

# ---------------------------------------------------------------- reporting

function Report([string]$Name, [bool]$Ok, [string]$Detail = '') {
    if ($Ok) {
        $script:Pass++
        Write-Host ("PASS  {0}" -f $Name) -ForegroundColor Green
        if ($Detail) { Write-Host ("      {0}" -f $Detail) -ForegroundColor DarkGray }
    }
    else {
        $script:Fail++
        $script:FailedNames += $Name
        Write-Host ("FAIL  {0}" -f $Name) -ForegroundColor Red
        if ($Detail) { Write-Host ("      {0}" -f $Detail) -ForegroundColor Yellow }
    }
}

function Section([string]$Title) {
    Write-Host ''
    Write-Host ("=== {0} ===" -f $Title) -ForegroundColor Cyan
}

# ---------------------------------------------------------------- HTTP

function Invoke-Api {
    param(
        [string]$Method = 'GET',
        [string]$Path,
        [string[]]$Files = @(),
        [string]$Options = '',
        [string]$OutFile = '',
        [string]$Tag = '',
        [int]$MaxTime = 300
    )
    if ($Tag) { $stem = "resp_$Tag" } else { $script:ReqNo++; $stem = 'resp_{0:D3}' -f $script:ReqNo }
    if ($OutFile) { $body = Join-Path $WorkDir $OutFile } else { $body = Join-Path $WorkDir "$stem.body" }
    $hdr = Join-Path $WorkDir "$stem.hdr"

    $curlArgs = @('-s', '--max-time', "$MaxTime", '-X', $Method, '-o', $body, '-D', $hdr, '-w', '%{http_code}')
    if ($Method -eq 'POST') {
        # rotate the device id so one run stays under the per-device rate limit
        if (($script:PostCount % 20) -eq 0) { $script:DeviceId = [guid]::NewGuid().ToString() }
        $script:PostCount++
        $curlArgs += @('-H', "X-Device-Id: $($script:DeviceId)")
        foreach ($f in $Files) {
            $full = Join-Path $WorkDir $f
            $curlArgs += @('-F', "files=@$full")
        }
        if ($Options) {
            $optFile = Join-Path $WorkDir ("opt_{0}.json" -f $stem)
            [System.IO.File]::WriteAllText($optFile, $Options, (New-Object System.Text.UTF8Encoding($false)))
            $curlArgs += @('-F', "options=<$optFile")
        }
    }
    $curlArgs += "$BaseUrl$Path"

    $code = & curl.exe @curlArgs 2>$null
    $status = 0
    [int]::TryParse(("$code").Trim(), [ref]$status) | Out-Null
    return [pscustomobject]@{ Code = $status; Body = $body; Hdr = $hdr; Path = $Path }
}

function Read-Json($Resp) {
    if (-not (Test-Path -LiteralPath $Resp.Body)) { return $null }
    try { return (Get-Content -LiteralPath $Resp.Body -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}

function Get-Header($Resp, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Resp.Hdr)) { return $null }
    $val = $null
    foreach ($line in (Get-Content -LiteralPath $Resp.Hdr)) {
        if ($line -match ('(?i)^' + [regex]::Escape($Name) + ':\s*(.*)$')) { $val = $Matches[1].Trim() }
    }
    return $val
}

function Get-ErrCode($Resp) {
    $j = Read-Json $Resp
    if ($j -and $j.error) { return [string]$j.error.code }
    return ''
}

function Submit-Tool {
    param([string]$Tool, [string[]]$Files, [string]$Options = '', [switch]$Wait, [string]$OutFile = '')
    $path = "/v1/tools/$Tool"
    if ($Wait) { $path += '?wait=true' }
    return Invoke-Api -Method POST -Path $path -Files $Files -Options $Options -OutFile $OutFile
}

function Wait-ApiJob([string]$JobId) {
    $deadline = (Get-Date).AddSeconds($JobTimeoutSec)
    while ($true) {
        $r = Invoke-Api -Method GET -Path "/v1/jobs/$JobId" -Tag 'poll'
        $j = Read-Json $r
        if ($r.Code -eq 200 -and $j) {
            if ($j.status -eq 'done' -or $j.status -eq 'failed') {
                return [pscustomobject]@{ Http = $r.Code; Job = $j }
            }
        }
        elseif ($r.Code -ne 0) {
            return [pscustomobject]@{ Http = $r.Code; Job = $j }
        }
        if ((Get-Date) -gt $deadline) { return [pscustomobject]@{ Http = -1; Job = $j } }
        Start-Sleep -Milliseconds 500
    }
}

# submit -> poll -> download (the real flow)
function Invoke-ToolJob {
    param([string]$Tool, [string[]]$Files, [string]$Options = '', [string]$OutName = '')
    if (-not $OutName) { $OutName = 'out_{0}.bin' -f $Tool }
    $sub = Submit-Tool -Tool $Tool -Files $Files -Options $Options
    $sj = Read-Json $sub
    if ($sub.Code -ne 202 -or -not $sj -or -not $sj.job_id) {
        $ec = Get-ErrCode $sub
        return [pscustomobject]@{
            Ok = $false; Stage = 'submit'; Http = $sub.Code; ErrCode = $ec
            Message = ("submit -> HTTP {0} {1}" -f $sub.Code, $ec)
            Job = $null; JobId = ''; File = ''; DownloadCode = 0; DownloadErr = ''
        }
    }
    $id = [string]$sj.job_id
    $w = Wait-ApiJob $id
    $job = $w.Job
    if (-not $job -or $job.status -ne 'done') {
        $ec = ''; $msg = ''; $st = 'unknown'
        if ($job) { $st = [string]$job.status }
        if ($job -and $job.error) { $ec = [string]$job.error.code; $msg = [string]$job.error.message }
        $dl = Invoke-Api -Method GET -Path "/v1/jobs/$id/result" -Tag 'failed'
        return [pscustomobject]@{
            Ok = $false; Stage = 'job'; Http = $w.Http; ErrCode = $ec
            Message = ("job status={0} code={1} message={2} http={3}" -f $st, $ec, $msg, $w.Http)
            Job = $job; JobId = $id; File = ''; DownloadCode = $dl.Code; DownloadErr = (Get-ErrCode $dl)
        }
    }
    $dl = Invoke-Api -Method GET -Path "/v1/jobs/$id/result" -OutFile $OutName
    return [pscustomobject]@{
        Ok = ($dl.Code -eq 200); Stage = 'download'; Http = $dl.Code; ErrCode = ''
        Message = ("download -> HTTP {0}" -f $dl.Code)
        Job = $job; JobId = $id; File = $OutName; DownloadCode = $dl.Code; DownloadErr = ''
    }
}

# ---------------------------------------------------------------- assertions

function Test-Meta($R, [hashtable]$Expected) {
    $errs = @()
    if (-not $Expected) { return $errs }
    $meta = $null
    if ($R.Job) { $meta = $R.Job.meta }
    foreach ($k in $Expected.Keys) {
        $actual = $null
        if ($meta) { $actual = $meta.$k }
        if ([string]$actual -ne [string]$Expected[$k]) {
            $errs += ("meta.{0}={1} (expected {2})" -f $k, $actual, $Expected[$k])
        }
    }
    return $errs
}

function Assert-Output {
    param(
        [string]$Name, $R,
        [string]$Command = 'check-pdf',
        [string[]]$CheckArgs = @(),
        [string]$Magic = '',
        [hashtable]$Meta = $null,
        [string]$ResultName = ''
    )
    if (-not $R.Ok) { Report $Name $false $R.Message; return }
    $errs = @()
    if ($Magic) {
        $m = Invoke-Helper @('has-magic', $R.File, $Magic)
        if ($m.Code -ne 0) { $errs += $m.Output }
    }
    $h = Invoke-Helper (@($Command, $R.File) + $CheckArgs)
    if ($h.Code -ne 0) { $errs += $h.Output }
    $errs += @(Test-Meta $R $Meta)
    if ($ResultName -and $R.Job -and ([string]$R.Job.result_name -ne $ResultName)) {
        $errs += ("result_name={0} (expected {1})" -f $R.Job.result_name, $ResultName)
    }
    if ($errs.Count -eq 0) { Report $Name $true $h.Output }
    else { Report $Name $false ($errs -join '; ') }
}

# ---------------------------------------------------------------- start

Write-Host ("PDF Toolkit smoke test against {0}" -f $BaseUrl) -ForegroundColor White
if ($script:UseDocker) { Write-Host ("Helper: docker image {0}" -f $DockerImage) }
else { Write-Host ("Helper: local Python ({0})" -f $script:PythonExe) }

Write-Host ("Waiting for the server (up to {0} s, covers a Render cold start)..." -f $ColdStartSec)
$deadline = (Get-Date).AddSeconds($ColdStartSec)
$up = $false
$attempts = 0
while ($true) {
    $attempts++
    $r = Invoke-Api -Method GET -Path '/v1/health' -MaxTime 15 -Tag 'cold'
    if ($r.Code -eq 200) { $up = $true; break }
    if ((Get-Date) -gt $deadline) { break }
    Start-Sleep -Seconds 3
}
if (-not $up) {
    Write-Host ("FAIL  server did not answer /v1/health with 200 within {0} s (last HTTP {1})" -f $ColdStartSec, $r.Code) -ForegroundColor Red
    exit 1
}
Write-Host ("Server is up after {0} attempt(s), {1:N0} s." -f $attempts, $sw.Elapsed.TotalSeconds)

Write-Host 'Generating sample files...'
$h = Invoke-Helper @('samples')
if ($h.Code -ne 0) {
    Write-Host ("Sample generation failed: {0}" -f $h.Output) -ForegroundColor Red
    exit 2
}
Write-Host ("  {0}" -f $h.Output) -ForegroundColor DarkGray

# ---------------------------------------------------------------- health and catalogue

Section 'Health and tool catalogue'

$r = Invoke-Api -Path '/v1/health'
$j = Read-Json $r
Report 'GET /v1/health' (($r.Code -eq 200) -and ($j.status -eq 'ok')) ("HTTP {0}" -f $r.Code)

$r = Invoke-Api -Path '/v1/tools'
$j = Read-Json $r
$names = @()
if ($j -and $j.tools) { $names = @($j.tools | ForEach-Object { [string]$_.name }) }
$wave1 = @('merge', 'split', 'extract-pages', 'remove-pages', 'reorder', 'rotate', 'crop',
    'images-to-pdf', 'pdf-to-images', 'compress', 'protect', 'unlock', 'page-numbers', 'watermark', 'metadata')
$missing = @($wave1 | Where-Object { $names -notcontains $_ })
Report 'GET /v1/tools lists every Wave 1 tool' (($r.Code -eq 200) -and ($missing.Count -eq 0)) ("HTTP {0}; missing: {1}" -f $r.Code, ($missing -join ', '))

$shapeErrs = @()
if ($j -and $j.tools) {
    foreach ($t in $j.tools) {
        foreach ($f in @('name', 'accepts', 'min_files', 'max_files', 'fast')) {
            if ($null -eq $t.PSObject.Properties[$f]) { $shapeErrs += ("{0} lacks {1}" -f $t.name, $f) }
        }
    }
}
if ($j -and $j.limits) {
    foreach ($f in @('max_file_mb', 'max_job_mb', 'job_ttl_min', 'ocr_max_pages')) {
        if ($null -eq $j.limits.PSObject.Properties[$f]) { $shapeErrs += ("limits lacks {0}" -f $f) }
    }
    $script:MaxFileMb = [int]$j.limits.max_file_mb
}
else { $shapeErrs += 'limits object missing' }
Report 'GET /v1/tools response shape (fields, limits)' ($shapeErrs.Count -eq 0) (($shapeErrs -join '; ') + (" [max_file_mb={0}]" -f $script:MaxFileMb))

$fastExpected = @{
    'merge' = $true; 'split' = $false; 'extract-pages' = $true; 'remove-pages' = $true; 'reorder' = $true
    'rotate' = $true; 'crop' = $true; 'images-to-pdf' = $false; 'pdf-to-images' = $false; 'compress' = $false
    'protect' = $true; 'unlock' = $true; 'page-numbers' = $true; 'watermark' = $true; 'metadata' = $false
}
$fastErrs = @()
if ($j -and $j.tools) {
    foreach ($t in $j.tools) {
        $n = [string]$t.name
        if ($fastExpected.ContainsKey($n) -and ([bool]$t.fast -ne $fastExpected[$n])) {
            $fastErrs += ("{0}.fast={1}" -f $n, $t.fast)
        }
    }
}
Report 'fast flags match the API contract' ($fastErrs.Count -eq 0) ($fastErrs -join '; ')
$selftest = @($names | Where-Object { $_ -like 'selftest*' })
if ($selftest.Count -gt 0) {
    Write-Host ("INFO  selftest tools are enabled on this server ({0}); fine locally, disable on Render" -f $selftest.Count) -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------- page tools

Section 'Merge'
$rMerge = Invoke-ToolJob -Tool 'merge' -Files @('a.pdf', 'b.pdf') -OutName 'out_merge.pdf'
$mergeId = $rMerge.JobId
Assert-Output -Name 'merge a.pdf + b.pdf' -R $rMerge -CheckArgs @('--pages', '8', '--widths', '110,120,130,140,150,110,120,130') -Meta @{ pages_out = 8 } -ResultName 'merged.pdf'

$r = Invoke-ToolJob -Tool 'merge' -Files @('locked.pdf', 'a.pdf') -Options '{"passwords":["open-sesame",null]}' -OutName 'out_merge_pw.pdf'
Assert-Output -Name 'merge with passwords list (encrypted + plain)' -R $r -CheckArgs @('--pages', '9', '--plain')

Section 'Split'
$r = Invoke-ToolJob -Tool 'split' -Files @('a.pdf') -Options '{"mode":"ranges","ranges":"1-2,4-5"}' -OutName 'out_split_ranges.zip'
Assert-Output -Name 'split ranges "1-2,4-5" -> zip of 2 PDFs' -R $r -Command 'check-zip' -Magic 'zip' -CheckArgs @('--entries', '2', '--kind', 'pdf', '--pages', '2,2') -ResultName 'a_split.zip'

$r = Invoke-ToolJob -Tool 'split' -Files @('a.pdf') -Options '{"ranges":"2-4"}' -OutName 'out_split_one.pdf'
Assert-Output -Name 'split one range "2-4" -> plain PDF' -R $r -Magic 'pdf' -CheckArgs @('--pages', '3', '--widths', '120,130,140')

$r = Invoke-ToolJob -Tool 'split' -Files @('c.pdf') -Options '{"mode":"every","every":5}' -OutName 'out_split_every.zip'
Assert-Output -Name 'split every 5 (12 pages) -> zip of 3 PDFs' -R $r -Command 'check-zip' -Magic 'zip' -CheckArgs @('--entries', '3', '--kind', 'pdf', '--pages', '5,5,2') -ResultName 'c_split.zip'

Section 'Extract, remove, reorder, rotate, crop'
$r = Invoke-ToolJob -Tool 'extract-pages' -Files @('a.pdf') -Options '{"pages":"2,4-5"}' -OutName 'out_extract.pdf'
Assert-Output -Name 'extract-pages "2,4-5"' -R $r -CheckArgs @('--pages', '3', '--widths', '120,140,150') -Meta @{ pages_in = 5; pages_out = 3 } -ResultName 'a_extracted.pdf'

$r = Invoke-ToolJob -Tool 'remove-pages' -Files @('a.pdf') -Options '{"pages":"1,3"}' -OutName 'out_remove.pdf'
Assert-Output -Name 'remove-pages "1,3"' -R $r -CheckArgs @('--pages', '3', '--widths', '120,140,150') -Meta @{ pages_in = 5; pages_out = 3 } -ResultName 'a_pages_removed.pdf'

$r = Invoke-ToolJob -Tool 'reorder' -Files @('a.pdf') -Options '{"order":"5,4,3,2,1"}' -OutName 'out_reorder_rev.pdf'
Assert-Output -Name 'reorder reverse order' -R $r -CheckArgs @('--pages', '5', '--widths', '150,140,130,120,110') -ResultName 'a_reordered.pdf'

$r = Invoke-ToolJob -Tool 'reorder' -Files @('a.pdf') -Options '{"order":"3,1","drop_missing":true,"rotations":{"1":90}}' -OutName 'out_reorder_drop.pdf'
Assert-Output -Name 'reorder drop_missing + rotations (page organizer)' -R $r -CheckArgs @('--pages', '2', '--widths', '130,110', '--rotations', '0,90') -Meta @{ pages_out = 2 }

$r = Invoke-ToolJob -Tool 'reorder' -Files @('a.pdf') -Options '{"order":"3"}' -OutName 'out_reorder_keep.pdf'
Assert-Output -Name 'reorder without drop_missing keeps the other pages' -R $r -CheckArgs @('--pages', '5', '--widths-start', '130') -Meta @{ pages_out = 5 }

$r = Invoke-ToolJob -Tool 'rotate' -Files @('a.pdf') -Options '{"angle":90,"pages":"1-2"}' -OutName 'out_rotate.pdf'
Assert-Output -Name 'rotate 90 on pages 1-2' -R $r -CheckArgs @('--pages', '5', '--rotations', '90,90,0,0,0') -Meta @{ pages_in = 5; pages_out = 5 } -ResultName 'a_rotated.pdf'

$r = Invoke-ToolJob -Tool 'crop' -Files @('a.pdf') -Options '{"unit":"points","left":10,"top":20}' -OutName 'out_crop.pdf'
Assert-Output -Name 'crop left 10 pt, top 20 pt' -R $r -CheckArgs @('--pages', '5', '--box', '1:100:180', '--box', '5:140:180') -ResultName 'a_cropped.pdf'

Section 'wait=true fast path'
$resp = Submit-Tool -Tool 'rotate' -Files @('a.pdf') -Options '{"angle":-90}' -Wait -OutFile 'out_rotate_wait.pdf'
$metaHdr = Get-Header $resp 'X-Result-Meta'
$mj = $null
try { $mj = $metaHdr | ConvertFrom-Json } catch { $mj = $null }
$cd = Get-Header $resp 'Content-Disposition'
$fastOk = ($resp.Code -eq 200) -and $mj -and ([int]$mj.pages_out -eq 5) -and ($cd -match 'a_rotated\.pdf')
$fastDetail = ("HTTP {0}; X-Result-Meta={1}; Content-Disposition={2}" -f $resp.Code, $metaHdr, $cd)
if ($resp.Code -eq 202) { $fastDetail += ' (got 202: the fast path was not taken)' }
Report 'rotate?wait=true returns 200 + file + X-Result-Meta' $fastOk $fastDetail
$fakeR = [pscustomobject]@{ Ok = ($resp.Code -eq 200); File = 'out_rotate_wait.pdf'; Job = $null; Message = ("HTTP {0}" -f $resp.Code) }
Assert-Output -Name 'rotate?wait=true output is a valid PDF, angle -90' -R $fakeR -Magic 'pdf' -CheckArgs @('--pages', '5', '--rotations', '270,270,270,270,270')

# ---------------------------------------------------------------- images

Section 'images-to-pdf and pdf-to-images'
$r = Invoke-ToolJob -Tool 'images-to-pdf' -Files @('photo1.jpg', 'photo2.png', 'photo3.jpg') -Options '{"page_size":"a4"}' -OutName 'out_img2pdf_multi.pdf'
Assert-Output -Name 'images-to-pdf 3 images, A4' -R $r -CheckArgs @('--pages', '3', '--a4') -Meta @{ pages_out = 3 } -ResultName 'images.pdf'

$r = Invoke-ToolJob -Tool 'images-to-pdf' -Files @('photo1.jpg') -Options '{"page_size":"letter","orientation":"portrait"}' -OutName 'out_img2pdf_one.pdf'
Assert-Output -Name 'images-to-pdf one image, letter portrait' -R $r -CheckArgs @('--pages', '1', '--box', '1:612:792') -ResultName 'photo1.pdf'

$r = Invoke-ToolJob -Tool 'images-to-pdf' -Files @('photo3.jpg') -Options '{"page_size":"fit","quality":"high"}' -OutName 'out_img2pdf_fit.pdf'
Assert-Output -Name 'images-to-pdf fit, quality high' -R $r -CheckArgs @('--pages', '1')

$r = Invoke-ToolJob -Tool 'pdf-to-images' -Files @('a.pdf') -Options '{"format":"png","dpi":72,"pages":"2"}' -OutName 'out_p2i_single.png'
Assert-Output -Name 'pdf-to-images single page -> plain PNG' -R $r -Command 'check-image' -Magic 'png' -CheckArgs @('--format', 'PNG', '--size', '120:200', '--tolerance', '2') -Meta @{ dpi = 72; format = 'png' } -ResultName 'a_page2.png'

$r = Invoke-ToolJob -Tool 'pdf-to-images' -Files @('a.pdf') -Options '{"format":"jpg","dpi":72,"pages":"1-3"}' -OutName 'out_p2i_multi.zip'
Assert-Output -Name 'pdf-to-images pages 1-3 -> zip of 3 JPEGs' -R $r -Command 'check-zip' -Magic 'zip' -CheckArgs @('--entries', '3', '--kind', 'image', '--ext', 'jpg', '--contains', 'page', '--format', 'JPEG') -ResultName 'a_images.zip'

# ---------------------------------------------------------------- compress, protect, unlock

Section 'Compress, protect, unlock'
$r = Invoke-ToolJob -Tool 'compress' -Files @('scan.pdf') -Options '{"level":"ebook"}' -OutName 'out_compress.pdf'
if (-not $r.Ok) { Report 'compress ebook (scan.pdf)' $false $r.Message }
else {
    $m = $r.Job.meta
    $errs = @()
    if ($null -eq $m -or $null -eq $m.input_bytes -or $null -eq $m.output_bytes) { $errs += 'meta lacks input_bytes/output_bytes' }
    elseif ([long]$m.output_bytes -gt [long]$m.input_bytes) { $errs += 'output is bigger than input' }
    if ($null -eq $m -or $null -eq $m.already_optimized) { $errs += 'meta.already_optimized missing' }
    $h = Invoke-Helper @('check-pdf', $r.File, '--pages', '2')
    if ($h.Code -ne 0) { $errs += $h.Output }
    if ([string]$r.Job.result_name -ne 'scan_compressed.pdf') { $errs += ("result_name={0}" -f $r.Job.result_name) }
    $d = ''
    if ($m) { $d = ("{0} -> {1} bytes, saved {2}%, already_optimized={3}" -f $m.input_bytes, $m.output_bytes, $m.saved_percent, $m.already_optimized) }
    if ($errs.Count -eq 0) { Report 'compress ebook (scan.pdf)' $true $d } else { Report 'compress ebook (scan.pdf)' $false (($errs -join '; ') + ' | ' + $d) }
}

$r = Invoke-ToolJob -Tool 'protect' -Files @('a.pdf') -Options '{"password":"Sm0ke-Test_pw","allow_print":true,"allow_copy":false}' -OutName 'out_protect.pdf'
Assert-Output -Name 'protect (AES-256 default) needs the password to open' -R $r -CheckArgs @('--pages', '5', '--encrypted', '--password', 'Sm0ke-Test_pw') -ResultName 'a_protected.pdf'
if ($r.Ok) { Report 'protect meta reports the encryption' ($null -ne $r.Job.meta -and [bool]$r.Job.meta.encryption) ("meta.encryption={0}" -f $r.Job.meta.encryption) }

$r = Invoke-ToolJob -Tool 'unlock' -Files @('locked.pdf') -Options '{"password":"open-sesame"}' -OutName 'out_unlock.pdf'
Assert-Output -Name 'unlock with the right password -> no encryption' -R $r -CheckArgs @('--pages', '4', '--plain') -Meta @{ was_encrypted = $true } -ResultName 'locked_unlocked.pdf'

$r = Invoke-ToolJob -Tool 'rotate' -Files @('locked.pdf') -Options '{"password":"open-sesame"}' -OutName 'out_rotate_locked.pdf'
Assert-Output -Name 'rotate on an encrypted PDF with the password option' -R $r -CheckArgs @('--pages', '4', '--plain', '--rotations', '90,90,90,90')

# ---------------------------------------------------------------- page numbers, watermark, metadata

Section 'Page numbers, watermark, metadata'
$r = Invoke-ToolJob -Tool 'page-numbers' -Files @('a.pdf') -Options '{"format":"page_n_of_total","position":"bottom-center"}' -OutName 'out_pn_all.pdf'
Assert-Output -Name 'page-numbers "Page n of total" on all pages' -R $r -CheckArgs @('--pages', '5', '--text', '1:Page 1 of 5', '--text', '5:Page 5 of 5', '--differs', 'a.pdf') -ResultName 'a_numbered.pdf'

$r = Invoke-ToolJob -Tool 'page-numbers' -Files @('c.pdf') -Options '{"pages":"2-4","start":10,"format":"n_of_total"}' -OutName 'out_pn_range.pdf'
Assert-Output -Name 'page-numbers pages 2-4, start 10 (total = last number)' -R $r -CheckArgs @('--pages', '12', '--text', '2:10 of 12', '--text', '3:11 of 12', '--text', '4:12 of 12', '--no-text', '1:of 12', '--no-text', '5:of 12')

$r = Invoke-ToolJob -Tool 'watermark' -Files @('a.pdf') -Options '{"type":"text","text":"CONFIDENTIAL","opacity":0.4}' -OutName 'out_wm_text.pdf'
Assert-Output -Name 'watermark text (visible change on pages 1 and 3)' -R $r -CheckArgs @('--pages', '5', '--differs', 'a.pdf', '--differs-pages', '1,3') -ResultName 'a_watermarked.pdf'

$r = Invoke-ToolJob -Tool 'watermark' -Files @('logo.png', 'a.pdf') -Options '{"type":"image","scale":40,"opacity":0.6}' -OutName 'out_wm_image.pdf'
Assert-Output -Name 'watermark image (files in any order)' -R $r -CheckArgs @('--pages', '5', '--differs', 'a.pdf', '--differs-pages', '1,5')

$r = Invoke-ToolJob -Tool 'metadata' -Files @('meta.pdf') -Options '{"action":"read"}' -OutName 'out_meta_read.pdf'
Assert-Output -Name 'metadata read (file unchanged)' -R $r -CheckArgs @('--pages', '2', '--meta', 'title=Smoke Title', '--meta', 'author=Smoke Author') -ResultName 'meta_metadata.pdf'
if ($r.Ok) { Report 'metadata read reports current values in meta.metadata' ($null -ne $r.Job.meta -and $r.Job.meta.metadata.title -eq 'Smoke Title') ("meta.metadata.title={0}" -f $r.Job.meta.metadata.title) }

$r = Invoke-ToolJob -Tool 'metadata' -Files @('meta.pdf') -Options '{"action":"edit","title":"New Title","author":"","keywords":"smoke, test"}' -OutName 'out_meta_edit.pdf'
Assert-Output -Name 'metadata edit (set, remove, leave alone)' -R $r -CheckArgs @('--pages', '2', '--meta', 'title=New Title', '--meta', 'keywords=smoke, test', '--meta', 'subject=Smoke Subject', '--no-meta', 'author')

# ---------------------------------------------------------------- error paths

Section 'Error paths'
$r = Submit-Tool -Tool 'does-not-exist' -Files @('a.pdf')
Report 'unknown tool -> 404 unknown_tool' (($r.Code -eq 404) -and ((Get-ErrCode $r) -eq 'unknown_tool')) ("HTTP {0} {1}" -f $r.Code, (Get-ErrCode $r))

$r = Submit-Tool -Tool 'rotate' -Files @('notes.txt')
Report 'text file sent to rotate -> 415 unsupported_type' (($r.Code -eq 415) -and ((Get-ErrCode $r) -eq 'unsupported_type')) ("HTTP {0} {1}" -f $r.Code, (Get-ErrCode $r))

$r = Submit-Tool -Tool 'images-to-pdf' -Files @('a.pdf')
Report 'PDF sent to images-to-pdf -> 415 unsupported_type' (($r.Code -eq 415) -and ((Get-ErrCode $r) -eq 'unsupported_type')) ("HTTP {0} {1}" -f $r.Code, (Get-ErrCode $r))

$r = Invoke-ToolJob -Tool 'unlock' -Files @('locked.pdf') -Options '{"password":"wrong-password"}' -OutName 'out_never.pdf'
Report 'unlock with a wrong password -> wrong_password (job + result 422)' (($r.Stage -eq 'job') -and ($r.ErrCode -eq 'wrong_password') -and ($r.DownloadCode -eq 422) -and ($r.DownloadErr -eq 'wrong_password')) ("{0}; result -> HTTP {1} {2}" -f $r.Message, $r.DownloadCode, $r.DownloadErr)

$r = Invoke-ToolJob -Tool 'unlock' -Files @('locked.pdf') -OutName 'out_never.pdf'
Report 'unlock without a password -> password_required (job + result 422)' (($r.Stage -eq 'job') -and ($r.ErrCode -eq 'password_required') -and ($r.DownloadCode -eq 422) -and ($r.DownloadErr -eq 'password_required')) ("{0}; result -> HTTP {1} {2}" -f $r.Message, $r.DownloadCode, $r.DownloadErr)

if ($SkipBigUpload) {
    Write-Host 'SKIP  file-too-large test (-SkipBigUpload)' -ForegroundColor DarkYellow
}
else {
    $h = Invoke-Helper @('bigfile', 'big_over_limit.pdf', '--over-mb', "$($script:MaxFileMb)")
    if ($h.Code -ne 0) { Report 'file too large -> 413 file_too_large' $false ("could not create the test file: " + $h.Output) }
    else {
        $r = Submit-Tool -Tool 'rotate' -Files @('big_over_limit.pdf')
        $d = ("limit {0} MB; HTTP {1} {2}" -f $script:MaxFileMb, $r.Code, (Get-ErrCode $r))
        if ($r.Code -eq 0) { $d += ' (connection dropped; some proxies reset the connection on oversized uploads)' }
        Report 'file too large -> 413 file_too_large' (($r.Code -eq 413) -and ((Get-ErrCode $r) -eq 'file_too_large')) $d
    }
    Remove-Item -LiteralPath (Join-Path $WorkDir 'big_over_limit.pdf') -Force -ErrorAction SilentlyContinue
}

# a job that was already downloaded (the merge job above) is gone
if ($mergeId) {
    $r = Invoke-Api -Method GET -Path "/v1/jobs/$mergeId/result"
    Report 'second download of the same result -> 410 job_expired' (($r.Code -eq 410) -and ((Get-ErrCode $r) -eq 'job_expired')) ("HTTP {0} {1}" -f $r.Code, (Get-ErrCode $r))
    $r = Invoke-Api -Method GET -Path "/v1/jobs/$mergeId"
    Report 'status of a downloaded job -> 410 job_expired' (($r.Code -eq 410) -and ((Get-ErrCode $r) -eq 'job_expired')) ("HTTP {0} {1}" -f $r.Code, (Get-ErrCode $r))
}
else { Report 'second download of the same result -> 410 job_expired' $false 'no merge job id (merge failed earlier)' }

$ghost = [guid]::NewGuid().ToString('N')
$r = Invoke-Api -Method GET -Path "/v1/jobs/$ghost"
Report 'job that never existed -> 404 job_not_found' (($r.Code -eq 404) -and ((Get-ErrCode $r) -eq 'job_not_found')) ("HTTP {0} {1}" -f $r.Code, (Get-ErrCode $r))

$sub = Submit-Tool -Tool 'split' -Files @('c.pdf') -Options '{"mode":"every","every":2}'
$sj = Read-Json $sub
if ($sub.Code -ne 202 -or -not $sj.job_id) {
    Report 'DELETE /v1/jobs/{id}' $false ("could not create a job: HTTP {0} {1}" -f $sub.Code, (Get-ErrCode $sub))
}
else {
    $delId = [string]$sj.job_id
    $d1 = Invoke-Api -Method DELETE -Path "/v1/jobs/$delId"
    $g = Invoke-Api -Method GET -Path "/v1/jobs/$delId"
    $d2 = Invoke-Api -Method DELETE -Path "/v1/jobs/$delId"
    Report 'DELETE /v1/jobs/{id} -> 204' ($d1.Code -eq 204) ("HTTP {0}" -f $d1.Code)
    Report 'job is gone after DELETE (404 or 410)' (@(404, 410) -contains $g.Code) ("GET -> HTTP {0} {1}" -f $g.Code, (Get-ErrCode $g))
    Report 'DELETE again -> 204' ($d2.Code -eq 204) ("HTTP {0}" -f $d2.Code)
}
$d3 = Invoke-Api -Method DELETE -Path ("/v1/jobs/" + [guid]::NewGuid().ToString('N'))
Report 'DELETE of an unknown job -> 204' ($d3.Code -eq 204) ("HTTP {0}" -f $d3.Code)
$r = Invoke-Api -Path '/v1/health'
Report 'server still healthy after the error tests' ($r.Code -eq 200) ("HTTP {0}" -f $r.Code)

# ---------------------------------------------------------------- summary

Write-Host ''
Write-Host '==============================================' -ForegroundColor Cyan
$total = $script:Pass + $script:Fail
Write-Host ("{0} checks: {1} passed, {2} failed ({3:N0} s)" -f $total, $script:Pass, $script:Fail, $sw.Elapsed.TotalSeconds)
if ($script:Fail -gt 0) {
    Write-Host 'Failed checks:' -ForegroundColor Red
    foreach ($n in $script:FailedNames) { Write-Host ("  - {0}" -f $n) -ForegroundColor Red }
    Write-Host ("Files kept for inspection in {0}" -f $WorkDir)
    exit 1
}
if (-not $KeepFiles) {
    Get-ChildItem -LiteralPath $WorkDir -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host 'ALL CHECKS PASSED' -ForegroundColor Green
exit 0
