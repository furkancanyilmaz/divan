@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title DIVAN - Ustalarla Terapi ve Ders

set "APP_VERSION=2026.08.17.5"
set "CORE_VERSION=2026.08.15.1"
set "APP_DIR=%~dp0Sistem_Dosyalari"
set "PYTHON_EXE=%APP_DIR%\python\python.exe"
set "PORT=8778"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Bu dagitim yalniz yerel model kullanir. Windows ortaminda daha once
rem tanimlanmis olabilecek bulut anahtarlarini da bu oturuma tasima.
set "DIVAN_LLM_PROVIDER=lmstudio"
set "DEEPSEEK_API_KEY="
set "OPENAI_API_KEY="
set "ANTHROPIC_API_KEY="
set "LMSTUDIO_API_KEY="

if "%LOCALAPPDATA%"=="" (
  set "DATA_DIR=%USERPROFILE%\Documents\Divan-Anne"
  set "LEGACY_DATA_DIR=%USERPROFILE%\Documents\Divan-Temiz-2026.07.25.5"
) else (
  set "DATA_DIR=%LOCALAPPDATA%\Divan-Anne"
  set "LEGACY_DATA_DIR=%LOCALAPPDATA%\Divan-Temiz-2026.07.25.5"
)
set "DIVAN_DB_PATH=%DATA_DIR%\freud.db"
set "LEGACY_DB_PATH=%LEGACY_DATA_DIR%\freud.db"

if not exist "%APP_DIR%\server.py" (
  echo.
  echo Divan'in sistem dosyalari bulunamadi.
  echo ZIP dosyasina sag tiklayip "Tumunu ayikla" secenegini kullanin.
  echo Ardindan ayiklanan klasordeki DIVAN_BASLAT.bat dosyasini acin.
  echo.
  pause
  exit /b 1
)

if not exist "%APP_DIR%\index.html" (
  echo.
  echo Divan'in arayuz dosyasi bulunamadi.
  echo Paketi yeniden indirin ve tum dosyalari birlikte ayiklayin.
  echo.
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo.
  echo Divan'in tasinabilir calisma ortami eksik.
  echo ZIP dosyasini yeniden "Tumunu ayikla" ile cikarin.
  echo.
  pause
  exit /b 1
)

if not exist "%DATA_DIR%" mkdir "%DATA_DIR%" 2>nul
if not exist "%DATA_DIR%" (
  echo.
  echo Divan veri klasorunu olusturamadi:
  echo %DATA_DIR%
  echo.
  pause
  exit /b 1
)

> "%DATA_DIR%\divan-yazma-testi.tmp" echo tamam
if errorlevel 1 (
  echo.
  echo Divan veri klasorune yazamiyor:
  echo %DATA_DIR%
  echo.
  pause
  exit /b 1
)
del /q "%DATA_DIR%\divan-yazma-testi.tmp" >nul 2>nul

rem Yalniz bu Windows paketinin ayni surumu zaten aciksa onu kullan.
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -TimeoutSec 2 'http://127.0.0.1:8778/api/settings'; if ($r.version -eq '%CORE_VERSION%') { Start-Process 'http://127.0.0.1:8778/'; exit 0 }; exit 2 } catch { exit 1 }" >nul 2>nul
set "SERVER_CHECK=%ERRORLEVEL%"
if "%SERVER_CHECK%"=="0" exit /b 0

if "%SERVER_CHECK%"=="2" (
  echo.
  echo 8778 numarali baglanti noktasinda baska bir Divan surumu acik.
  echo Eski Divan'in siyah penceresini kapatip yeniden deneyin.
  echo.
  pause
  exit /b 1
)

rem Veri klasoru surumden bagimsizdir. Onceki temiz pakette olusan yerel
rem kayitlari yalniz ilk acilista SQLite'in backup API'siyle gecici dosyaya
rem tasir; butunluk denetiminden sonra ayni klasorde atomik olarak kurar.
set "MIGRATION_TMP=%DATA_DIR%\freud-migration.tmp.db"
set "CORRUPT_FOUND="

