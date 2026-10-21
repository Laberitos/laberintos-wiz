@echo off
setlocal

set "REPO="

if exist "%~dp0tablero\main.py" (
    set "REPO=%~dp0"
    goto :repo_encontrado
)

if exist "%~dp0laberintos-wiz\tablero\main.py" (
    set "REPO=%~dp0laberintos-wiz\"
    goto :repo_encontrado
)

if exist "C:\Laberintos\laberintos-wiz\tablero\main.py" (
    set "REPO=C:\Laberintos\laberintos-wiz\"
    goto :repo_encontrado
)

if exist "%USERPROFILE%\Documents\Laberintos\laberintos-wiz\tablero\main.py" (
    set "REPO=%USERPROFILE%\Documents\Laberintos\laberintos-wiz\"
    goto :repo_encontrado
)

if exist "%USERPROFILE%\Documents\Proyecto_Laberintos_Wiz\Laberintos\tablero\main.py" (
    set "REPO=%USERPROFILE%\Documents\Proyecto_Laberintos_Wiz\Laberintos\"
    goto :repo_encontrado
)

echo.
echo No se encontro la instalacion local del Tablero Laberintos.
echo.
echo Ubicacion recomendada:
echo C:\Laberintos\laberintos-wiz
echo.
echo Primero instala o clona el proyecto siguiendo el manual.
pause
exit /b 1

:repo_encontrado
if not exist "%REPO%.venv\Scripts\python.exe" goto :sin_entorno

pushd "%REPO%"
"%REPO%.venv\Scripts\python.exe" -m tablero.main
set "CODIGO_SALIDA=%ERRORLEVEL%"
popd

if not "%CODIGO_SALIDA%"=="0" (
    echo.
    echo El tablero se cerro con un error. Revisa el mensaje anterior.
    pause
)

exit /b %CODIGO_SALIDA%

:sin_entorno
echo.
echo Se encontro el proyecto en:
echo %REPO%
echo.
echo Pero falta el entorno de Python 3.11.16.
echo Sigue la instalacion inicial indicada en el manual.
pause
exit /b 1
