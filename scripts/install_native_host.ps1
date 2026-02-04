param(
    [string]$ManifestPath = "C:\\Workspace\\rss-opml\\native_host\\feedly_ai_overlay.json"
)

if (-not (Test-Path $ManifestPath)) {
    Write-Error "Manifest not found: $ManifestPath"
    exit 1
}

$regPath = "HKCU:\\Software\\Google\\Chrome\\NativeMessagingHosts"
$hostName = "feedly.ai.overlay"

if (-not (Test-Path $regPath)) {
    New-Item -Path $regPath -Force | Out-Null
}

New-Item -Path (Join-Path $regPath $hostName) -Force | Out-Null
Set-ItemProperty -Path (Join-Path $regPath $hostName) -Name "(default)" -Value $ManifestPath

Write-Host "Registered native host: $hostName"
Write-Host "Manifest path: $ManifestPath"
Write-Host "Reminder: Update allowed_origins with your extension ID in the manifest."
