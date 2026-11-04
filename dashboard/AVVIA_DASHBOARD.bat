@echo off
rem Avvia su questa macchina: esportazione delle sessioni (finestra ridotta) + dashboard + browser.
rem Funziona uguale su manas e su dedalo. Chiudere le due finestre per fermare tutto.
set PY=
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (where py >nul 2>nul && set PY=py)
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
  echo Python non trovato: installalo da python.org spuntando "Add python.exe to PATH".
  pause
  exit /b 1
)
start "Esportazione sessioni" /min %PY% "%~dp0dashboard.py" --esporta --ogni 60
start "" http://127.0.0.1:8765
%PY% "%~dp0dashboard.py"
pause
