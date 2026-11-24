@echo off
REM ===========================================================================
REM Crea ExoplanetSearcher.exe per Windows 11 (da fare UNA sola volta).
REM L'eseguibile finale funziona senza Python, senza JupyterLab e senza pacchetti.
REM
REM Prima serve Python per la sola compilazione: scaricalo da python.org e
REM durante l'installazione spunta "Add python.exe to PATH".
REM
REM Uso: metti questo file nella stessa cartella di exoplanet_searcher.py e fai
REM      doppio clic su crea_eseguibile_windows.bat
REM ===========================================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist motore_exo.py (
    echo ERRORE: motore_exo.py non e' in questa cartella: %cd%
    pause
    exit /b 1
)
if not exist exoplanet_searcher.py (
    echo ERRORE: exoplanet_searcher.py non e' in questa cartella: %cd%
    pause
    exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
    echo ERRORE: Python non trovato. Installalo da https://www.python.org
    echo spuntando "Add python.exe to PATH", poi riavvia questo file.
    pause
    exit /b 1
)

echo === 1/3  Ambiente Python temporaneo per la compilazione ===
if not exist .venv-build (%PY% -m venv .venv-build || goto errore)
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip || goto errore
python -m pip install numpy scipy matplotlib pillow astropy astroquery pyvo requests keyring transitleastsquares pyinstaller || goto errore

echo === 2/3  Creazione dell'eseguibile (qualche minuto) ===
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name ExoplanetSearcher ^
    --collect-all astropy ^
    --collect-all astroquery ^
    --collect-all pyvo ^
    --collect-all erfa ^
    --collect-all keyring ^
    --collect-all transitleastsquares ^
    --collect-all numba ^
    --collect-all llvmlite ^
    --collect-all batman ^
    --collect-data astropy_iers_data ^
    --collect-submodules scipy ^
    --collect-binaries scipy ^
    --collect-submodules html5lib ^
    --collect-submodules bs4 ^
    --copy-metadata numpy ^
    --copy-metadata scipy ^
    --copy-metadata astropy ^
    --copy-metadata astroquery ^
    --copy-metadata pyvo ^
    --copy-metadata requests ^
    --copy-metadata keyring ^
    --copy-metadata pyerfa ^
    --copy-metadata astropy-iers-data ^
    --copy-metadata packaging ^
    --copy-metadata pyyaml ^
    --copy-metadata matplotlib ^
    --copy-metadata pillow ^
    --copy-metadata numba ^
    --copy-metadata llvmlite ^
    --copy-metadata transitleastsquares ^
    --copy-metadata tqdm ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import PIL.ImageTk ^
    --hidden-import matplotlib.backends.backend_agg ^
    --hidden-import matplotlib.backends.backend_pdf ^
    exoplanet_searcher.py || goto errore
call deactivate

echo === Verifica dell'eseguibile (autotest) ===
del /q autotest_risultato.txt 2>nul
dist\ExoplanetSearcher.exe --autotest > autotest.txt 2>&1
if exist autotest_risultato.txt type autotest_risultato.txt >> autotest.txt
type autotest.txt
findstr /c:"AUTOTEST SUPERATO" autotest.txt >nul || (
    echo.
    echo L'autotest e' FALLITO: i dettagli sono in %cd%\autotest.txt
    goto errore
)

echo === Prova degli archivi online (diagnostica, serve Internet) ===
del /q diagnostica_risultato.txt 2>nul
dist\ExoplanetSearcher.exe --diagnostica > diagnostica.txt 2>&1
if exist diagnostica_risultato.txt type diagnostica_risultato.txt >> diagnostica.txt
findstr /b /c:"[ok]" /c:"[ERRORE]" diagnostica.txt
echo (dettagli in %cd%\diagnostica.txt)

echo === 3/3  Collegamento sul Desktop ===
copy /y dist\ExoplanetSearcher.exe "%cd%\ExoplanetSearcher.exe" >nul
powershell -NoProfile -Command ^
  "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\Exoplanet Searcher.lnk\"); $s.TargetPath='%cd%\ExoplanetSearcher.exe'; $s.WorkingDirectory='%cd%'; $s.Save()"

rmdir /s /q .venv-build build 2>nul
del /q ExoplanetSearcher.spec 2>nul

echo.
echo FATTO.
echo   Eseguibile: %cd%\ExoplanetSearcher.exe
echo   Sul Desktop trovi il collegamento "Exoplanet Searcher".
echo   Puoi copiare ExoplanetSearcher.exe su qualsiasi PC Windows: non serve altro.
pause
exit /b 0

:errore
echo.
echo Si e' verificato un errore: copia i messaggi qui sopra e inviameli.
pause
exit /b 1
