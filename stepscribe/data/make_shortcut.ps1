# stepscribe launcher helper: creates, or reads the description of, a Windows shortcut (.lnk).
# Called by `stepscribe shortcut` with a fixed argument list; nothing is built from strings.
param(
    [Parameter(Mandatory = $true)][ValidateSet('create', 'read')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$LinkPath,
    [string]$Target = '',
    [string]$WorkDir = '',
    [string]$Icon = '',
    [string]$Description = '',
    [int]$WindowStyle = 1
)
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
if ($Mode -eq 'read') {
    if (Test-Path -LiteralPath $LinkPath) { $shell.CreateShortcut($LinkPath).Description }
    exit 0
}
$link = $shell.CreateShortcut($LinkPath)
$link.TargetPath = $Target
$link.WorkingDirectory = $WorkDir
if ($Icon) { $link.IconLocation = $Icon }
$link.Description = $Description
$link.WindowStyle = $WindowStyle
$link.Save()
