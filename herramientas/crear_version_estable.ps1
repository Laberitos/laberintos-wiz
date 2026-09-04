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
    $branch = (& git branch --show-current).Trim()
    if ($branch -ne "dev") {
        throw "Debes iniciar desde la rama dev. Rama actual: $branch"
    }

    if (@(& git status --porcelain).Count -gt 0) {
        throw "Hay cambios sin publicar. Ejecuta primero Publicar_DEV.cmd."
    }

    Invoke-Git fetch origin
    $localDev = (& git rev-parse dev).Trim()
    $remoteDev = (& git rev-parse origin/dev).Trim()
    if ($localDev -ne $remoteDev) {
        throw "DEV local y GitHub no coinciden. Ejecuta primero Publicar_DEV.cmd."
    }

    $answer = Read-Host "Publicar la version validada de DEV en MAIN? (S/N)"
    if ($answer -notmatch '^[sS]$') {
        Write-Host "Operacion cancelada. No se modifico MAIN." -ForegroundColor Yellow
        exit 0
    }

    Invoke-Git switch main
    Invoke-Git pull --ff-only origin main

    $releaseMessage = "Publica version estable " + (Get-Date -Format "yyyy-MM-dd HH:mm")
    Invoke-Git merge --no-ff dev -m $releaseMessage
    Invoke-Git push origin main

    $version = (& git rev-parse --short HEAD).Trim()
    Invoke-Git switch dev

    Write-Host "`nMAIN publicada correctamente. Version: $version" -ForegroundColor Green
    Write-Host "Tu amigo ya puede ejecutar Actualizar_TABLERO.cmd."
}
catch {
    Write-Host "`nNo se pudo crear la version estable:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "No hagas otros cambios; revisa el mensaje antes de continuar." -ForegroundColor Yellow
    exit 1
}
