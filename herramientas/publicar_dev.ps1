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
        throw "Debes estar en la rama dev. Rama actual: $branch"
    }

    $changes = @(& git status --short)
    if ($changes.Count -gt 0) {
        Write-Host "`nCambios que se publicaran en dev:" -ForegroundColor Cyan
        $changes | ForEach-Object { Write-Host $_ }

        $answer = Read-Host "`nRevisaste la lista y deseas continuar? (S/N)"
        if ($answer -notmatch '^[sS]$') {
            Write-Host "Operacion cancelada. No se modifico Git." -ForegroundColor Yellow
            exit 0
        }

        $message = Read-Host "Describe brevemente esta actualizacion"
        if ([string]::IsNullOrWhiteSpace($message)) {
            throw "La descripcion no puede quedar vacia."
        }

        Invoke-Git add --all
        Invoke-Git diff --cached --check
        Invoke-Git commit -m $message
    }
    else {
        Write-Host "No hay cambios locales pendientes." -ForegroundColor Yellow
    }

    Write-Host "`nSincronizando dev con GitHub..." -ForegroundColor Cyan
    Invoke-Git pull --rebase origin dev
    Invoke-Git push origin dev

    $version = (& git rev-parse --short HEAD).Trim()
    Write-Host "`nDEV publicada correctamente. Version: $version" -ForegroundColor Green
    Write-Host "Cuando la validacion termine, usa Crear_VERSION_ESTABLE.cmd."
}
catch {
    Write-Host "`nNo se pudo publicar DEV:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
