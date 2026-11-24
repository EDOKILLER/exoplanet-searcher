#!/bin/bash
# Exoplanet Searcher - avvio del servizio nel container Docker del NAS
# © 2026 Edoardo Battistel
# Al primo avvio installa Python e le librerie in /dati/programma/_python (resta sul NAS:
# i riavvii successivi sono immediati). Poi avvia la ricerca a priorità minima.
umask 000                                   # file leggibili e cancellabili anche dal PC
cd /dati/programma || exit 1
export HOME=/dati/programma/_home MPLBACKEND=Agg PYTHONUNBUFFERED=1
export NUMBA_CACHE_DIR=/dati/programma/_numba_cache
mkdir -p "$HOME" "$NUMBA_CACHE_DIR"
VENV=/dati/programma/_python
if [ ! -f "$VENV/.pronto_1.1" ]; then
    echo "Primo avvio: installo le librerie (10-20 minuti, serve Internet)…"
    until python -m venv "$VENV" && \
          "$VENV/bin/pip" install --no-cache-dir --upgrade pip && \
          "$VENV/bin/pip" install --no-cache-dir -r requisiti.txt; do
        echo "Installazione non riuscita (Internet assente?): riprovo tra 10 minuti"
        sleep 600
    done
    touch "$VENV/.pronto_1.1"
fi
"$VENV/bin/python" -c "import transitleastsquares; print('TLS disponibile')" || echo "ATTENZIONE: TLS non disponibile, uso BLS"
exec nice -n 19 ionice -c 3 "$VENV/bin/python" servizio_exo.py /dati
