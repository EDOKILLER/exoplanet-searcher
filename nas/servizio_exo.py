#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EXOPLANET SEARCHER - SERVIZIO PER IL NAS (senza finestra)
========================================================
© 2026 Edoardo Battistel

Gira di continuo dentro Docker sul NAS, a priorità minima:
  - legge le opzioni da exo_config.json (nella cartella dei dati, creato al primo avvio);
  - profilo "approfondito": periodi fino a 250 giorni, griglia TLS più fine,
    fino a 5 segnali per stella;
  - se manca Internet aspetta e riprova (le stelle non vengono segnate come errori);
  - finito tutto, dorme 12 ore e ricontrolla se ci sono nuovi settori TESS;
  - scrive servizio_attivo.json ogni minuto: il programma sul PC lo legge e
    mostra l'avanzamento ("Ricerca in corso sul NAS").

Uso:  python servizio_exo.py [cartella_dati]      (di base /dati)
      python servizio_exo.py --prova               prova breve senza rete
"""

import json
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import motore_exo as M  # noqa: E402

CONFIG_PREDEFINITA = {
    "_nota": "Opzioni di Exoplanet Searcher sul NAS. Dopo una modifica riavvia il container.",
    "profilo": "approfondito",
    "missioni": {"tess2": True, "tessffi": True, "kepler": True, "k2": True},
    "mag_ffi": 15.0,
    "paralleli": 2,
    "thread_per_stella": 2,
    "ore_di_pausa_a_fine_giro": 12,
}


class Battito:
    """Riceve gli eventi del Cacciatore e aggiorna servizio_attivo.json."""

    def __init__(self, cartella):
        self.p = Path(cartella) / M.FILE_SERVIZIO
        self.d = {"stato": "avvio", "rete": True, "fatte": 0, "totale": 0, "stelle_ora": 0.0,
                  "candidati_sessione": 0, "avvio": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.cartella = Path(cartella)
        self.lock = threading.Lock()
        self.scrivi()

    def put(self, evento):
        tipo, d = evento
        with self.lock:
            if tipo == "log":
                print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {d}", flush=True)
                return
            if tipo == "progresso":
                mis, lotto, k, tot, ora, resto, ident = d
                self.d.update(stato="ricerca", missione=dict(M.MISSIONI).get(mis, mis), lotto=lotto,
                              fatte=k, totale=tot, stelle_ora=round(ora, 2), ore_alla_fine_lotto=round(resto / 3600, 1),
                              ultima=ident)
            elif tipo == "candidato":
                self.d["candidati_sessione"] += 1
            elif tipo == "rete":
                self.d["rete"] = bool(d)
            elif tipo == "stato":
                self.d["stato"] = d
        self.scrivi()

    def scrivi(self):
        try:
            p_c = self.cartella / M.FILE_CANDIDATI
            n = 0
            if p_c.exists():
                with open(p_c, encoding="utf-8-sig") as f:
                    n = max(0, sum(1 for _ in f) - 1)
            self.d["candidati_totali"] = n
            self.d["ora"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            tmp = self.p.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.p)
        except OSError:
            pass


def carica_config(cartella):
    p = Path(cartella) / "exo_config.json"
    cfg = dict(CONFIG_PREDEFINITA)
    try:
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        p.write_text(json.dumps(CONFIG_PREDEFINITA, indent=1, ensure_ascii=False), encoding="utf-8")
    return cfg


def abbassa_priorita():
    """Priorità minima anche se il container non usa nice/ionice."""
    try:
        os.nice(19 - os.nice(0))
    except OSError:
        pass
    try:
        import subprocess
        subprocess.run(["ionice", "-c", "3", "-p", str(os.getpid())], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def main(cartella):
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    abbassa_priorita()
    cfg = carica_config(cartella)
    M.applica_profilo(cfg.get("profilo", "approfondito"))
    ferma = threading.Event()

    def stop(*_):
        print("Arresto richiesto: finisco le stelle in corso…", flush=True)
        ferma.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    battito = Battito(cartella)
    # battito anche quando non arrivano eventi (per esempio durante una stella Kepler lunga)
    def pulsa():
        while not ferma.wait(60):
            battito.scrivi()
    threading.Thread(target=pulsa, daemon=True).start()

    print(f"{M.NOME_PROGRAMMA} {M.VERSIONE} (servizio NAS) — {M.COPYRIGHT}", flush=True)
    print(f"Cartella: {cartella}  ·  nuclei visibili: {M.n_nuclei()}  ·  profilo: {cfg.get('profilo')}", flush=True)
    while not ferma.is_set():
        opzioni = {"missioni": cfg.get("missioni", {}), "mag_ffi": float(cfg.get("mag_ffi", 15.0)),
                   "paralleli": int(cfg.get("paralleli", 2))}
        cacc = M.Cacciatore(cartella, opzioni, battito, ferma,
                            thread_tls=max(1, int(cfg.get("thread_per_stella", 2))))
        try:
            battito.put(("stato", "ricerca"))
            cacc.esegui()
        except Exception:
            cacc.log("ERRORE:\n" + traceback.format_exc())
            ferma.wait(600)              # errore imprevisto: riprovo tra 10 minuti
            continue
        if ferma.is_set():
            break
        ore = float(cfg.get("ore_di_pausa_a_fine_giro", 12))
        battito.put(("stato", f"in pausa fino a {datetime.fromtimestamp(time.time() + ore * 3600):%Y-%m-%d %H:%M}"))
        cacc.log(f"Giro completo: ricontrollo i nuovi settori tra {ore:g} ore")
        ferma.wait(ore * 3600)
    battito.put(("stato", "fermo"))
    try:
        battito.p.unlink()               # il PC smette subito di mostrare "in corso sul NAS"
    except OSError:
        pass
    print("Servizio fermato.", flush=True)


def prova():
    """Prova senza rete: battito, profilo, Cacciatore con una stella sintetica in caso di rete assente."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="exo_nas_prova_"))
    M.applica_profilo("approfondito")
    assert M.PERIODO_MAX == 250.0 and M.OVERSAMPLING_TLS == 5 and M.MAX_SEGNALI == 5
    b = Battito(d)
    b.put(("progresso", ("tess2", "s0099", 5, 100, 3.2, 3600, "TIC 1")))
    dati = json.loads((d / M.FILE_SERVIZIO).read_text(encoding="utf-8"))
    assert dati["fatte"] == 5 and dati["lotto"] == "s0099"
    import urllib.error
    assert M.errore_di_rete(urllib.error.URLError("no route"))
    assert not M.errore_di_rete(ValueError("file rotto"))
    print("PROVA SERVIZIO SUPERATA:", d)


if __name__ == "__main__":
    if "--prova" in sys.argv:
        prova()
    else:
        argomenti = [a for a in sys.argv[1:] if not a.startswith("-")]
        main(argomenti[0] if argomenti else os.environ.get("EXO_DATI", "/dati"))
