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

function Assert-SharedData {
    foreach ($file in $sharedDataFiles) {
        $path = Join-Path $repo $file
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Falta el archivo compartido del espectaculo: $file"
        }

        try {
            Get-Content -LiteralPath $path -Raw | ConvertFrom-Json | Out-Null
        }
        catch {
            throw "El archivo $file no contiene JSON valido. Corrigelo antes de publicar MAIN."
        }

        & git ls-files --error-unmatch -- $file *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "El archivo $file no esta incluido en Git. No se publicara una version incompleta."
        }
    }
}

try {
    $branch = (& git branch --show-current).Trim()
    if ($branch -ne "dev") {
        throw "Debes iniciar desde la rama dev. Rama actual: $branch"
    }

    Assert-SharedData

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

    foreach ($file in $sharedDataFiles) {
        $devObject = (& git rev-parse "dev:$file").Trim()
        $mainObject = (& git rev-parse "HEAD:$file").Trim()
        if ($devObject -ne $mainObject) {
            throw "MAIN no contiene la misma version de $file que DEV."
        }
    }

    Invoke-Git push origin main

    $version = (& git rev-parse --short HEAD).Trim()
    Invoke-Git switch dev

    Write-Host "`nMAIN publicada correctamente. Version: $version" -ForegroundColor Green
    Write-Host "La version estable incluye escenas, banco, proyectos y Espacio Laberintos." -ForegroundColor Green
    Write-Host "Tu amigo ya puede ejecutar Actualizar_TABLERO.cmd."
}
catch {
    Write-Host "`nNo se pudo crear la version estable:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "No hagas otros cambios; revisa el mensaje antes de continuar." -ForegroundColor Yellow
    exit 1
}
