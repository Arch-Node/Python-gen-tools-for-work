@echo off
REM Docker to Podman shim for Windows
REM This batch file redirects docker commands to podman running in podman-machine-default WSL distro

setlocal enabledelayedexpansion
set PODMAN_DISTRO=podman-machine-default

REM Try to run podman via WSL
wsl.exe -d !PODMAN_DISTRO! podman %*
set ERRORLEVEL_VAL=%ERRORLEVEL%

endlocal & exit /b %ERRORLEVEL_VAL%
