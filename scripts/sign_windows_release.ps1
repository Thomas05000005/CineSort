param(
  [Parameter(Mandatory = $true)]
  [string[]]$Paths
)

$ErrorActionPreference = "Stop"

function Get-SigntoolPath {
  if ($env:SIGNTOOL_PATH -and (Test-Path $env:SIGNTOOL_PATH)) {
    return $env:SIGNTOOL_PATH
  }

  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }

  $roots = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
    "${env:ProgramFiles}\Windows Kits\10\bin"
  )
  foreach ($root in $roots) {
    if (-not (Test-Path $root)) {
      continue
    }
    $candidate = Get-ChildItem -Path $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      Select-Object -First 1
    if ($candidate) {
      return $candidate.FullName
    }
  }

  return $null
}

$certBase64 = [string]($env:WINDOWS_CODESIGN_CERT_BASE64 ?? "")
$certPassword = [string]($env:WINDOWS_CODESIGN_CERT_PASSWORD ?? "")
$timestampUrl = [string]($env:WINDOWS_CODESIGN_TIMESTAMP_URL ?? "http://timestamp.digicert.com")

if ([string]::IsNullOrWhiteSpace($certBase64)) {
  Write-Host "[INFO] Signature optionnelle ignoree: WINDOWS_CODESIGN_CERT_BASE64 absent."
  exit 0
}

if ([string]::IsNullOrWhiteSpace($certPassword)) {
  throw "WINDOWS_CODESIGN_CERT_PASSWORD manquant alors qu'un certificat de signature est fourni."
}

$signtool = Get-SigntoolPath
if (-not $signtool) {
  throw "signtool.exe introuvable alors que la signature optionnelle est demandee."
}

$resolvedPaths = @()
foreach ($rawPath in $Paths) {
  if ([string]::IsNullOrWhiteSpace($rawPath)) {
    continue
  }
  $resolved = Resolve-Path -Path $rawPath -ErrorAction SilentlyContinue
  if (-not $resolved) {
    throw "Artefact a signer introuvable: $rawPath"
  }
  $resolvedPaths += [string]$resolved.Path
}

if ($resolvedPaths.Count -eq 0) {
  throw "Aucun artefact a signer n'a ete fourni."
}

$tempPfx = Join-Path $env:RUNNER_TEMP "cinesort_codesign.pfx"
try {
  [IO.File]::WriteAllBytes($tempPfx, [Convert]::FromBase64String($certBase64))
  foreach ($artifactPath in $resolvedPaths) {
    Write-Host "[INFO] Signature SHA256: $artifactPath"
    & $signtool sign `
      /fd SHA256 `
      /td SHA256 `
      /tr $timestampUrl `
      /f $tempPfx `
      /p $certPassword `
      $artifactPath
    if ($LASTEXITCODE -ne 0) {
      throw "Echec de signature pour $artifactPath"
    }
  }
}
finally {
  if (Test-Path $tempPfx) {
    Remove-Item -Force $tempPfx
  }
}

Write-Host "[INFO] Signature optionnelle terminee."
