#!/usr/bin/env bash
# =============================================================================
# Crea l'eseguibile "ExoplanetSearcher" per Ubuntu (da fare UNA sola volta).
# L'eseguibile finale funziona senza Python, senza JupyterLab e senza pacchetti.
#
# Uso: metti questo file nella stessa cartella di exoplanet_searcher.py, poi nel terminale:
#     cd <cartella con i due file>
#     bash crea_eseguibile_ubuntu.sh
# =============================================================================
set -e
cd "$(dirname "$(readlink -f "$0")")"

if [ ! -f exoplanet_searcher.py ] || [ ! -f motore_exo.py ]; then
    echo "ERRORE: exoplanet_searcher.py e motore_exo.py devono essere in questa cartella ($(pwd))."
    exit 1
fi

echo "=== 1/4  Strumenti di sistema (chiede la password) ==="
sudo apt update
sudo apt install -y python3-venv python3-tk

echo "=== 2/4  Ambiente Python temporaneo per la compilazione ==="
# l'ambiente viene riusato se esiste già (ricompilazioni molto più rapide)
[ -d .venv-build ] || python3 -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install numpy scipy matplotlib pillow astropy astroquery pyvo requests keyring transitleastsquares pyinstaller

echo "=== 3/4  Creazione dell'eseguibile (qualche minuto) ==="
pyinstaller --noconfirm --clean --onefile --windowed \
    --name ExoplanetSearcher \
    --collect-all astropy \
    --collect-all astroquery \
    --collect-all pyvo \
    --collect-all erfa \
    --collect-all keyring \
    --collect-all transitleastsquares \
    --collect-all numba \
    --collect-all llvmlite \
    --collect-all batman \
    --collect-data astropy_iers_data \
    --collect-submodules scipy \
    --collect-binaries scipy \
    --collect-submodules html5lib \
    --collect-submodules bs4 \
    --copy-metadata numpy \
    --copy-metadata scipy \
    --copy-metadata astropy \
    --copy-metadata astroquery \
    --copy-metadata pyvo \
    --copy-metadata requests \
    --copy-metadata keyring \
    --copy-metadata pyerfa \
    --copy-metadata astropy-iers-data \
    --copy-metadata packaging \
    --copy-metadata pyyaml \
    --copy-metadata matplotlib \
    --copy-metadata pillow \
    --copy-metadata numba \
    --copy-metadata llvmlite \
    --copy-metadata transitleastsquares \
    --copy-metadata tqdm \
    --hidden-import PIL._tkinter_finder \
    --hidden-import PIL.ImageTk \
    --hidden-import matplotlib.backends.backend_agg \
    --hidden-import matplotlib.backends.backend_pdf \
    exoplanet_searcher.py
deactivate

echo "=== Verifica dell'eseguibile (autotest) ==="
if ! ./dist/ExoplanetSearcher --autotest > autotest.txt 2>&1; then
    cat autotest.txt
    echo
    echo "L'autotest è FALLITO: i dettagli sono in $(pwd)/autotest.txt"
    echo "L'eseguibile non è stato installato. Invia autotest.txt per la correzione."
    rm -rf build ExoplanetSearcher.spec
    exit 1
fi
cat autotest.txt

echo "=== Prova dei servizi in rete (diagnostica: scarica e analizza due stelle con pianeti noti, qualche minuto) ==="
./dist/ExoplanetSearcher --diagnostica > diagnostica.txt 2>&1 || true
grep -E "^\[(ok|ERRORE)\]" diagnostica.txt || true
echo "(dettagli in $(pwd)/diagnostica.txt)"

echo "=== 4/4  Installazione nella home e icona nel menu ==="
DEST="$HOME/.local/bin"
mkdir -p "$DEST" "$HOME/.local/share/applications"
cp dist/ExoplanetSearcher "$DEST/ExoplanetSearcher"
chmod +x "$DEST/ExoplanetSearcher"

cat > "$HOME/.local/share/applications/exoplanet-searcher.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Exoplanet Searcher
Comment=Ricerca automatica di esopianeti nei dati di TESS, Kepler e K2
Exec=$DEST/ExoplanetSearcher
Icon=applications-science
Terminal=false
Categories=Science;Astronomy;Education;
EOF
chmod +x "$HOME/.local/share/applications/exoplanet-searcher.desktop"

# Copia anche sulla Scrivania (cartella Desktop o Scrivania, a seconda della lingua)
SCRIVANIA="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Scrivania")"
if [ -d "$SCRIVANIA" ]; then
    cp "$HOME/.local/share/applications/exoplanet-searcher.desktop" "$SCRIVANIA/"
    chmod +x "$SCRIVANIA/exoplanet-searcher.desktop"
    gio set "$SCRIVANIA/exoplanet-searcher.desktop" metadata::trusted true 2>/dev/null || true
fi

# Pulizia dei file della compilazione (l'eseguibile resta in dist/ e in ~/.local/bin)
rm -rf .venv-build build ExoplanetSearcher.spec

echo
echo "FATTO."
echo "  Eseguibile:  $DEST/ExoplanetSearcher   (copia anche in $(pwd)/dist/)"
echo "  Avvio:       cerca 'Exoplanet Searcher' nel menu delle applicazioni,"
echo "               oppure doppio clic sull'icona sulla Scrivania"
echo "               (la prima volta: tasto destro -> 'Consenti avvio')."
