$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Git no pudo completar: git $($GitArgs -join ' ')"
    }
}

$sharedDataFiles = @(
    "escenas.json"
    "banco_escenas.json"
    "proyectos.json"
    "espacio_laberintos.json"
)

function Backup-SharedData {
    $existingFiles = @($sharedDataFiles | Where-Object {
        Test-Path -LiteralPath (Join-Path $repo $_)
    })
    if ($existingFiles.Count -eq 0) {
        return $null
    }

    $backupRoot = Join-Path $repo "backups\actualizaciones"
    $backupPath = Join-Path $backupRoot (Get-Date -Format "yyyy-MM-dd_HH-mm-ss")
    New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
    foreach ($file in $existingFiles) {
        Copy-Item -LiteralPath (Join-Path $repo $file) -Destination (Join-Path $backupPath $file)
    }
    return $backupPath
}

function Assert-SharedData {
    foreach ($file in $sharedDataFiles) {
        $path = Join-Path $repo $file
        if (-not (Test-Path -LiteralPath $path)) {
            throw "La version descargada no contiene $file."
        }

        try {
            Get-Content -LiteralPath $path -Raw | ConvertFrom-Json | Out-Null
        }
        catch {
            throw "La version descargada de $file no contiene JSON valido."
        }
    }
}

function Show-SharedDataSummary {
    $scenes = Get-Content -LiteralPath (Join-Path $repo "escenas.json") -Raw | ConvertFrom-Json
    $bank = Get-Content -LiteralPath (Join-Path $repo "banco_escenas.json") -Raw | ConvertFrom-Json
    $projects = Get-Content -LiteralPath (Join-Path $repo "proyectos.json") -Raw | ConvertFrom-Json
    $space = Get-Content -LiteralPath (Join-Path $repo "espacio_laberintos.json") -Raw | ConvertFrom-Json

    Write-Host "`nContenido compartido actualizado:" -ForegroundColor Cyan
    Write-Host "  Escenas del proyecto: $(@($scenes.orden).Count)"
    Write-Host "  Escenas disponibles en el banco: $(@($bank.orden).Count)"
    Write-Host "  Proyectos / obras: $(@($projects.orden).Count)"
    Write-Host "  Espacio Laberintos: $($space.rows)x$($space.cols), $(@($space.placements.PSObject.Properties).Count) lamparas ubicadas"
}

try {
    Write-Host "Cierra el tablero antes de actualizar." -ForegroundColor Yellow
    $answer = Read-Host "El tablero esta cerrado? (S/N)"
    if ($answer -notmatch '^[sS]$') {
        Write-Host "Operacion cancelada. Cierra el tablero e intenta nuevamente."
        exit 0
    }

    $sharedBackup = Backup-SharedData
    if ($null -ne $sharedBackup) {
        Write-Host "Respaldo previo de escenas y proyectos: $sharedBackup" -ForegroundColor DarkGray
    }

    $changes = @(& git status --porcelain)
    if ($changes.Count -gt 0) {
        $backupName = "Actualizacion automatica " + (Get-Date -Format "yyyy-MM-dd_HH-mm-ss")
        Write-Host "Guardando temporalmente los cambios locales..." -ForegroundColor Yellow
        Invoke-Git stash push --include-untracked -m $backupName
    }

    Invoke-Git fetch origin
    Invoke-Git switch main
    Invoke-Git pull --ff-only origin main
    Assert-SharedData

    $python = Join-Path $repo ".venv\Scripts\python.exe"
    if (Test-Path $python) {
        Write-Host "Actualizando dependencias..." -ForegroundColor Cyan
        & $python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudieron actualizar las dependencias."
        }
    }
    else {
        Write-Host "No se encontro el entorno de Python. Ejecuta la instalacion inicial con Python 3.11.16." -ForegroundColor Yellow
    }

    $version = (& git rev-parse --short HEAD).Trim()
    Write-Host "`nTablero actualizado correctamente. Version: $version" -ForegroundColor Green
    Show-SharedDataSummary
    Write-Host "Las escenas y proyectos de MAIN ya estan disponibles en esta computadora." -ForegroundColor Green
    Write-Host "Las IP y configuraciones locales ignoradas por Git se conservaron."
    if ($changes.Count -gt 0) {
        Write-Host "Se creo un respaldo temporal de los cambios locales anteriores." -ForegroundColor Yellow
    }
}
catch {
    Write-Host "`nNo se pudo actualizar el tablero:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
