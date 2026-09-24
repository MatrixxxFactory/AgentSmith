@echo off
chcp 65001 >nul
title Agent Smith
cd /d "%~dp0"

echo.
echo  ==========================================
echo    Agent Smith - KI-Telefonagent
echo  ==========================================
echo.
echo  Welcher Betrieb soll antworten?
echo.

set /a nr=0
for %%f in (profile\*.yaml) do (
    set "datei=%%~nf"
    call :eintrag
)
echo.
set /p wahl="  Nummer eingeben und Enter druecken [1]: "
if "%wahl%"=="" set wahl=1
call set "SMITH_PROFIL=%%profil_%wahl%%%"
if "%SMITH_PROFIL%"=="" (
    echo  Ungueltige Auswahl.
    pause
    exit /b 1
)

echo.
echo  Starte %SMITH_PROFIL% ...
echo  Gleich oeffnet sich der Browser. Dort auf "Start" klicken und
echo  das Mikrofon erlauben. Zum Beenden dieses Fenster schliessen.
echo.

rem Projektadresse aus .env.local: wss://agent-smith-xyz.livekit.cloud -> d_agent-smith-xyz
set "projekt="
for /f "tokens=1,* delims==" %%a in ('findstr /b "LIVEKIT_URL=" .env.local 2^>nul') do set "projekt=%%b"
if not defined projekt (
    echo  .env.local fehlt oder enthaelt kein LIVEKIT_URL - bitte zuerst bei LiveKit anmelden.
    pause
    exit /b 1
)
set projekt=%projekt:"=%
set "projekt=%projekt:wss://=%"
set "projekt=%projekt:.livekit.cloud=%"
set "konsole=https://cloud.livekit.io/projects/d_%projekt%/agents/console?agentName=agent-smith&autoStart=true"

rem Browser erst oeffnen, wenn der Agent bei LiveKit angemeldet ist
start "" /b cmd /c "timeout /t 12 /nobreak >nul & start "" "%konsole%""

lk agent dev
pause
exit /b 0

:eintrag
if "%datei:~0,1%"=="_" exit /b 0
set /a nr+=1
set "profil_%nr%=%datei%"
echo    %nr%^) %datei%
exit /b 0
