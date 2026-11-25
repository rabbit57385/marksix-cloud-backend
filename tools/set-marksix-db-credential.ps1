# Store the MarkSix external database URL using Windows DPAPI (current user).
# Input is masked and never used as a shell argument. No database connection.
$ErrorActionPreference = 'Stop'
$credentialDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'MarkSix\credentials'
$credentialPath = Join-Path $credentialDirectory 'production-db-url.dpapi'
$secret = Read-Host 'Paste the MarkSix Render External Database URL (masked)' -AsSecureString
try {
    if ($secret.Length -eq 0) { throw 'No credential was entered.' }
    $encrypted = ConvertFrom-SecureString -SecureString $secret
    New-Item -ItemType Directory -Path $credentialDirectory -Force | Out-Null
    [IO.File]::WriteAllText($credentialPath, $encrypted, [Text.Encoding]::ASCII)
    Write-Host 'MarkSix credential saved with Windows DPAPI. No database connection was made.'
} finally {
    $secret.Dispose()
    Remove-Variable encrypted -ErrorAction SilentlyContinue
}
