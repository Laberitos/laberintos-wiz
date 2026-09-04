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

try {
    Write-Host "Cierra el tablero antes de actualizar." -ForegroundColor Yellow
    $answer = Read-Host "El tablero esta cerrado? (S/N)"
    if ($answer -notmatch '^[sS]$') {
        Write-Host "Operacion cancelada. Cierra el tablero e intenta nuevamente."
        exit 0
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
