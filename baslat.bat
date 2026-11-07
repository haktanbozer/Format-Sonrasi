@echo off
title Format Sonrasi Kurulum Sihirbazi
set "SCRIPT_DIR=%~dp0"
cd /d "%SystemRoot%\System32"

REM 1. Yonetici Yetkisi Kontrolu (net.exe ve fltmc.exe tam yol ile)
"%SystemRoot%\System32\net.exe" session >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :admin_ok

"%SystemRoot%\System32\fltmc.exe" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :admin_ok

echo ========================================================
echo   Format Sonrasi Kurulum Sihirbazi
echo ========================================================
echo [BILGI] Yonetici izinleri isteniyor, lutfen acilan UAC penceresinde 'Evet'i secin...
echo.

set "SCRIPT_PATH=%~f0"
set "SCRIPT_PATH=%SCRIPT_PATH:'=''%"
set "PS_ARGS=%*"
if not defined PS_ARGS goto :elevate_noargs
set "PS_ARGS=%PS_ARGS:'=''%"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "try { Start-Process -FilePath '%SCRIPT_PATH%' -ArgumentList '%PS_ARGS%' -Verb RunAs -ErrorAction Stop } catch { exit 2 }"
goto :elevate_done

:elevate_noargs
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "try { Start-Process -FilePath '%SCRIPT_PATH%' -Verb RunAs -ErrorAction Stop } catch { exit 2 }"

:elevate_done
if %ERRORLEVEL% EQU 2 (
    echo.
    echo [UYARI] Yonetici izni reddedildi veya alinamadi.
    echo Kurulum Sihirbazi sistem ayarlari ve program kurulumlari icin yonetici haklari gerektirir.
    echo.
    pause
    exit /b 1
)
exit /b 0

:admin_ok
cd /d "%SCRIPT_DIR%"
echo ========================================================
echo   Format Sonrasi Kurulum Sihirbazi (Yonetici Modu)
echo ========================================================
echo [BILGI] Yonetici haklari onaylandi.
echo.

set "APP_ARGS=%*"
REM 2. Gelistirici modu: --python bayragi varsa argumanlardan cikar ve dogrudan Python'a gec
if "%1"=="--python" (
    set "APP_ARGS=%APP_ARGS:*--python=%"
    goto :check_python
)

REM 3. Son kullanici icin oncelikli olarak derlenmis EXE calistir (--onedir veya tek dosya)
if exist "%~dp0FormatSonrasiKurulum\FormatSonrasiKurulum.exe" goto :run_onedir_exe
if exist "%~dp0dist\FormatSonrasiKurulum\FormatSonrasiKurulum.exe" goto :run_dist_onedir_exe
if exist "%~dp0FormatSonrasiKurulum.exe" goto :run_exe
if exist "%~dp0dist\FormatSonrasiKurulum.exe" goto :run_dist_exe

:check_python
REM 4. Python Calistirma (py -3 Store tetiklemesini onlemek icin onceliklidir)
set "PY_EXE="
set "PYTHON_EXE="
for /f "delims=" %%I in ('"%SystemRoot%\System32\where.exe" py 2^>nul') do (
    if not defined PY_EXE if /i not "%%~dpI"=="%SCRIPT_DIR%" set "PY_EXE=%%I"
)
for /f "delims=" %%I in ('"%SystemRoot%\System32\where.exe" python 2^>nul') do (
    if not defined PYTHON_EXE if /i not "%%~dpI"=="%SCRIPT_DIR%" set "PYTHON_EXE=%%I"
)

if defined PY_EXE goto :run_py_launcher
if defined PYTHON_EXE goto :run_python_path

set "APPDATA_PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "APPDATA_PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined APPDATA_PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "APPDATA_PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined APPDATA_PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "APPDATA_PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined APPDATA_PY goto :run_python_appdata
if exist "%~dp0FormatSonrasiKurulum.exe" goto :run_exe
if exist "%~dp0dist\FormatSonrasiKurulum.exe" goto :run_dist_exe

goto :not_found

:run_py_launcher
echo [BILGI] Python Launcher (%PY_EXE% -3) ile baslatiliyor...
"%PY_EXE%" -3 main.py %APP_ARGS%
set "APP_EXIT=%ERRORLEVEL%"
if "%APP_EXIT%"=="9009" goto :try_other_py
if "%APP_EXIT%"=="103" goto :try_other_py
goto :handle_exit

:run_python_path
echo [BILGI] Sistem PATH uzerindeki Python (%PYTHON_EXE%) ile baslatiliyor...
"%PYTHON_EXE%" main.py %APP_ARGS%
set "APP_EXIT=%ERRORLEVEL%"
if "%APP_EXIT%"=="9009" goto :try_other_py
if "%APP_EXIT%"=="103" goto :try_other_py
goto :handle_exit

:try_other_py
set "APPDATA_PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "APPDATA_PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined APPDATA_PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "APPDATA_PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined APPDATA_PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "APPDATA_PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined APPDATA_PY goto :run_python_appdata
if exist "%~dp0FormatSonrasiKurulum\FormatSonrasiKurulum.exe" goto :run_onedir_exe
if exist "%~dp0dist\FormatSonrasiKurulum\FormatSonrasiKurulum.exe" goto :run_dist_onedir_exe
if exist "%~dp0FormatSonrasiKurulum.exe" goto :run_exe
if exist "%~dp0dist\FormatSonrasiKurulum.exe" goto :run_dist_exe
goto :not_found

:run_python_appdata
echo [BILGI] AppData altindaki Python ile baslatiliyor (%APPDATA_PY%)...
"%APPDATA_PY%" main.py %APP_ARGS%
set "APP_EXIT=%ERRORLEVEL%"
goto :handle_exit

:run_onedir_exe
echo [BILGI] Hizli FormatSonrasiKurulum\FormatSonrasiKurulum.exe baslatiliyor...
start "" "%~dp0FormatSonrasiKurulum\FormatSonrasiKurulum.exe" %APP_ARGS%
exit /b 0

:run_dist_onedir_exe
echo [BILGI] Hizli dist\FormatSonrasiKurulum\FormatSonrasiKurulum.exe baslatiliyor...
start "" "%~dp0dist\FormatSonrasiKurulum\FormatSonrasiKurulum.exe" %APP_ARGS%
exit /b 0

:run_exe
echo [BILGI] Derlenmis FormatSonrasiKurulum.exe baslatiliyor...
start "" "%~dp0FormatSonrasiKurulum.exe" %APP_ARGS%
exit /b 0

:run_dist_exe
echo [BILGI] Derlenmis dist\FormatSonrasiKurulum.exe baslatiliyor...
start "" "%~dp0dist\FormatSonrasiKurulum.exe" %APP_ARGS%
exit /b 0

:handle_exit
if %APP_EXIT% EQU 0 exit /b 0
echo.
echo [BILGI] Uygulama cikis kodu: %APP_EXIT%
pause
exit /b %APP_EXIT%

:not_found
echo.
echo [HATA] Ne FormatSonrasiKurulum.exe ne de calisir bir Python ortami bulunamadi!
echo Lutfen Python 3.10+ yukleyin veya FormatSonrasiKurulum.exe dosyasini bu klasore kopyalayin.
echo.
pause
exit /b 1
