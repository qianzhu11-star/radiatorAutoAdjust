$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$shell = New-Object -ComObject WScript.Shell
$folders = @(
    [Environment]::GetFolderPath('Desktop'),
    [Environment]::GetFolderPath('CommonDesktopDirectory'),
    [Environment]::GetFolderPath('StartMenu'),
    [Environment]::GetFolderPath('CommonStartMenu')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
$items = @()
foreach ($folder in $folders) {
    $links = Get-ChildItem -LiteralPath $folder -Filter '*.lnk' -File -Recurse -ErrorAction SilentlyContinue
    foreach ($link in $links) {
        try {
            $shortcut = $shell.CreateShortcut($link.FullName)
            if ($shortcut.TargetPath) {
                $items += [PSCustomObject]@{ name=$link.BaseName; target=$shortcut.TargetPath }
            }
        } catch { }
    }
}
ConvertTo-Json -InputObject $items -Compress -Depth 3
