param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & $Python -m pip install --no-compile --target (Join-Path $PSScriptRoot '.deps') -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    $pythonPath = (& $Python -c 'import sys; print(sys.executable)').Trim()
    $pythonwPath = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonwPath)) { throw 'pythonw.exe not found' }
    $pythonwPath | Set-Content -LiteralPath (Join-Path $PSScriptRoot '.pythonw-path') -Encoding Unicode
    Write-Host 'Setup complete. Double-click start.vbs.'
} finally {
    Pop-Location
}