if exist "%DIVAN_DB_PATH%" (
  "%PYTHON_EXE%" -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); r=c.execute('PRAGMA integrity_check').fetchone(); c.close(); sys.exit(0 if r and r[0]=='ok' else 2)" "%DIVAN_DB_PATH%" >nul 2>nul
  if errorlevel 1 (
    call :QUARANTINE_CORRUPT_DB
    if errorlevel 1 exit /b 1
  )
)

if exist "%DIVAN_DB_PATH%" goto START_DIVAN
if not exist "%LEGACY_DB_PATH%" goto NO_LEGACY_DB

echo Onceki Divan kayitlari guvenli veri klasorune tasiniyor...
if exist "%MIGRATION_TMP%" del /q "%MIGRATION_TMP%" >nul 2>nul
if exist "%MIGRATION_TMP%" goto MIGRATION_FAILED
"%PYTHON_EXE%" -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); ok=d.execute('PRAGMA integrity_check').fetchone()[0]; d.close(); s.close(); sys.exit(0 if ok=='ok' else 2)" "%LEGACY_DB_PATH%" "%MIGRATION_TMP%"
if errorlevel 1 goto MIGRATION_FAILED
move /Y "%MIGRATION_TMP%" "%DIVAN_DB_PATH%" >nul
if errorlevel 1 goto MIGRATION_FAILED
goto START_DIVAN

:NO_LEGACY_DB
if not defined CORRUPT_FOUND goto START_DIVAN
echo.
echo Bozuk Divan veritabani korumaya alindi; yeniden kurulabilecek eski
echo temiz paket veritabani bulunamadi. Korunan dosyayi silmeyin:
echo %QUARANTINE_DB%
echo.
pause
exit /b 1

:MIGRATION_FAILED
if exist "%MIGRATION_TMP%" del /q "%MIGRATION_TMP%" >nul 2>nul
echo.
echo Onceki Divan kayitlari tasinamadi. Eski dosya yerinde korundu:
echo %LEGACY_DB_PATH%
echo.
pause
exit /b 1

:START_DIVAN
echo.
echo Divan %APP_VERSION% temiz paket aciliyor...
echo Tarayici otomatik acilacak.
echo Bu siyah pencereyi Divan'i kullanirken acik tutun.
echo.

pushd "%APP_DIR%"
"%PYTHON_EXE%" -u server.py
set "DIVAN_EXIT=%ERRORLEVEL%"
popd

if not "%DIVAN_EXIT%"=="0" (
  echo.
  echo Divan baslatilamadi.
  echo Lutfen yukaridaki hata metninin fotografini cekin.
  echo.
  pause
)

endlocal & exit /b %DIVAN_EXIT%

:QUARANTINE_CORRUPT_DB
for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "CORRUPT_STAMP=%%I"
if not defined CORRUPT_STAMP set "CORRUPT_STAMP=%RANDOM%-%RANDOM%"
set "QUARANTINE_DB=%DATA_DIR%\freud-%CORRUPT_STAMP%-%RANDOM%.bozuk"
move /Y "%DIVAN_DB_PATH%" "%QUARANTINE_DB%" >nul
if errorlevel 1 (
  echo.
  echo Bozuk Divan veritabani korumaya alinamadi:
  echo %DIVAN_DB_PATH%
  echo.
  pause
  exit /b 1
)
if exist "%DIVAN_DB_PATH%-wal" move /Y "%DIVAN_DB_PATH%-wal" "%QUARANTINE_DB%-wal" >nul
if exist "%DIVAN_DB_PATH%-shm" move /Y "%DIVAN_DB_PATH%-shm" "%QUARANTINE_DB%-shm" >nul
set "CORRUPT_FOUND=1"
echo Bozuk veritabani silinmedi; korumaya alindi:
echo %QUARANTINE_DB%
exit /b 0
