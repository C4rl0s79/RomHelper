# Buduje paczkę źródłową chd_buddy dla Linuksa: dist\chd_buddy-<wersja>-linux.zip
#
# W ZIP-ie nie ma binarki — są źródła, install.sh (venv + zależności),
# run.sh / cli.sh i DEPS.md z pakietami systemowymi per dystrybucja.
#
#   .\build_linux.ps1
#   .\build_linux.ps1 -OutDir D:\wydania
#
# Skrypty .sh zapisujemy z końcami linii LF i bitem wykonywalnym (0755) —
# inaczej po rozpakowaniu trzeba by robić `chmod +x` i `dos2unix`.
[CmdletBinding()]
param(
    [string]$OutDir = "dist"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# --- wersja z chd_buddy/__init__.py -----------------------------------------

$initPath = Join-Path $PSScriptRoot "chd_buddy\__init__.py"
$versionLine = Select-String -LiteralPath $initPath -Pattern '^__version__\s*=\s*"([^"]+)"'
if (-not $versionLine) { throw "Nie znalazłem __version__ w $initPath" }
$version = $versionLine.Matches[0].Groups[1].Value
$name = "chd_buddy-$version"
Write-Host "chd_buddy $version -> paczka linuksowa" -ForegroundColor Cyan

# --- co pakujemy ------------------------------------------------------------

# Katalogi kopiowane w całości (bez śmieci wymienionych w $excludeDirs).
$sourceDirs = @("chd_buddy", "assets", "tests")
$excludeDirs = @("__pycache__", ".pytest_cache", ".venv", "build", "dist",
                 "libretro_cache", "Cache")
# Pliki z korzenia repozytorium.
$rootFiles = @("README.md", "CHANGELOG.md", "pyproject.toml",
               "bios_manifest.json")
# Zawartość packaging\linux trafia do korzenia archiwum — install.sh zakłada,
# że leży obok katalogu chd_buddy.
$linuxDir = Join-Path $PSScriptRoot "packaging\linux"

foreach ($d in $sourceDirs) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $d))) {
        throw "Brak katalogu $d"
    }
}
if (-not (Test-Path -LiteralPath $linuxDir)) { throw "Brak packaging\linux" }

# --- lista wpisów: ścieżka w archiwum -> plik źródłowy -----------------------

$entries = [ordered]@{}

function Add-Tree([string]$dirName) {
    $root = Join-Path $PSScriptRoot $dirName
    Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($PSScriptRoot.Length).TrimStart('\')
        $parts = $rel -split '\\'
        foreach ($part in $parts) {
            if ($excludeDirs -contains $part) { return }
        }
        if ($_.Extension -in @(".pyc", ".pyo", ".log", ".bak")) { return }
        $entries[($rel -replace '\\', '/')] = $_.FullName
    }
}

foreach ($d in $sourceDirs) { Add-Tree $d }

foreach ($f in $rootFiles) {
    $p = Join-Path $PSScriptRoot $f
    if (Test-Path -LiteralPath $p) { $entries[$f] = $p }
    else { Write-Warning "pomijam brakujący $f" }
}

Get-ChildItem -LiteralPath $linuxDir -File | ForEach-Object {
    $entries[$_.Name] = $_.FullName
}

Write-Host ("plików: {0}" -f $entries.Count)

# --- zapis ZIP-a ------------------------------------------------------------

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}
$zipPath = Join-Path (Resolve-Path -LiteralPath $OutDir) "$name-linux.zip"
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

# Uprawnienia unixowe siedzą w górnych 16 bitach ExternalAttributes.
$modeExec = [Convert]::ToInt32("100755", 8) -shl 16
$modeFile = [Convert]::ToInt32("100644", 8) -shl 16

$zip = [System.IO.Compression.ZipFile]::Open(
    $zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($rel in $entries.Keys) {
        $src = $entries[$rel]
        $entryName = "$name/$rel"
        $entry = $zip.CreateEntry(
            $entryName, [System.IO.Compression.CompressionLevel]::Optimal)
        $isShell = $rel -like "*.sh"
        $entry.ExternalAttributes = if ($isShell) { $modeExec } else { $modeFile }
        $out = $entry.Open()
        try {
            if ($isShell) {
                # LF: sh nie strawi `\r` na końcu shebanga ani warunków
                $text = [IO.File]::ReadAllText($src) -replace "`r`n", "`n"
                $bytes = New-Object byte[] 0
                $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
            } else {
                $bytes = [IO.File]::ReadAllBytes($src)
            }
            $out.Write($bytes, 0, $bytes.Length)
        } finally { $out.Dispose() }
    }
} finally { $zip.Dispose() }

$sizeMb = [Math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 2)
Write-Host "`nGotowe: $zipPath ($sizeMb MB)" -ForegroundColor Green
Write-Host "Na Linuksie:  unzip $name-linux.zip && cd $name && ./install.sh" -ForegroundColor DarkGray
