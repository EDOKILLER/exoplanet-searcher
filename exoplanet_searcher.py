#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EXOPLANET SEARCHER - ricerca automatica di esopianeti nei dati di TESS, Kepler e K2
=================================================================================
© 2026 Edoardo Battistel

Gira da solo finché il computer è acceso: scarica una curva di luce, cerca i
transiti (TLS), controlla i falsi positivi e i pianeti già noti, salva
risultati e grafici, cancella i FITS e passa alla stella successiva.
Ordine: TESS a 2 minuti (dal settore più recente) -> TESS immagini a campo
intero (fino alla magnitudine scelta) -> Kepler -> K2. Si ferma e riprende
da dove era rimasto.

Opzioni: --autotest (prove senza rete) e --diagnostica (prove in rete).
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

import motore_exo as M

NOME = M.NOME_PROGRAMMA
FILE_CONFIG = Path.home() / ".exoplanet_searcher.json"
ZOOM_PREDEFINITO = 1.0 if sys.platform == "win32" else 1.4
ZOOM_MIN, ZOOM_MAX, ZOOM_PASSO = 0.8, 2.6, 0.1
COLONNE = [("stella", "Stella", 15), ("segnale", "N.", 3), ("missione", "Missione", 8), ("periodo_giorni", "Periodo (g)", 10),
           ("profondita_ppm", "Profondità (ppm)", 11), ("raggio_terre", "Raggio (R⊕)", 9), ("sde", "SDE", 6),
           ("snr", "SNR", 6), ("confronto", "Confronto", 18), ("controlli", "Controlli", 30)]


def carica_config():
    try:
        c = json.loads(FILE_CONFIG.read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def salva_config(c):
    try:
        FILE_CONFIG.write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def cartella_predefinita():
    for n in ("Scrivania", "Desktop"):
        if (Path.home() / n / "Astronomia").is_dir():
            return Path.home() / n / "Astronomia" / "Exoplanet_Searcher"
    return Path.home() / "Exoplanet_Searcher"


n_nuclei = M.n_nuclei
Cacciatore = M.Cacciatore


# =============================================================================
# FINESTRA
# =============================================================================
class App(tk.Tk):
    FONT_DI_SISTEMA = ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont",
                       "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")

    def __init__(self):
        super().__init__()
        self.title(f"{NOME} {M.VERSIONE}  —  {M.COPYRIGHT}")
        self.geometry("1366x800")
        self.minsize(1000, 600)
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass
        self.cfg = carica_config()
        self.zoom = min(max(float(self.cfg.get("zoom", ZOOM_PREDEFINITO)), ZOOM_MIN), ZOOM_MAX)
        self.cartella = Path(self.cfg.get("cartella") or cartella_predefinita())
        self.coda = queue.Queue()
        self.ferma = threading.Event()
        self.thread = None
        self._foto = None
        self._stile()
        self._costruisci()
        self._applica_zoom()
        for t in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            self.bind_all(t, lambda e: self._cambia_zoom(+ZOOM_PASSO))
        for t in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.bind_all(t, lambda e: self._cambia_zoom(-ZOOM_PASSO))
        self.bind_all("<Control-0>", lambda e: self._cambia_zoom(None))
        self.protocol("WM_DELETE_WINDOW", self._chiudi)
        self.after(150, self._controlla_coda)
        self.after(2000, self._controlla_nas)
        self.after(300, self._carica_candidati)
        if self.cfg.get("avvio_automatico"):
            self.after(1500, self._avvia)

    # ---------------------------------------------------------------- stile
    def _stile(self):
        self._font_base = {}
        for n in self.FONT_DI_SISTEMA:
            try:
                self._font_base[n] = tkfont.nametofont(n).cget("size") or 10
            except tk.TclError:
                pass
        fam = tkfont.nametofont("TkDefaultFont").actual()["family"]
        self.f_titolo = tkfont.Font(family=fam, weight="bold")
        self.f_grassetto = tkfont.Font(family=fam, weight="bold")
        self.f_nota = tkfont.Font(family=fam, slant="italic")
        self.st = ttk.Style(self)
        try:
            self.st.theme_use("clam")
        except tk.TclError:
            pass
        self.option_add("*TCombobox*Listbox.font", "TkDefaultFont")

    def _applica_zoom(self):
        z = self.zoom
        sc = lambda b, f: (-1 if b < 0 else 1) * max(1, round(abs(b) * f))
        for n, b in self._font_base.items():
            tkfont.nametofont(n).configure(size=sc(b, z))
        b = self._font_base.get("TkDefaultFont", 10)
        self.f_titolo.configure(size=sc(b, 1.3 * z))
        self.f_grassetto.configure(size=sc(b, 1.05 * z))
        self.f_nota.configure(size=sc(b, 0.92 * z))
        p = lambda v: max(1, round(v * z))
        s = self.st
        s.configure("TButton", padding=(p(8), p(5)))
        s.configure("Grande.TButton", font=self.f_grassetto, padding=(p(14), p(8)))
        s.configure("Casella.TButton", anchor="w", padding=(p(4), p(2)), relief="flat")
        s.configure("Titolo.TLabel", font=self.f_titolo)
        s.configure("Campo.TLabel", font=self.f_grassetto)
        s.configure("Nota.TLabel", font=self.f_nota, foreground="#555555")
        s.configure("TNotebook.Tab", padding=(p(14), p(6)), font=self.f_grassetto)
        s.configure("Treeview", rowheight=tkfont.nametofont("TkDefaultFont").metrics("linespace") + p(8))
        s.configure("Treeview.Heading", font=self.f_grassetto, padding=p(4))
        s.configure("TSpinbox", padding=p(4), arrowsize=p(20))
        for o in ("Vertical", "Horizontal"):
            s.configure(f"{o}.TScrollbar", arrowsize=p(22), width=p(22))
        s.configure("TProgressbar", thickness=p(18))
        larg = tkfont.nametofont("TkDefaultFont").measure("0")
        for k, _, l in COLONNE:
            self.tab.column(k, width=l * larg + p(14))

    def _cambia_zoom(self, d):
        self.zoom = ZOOM_PREDEFINITO if d is None else min(max(round(self.zoom + d, 2), ZOOM_MIN), ZOOM_MAX)
        self.cfg["zoom"] = self.zoom
        salva_config(self.cfg)
        self._applica_zoom()
        return "break"

    def _casella(self, master, testo, var, comando=None):
        b = ttk.Button(master, style="Casella.TButton")

        def agg(*a):
            b.configure(text=("☑  " if var.get() else "☐  ") + testo)

        def clic():
            var.set(not var.get())
            if comando:
                comando()
        b.configure(command=clic)
        var.trace_add("write", agg)
        agg()
        return b

    # ---------------------------------------------------------------- layout
    def _costruisci(self):
        mb = tk.Menu(self, tearoff=0)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Cartella dei risultati…", command=self._scegli_cartella)
        m.add_command(label="Apri la cartella dei risultati", command=self._apri_cartella)
        m.add_separator()
        m.add_command(label="Esci", accelerator="Ctrl+Q", command=self._chiudi)
        mb.add_cascade(label="File", menu=m)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="▶ Avvia la ricerca", command=self._avvia)
        m.add_command(label="⏸ Pausa (dopo le stelle in corso)", command=self._pausa)
        m.add_separator()
        m.add_command(label="Aggiorna ora i cataloghi dei pianeti noti", command=self._aggiorna_noti)
        m.add_command(label="Prova i servizi in rete", command=self._prova)
        mb.add_cascade(label="Ricerca", menu=m)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Ingrandisci il testo", accelerator="Ctrl +", command=lambda: self._cambia_zoom(+ZOOM_PASSO))
        m.add_command(label="Riduci il testo", accelerator="Ctrl −", command=lambda: self._cambia_zoom(-ZOOM_PASSO))
        m.add_command(label="Testo normale", accelerator="Ctrl 0", command=lambda: self._cambia_zoom(None))
        mb.add_cascade(label="Opzioni", menu=m)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label=f"Informazioni su {NOME}…", command=self._informazioni)
        mb.add_cascade(label="Informazioni", menu=m)
        self.config(menu=mb)
        self.bind_all("<Control-q>", lambda e: self._chiudi())

        bas = ttk.Frame(self, padding=(10, 2, 10, 6))
        bas.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bas, text=f"{NOME} {M.VERSIONE}  ·  {M.COPYRIGHT}", style="Nota.TLabel").pack(side=tk.RIGHT)
        self.lbl_motore = ttk.Label(bas, text="", style="Nota.TLabel")
        self.lbl_motore.pack(side=tk.LEFT)

        alto = ttk.Frame(self, padding=(10, 8))
        alto.pack(fill=tk.X)
        self.btn_avvia = ttk.Button(alto, text="▶  Avvia la ricerca", style="Grande.TButton", command=self._avvia)
        self.btn_avvia.pack(side=tk.LEFT)
        self.btn_pausa = ttk.Button(alto, text="⏸  Pausa", style="Grande.TButton", command=self._pausa, state=tk.DISABLED)
        self.btn_pausa.pack(side=tk.LEFT, padx=6)
        self.lbl_stato = ttk.Label(alto, text="Fermo", style="Titolo.TLabel")
        self.lbl_stato.pack(side=tk.LEFT, padx=12)
        self.lbl_cartella = ttk.Label(alto, text="", style="Nota.TLabel")
        self.lbl_cartella.pack(side=tk.RIGHT)

        opz = ttk.LabelFrame(self, text="Impostazioni", padding=(10, 4))
        opz.pack(fill=tk.X, padx=10)
        r1 = ttk.Frame(opz)
        r1.pack(fill=tk.X)
        ttk.Label(r1, text="Missioni, in quest'ordine:", style="Campo.TLabel").pack(side=tk.LEFT)
        self.var_mis = {}
        for k, et in M.MISSIONI:
            v = tk.BooleanVar(value=self.cfg.get("missioni", {}).get(k, True))
            self.var_mis[k] = v
            self._casella(r1, et, v, self._salva_opzioni).pack(side=tk.LEFT, padx=(8, 0))
        r2 = ttk.Frame(opz)
        r2.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(r2, text="Magnitudine massima per le immagini a campo intero:", style="Campo.TLabel").pack(side=tk.LEFT)
        self.var_mag = tk.StringVar(value=str(self.cfg.get("mag_ffi", 13.0)))
        ttk.Spinbox(r2, from_=8, to=16, increment=0.5, textvariable=self.var_mag, width=5,
                    command=self._salva_opzioni).pack(side=tk.LEFT, padx=6)
        ttk.Label(r2, text="Stelle analizzate insieme:", style="Campo.TLabel").pack(side=tk.LEFT, padx=(20, 0))
        self.var_par = tk.StringVar(value=str(self.cfg.get("paralleli", 2)))
        ttk.Spinbox(r2, from_=1, to=max(1, n_nuclei()), increment=1, textvariable=self.var_par, width=4,
                    command=self._salva_opzioni).pack(side=tk.LEFT, padx=6)
        ttk.Label(r2, text=f"(nuclei del processore: {n_nuclei()})", style="Nota.TLabel").pack(side=tk.LEFT)
        self.var_auto = tk.BooleanVar(value=self.cfg.get("avvio_automatico", False))
        r3 = ttk.Frame(opz)
        r3.pack(fill=tk.X, pady=(2, 0))
        self._casella(r3, "Riprendi la ricerca da solo all'apertura del programma", self.var_auto,
                      self._salva_opzioni).pack(side=tk.LEFT)

        pr = ttk.Frame(self, padding=(10, 6))
        pr.pack(fill=tk.X)
        self.lbl_prog = ttk.Label(pr, text="")
        self.lbl_prog.pack(fill=tk.X)
        self.prog = ttk.Progressbar(pr, mode="determinate", maximum=1000)
        self.prog.pack(fill=tk.X)

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))
        self.nb = nb
        # --- candidati
        fc = ttk.Frame(nb, padding=4)
        nb.add(fc, text="⭐ Candidati")
        cima = ttk.Frame(fc)
        cima.pack(fill=tk.X)
        self.var_solo_nuovi = tk.BooleanVar(value=True)
        self._casella(cima, "Solo i nuovi (non già noti)", self.var_solo_nuovi, self._carica_candidati).pack(side=tk.LEFT)
        self.var_solo_puliti = tk.BooleanVar(value=False)
        self._casella(cima, "Solo quelli che superano tutti i controlli", self.var_solo_puliti,
                      self._carica_candidati).pack(side=tk.LEFT, padx=10)
        ttk.Button(cima, text="📄 Apri la scheda PDF", command=self._apri_scheda).pack(side=tk.RIGHT)
        ttk.Button(cima, text="📁 Apri la cartella del candidato", command=self._apri_cart_cand).pack(side=tk.RIGHT, padx=6)
        corpo = ttk.PanedWindow(fc, orient=tk.HORIZONTAL)
        corpo.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        ft = ttk.Frame(corpo)
        corpo.add(ft, weight=3)
        self.tab = ttk.Treeview(ft, columns=[c[0] for c in COLONNE], show="headings", selectmode="browse")
        for k, t, l in COLONNE:
            self.tab.heading(k, text=t)
            self.tab.column(k, width=l * 10, anchor="w")
        sb = ttk.Scrollbar(ft, orient=tk.VERTICAL, command=self.tab.yview)
        sbx = ttk.Scrollbar(ft, orient=tk.HORIZONTAL, command=self.tab.xview)
        self.tab.configure(yscrollcommand=sb.set, xscrollcommand=sbx.set)
        sbx.pack(side=tk.BOTTOM, fill=tk.X)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tab.pack(fill=tk.BOTH, expand=True)
        self.tab.bind("<<TreeviewSelect>>", lambda e: self._mostra_grafico())
        self.tab.bind("<Double-1>", lambda e: self._apri_scheda())
        self.lbl_graf = tk.Label(corpo, background="white", text="Seleziona un candidato per vedere i grafici",
                                 font=self.f_nota)
        corpo.add(self.lbl_graf, weight=2)
        self.lbl_graf.bind("<Configure>", self._ridimensiona_grafico)
        self.after(600, lambda: corpo.sashpos(0, int(corpo.winfo_width() * 0.55)) if corpo.winfo_width() > 100 else None)
        self._righe = {}
        # --- registro
        fr = ttk.Frame(nb, padding=4)
        nb.add(fr, text="📜 Registro")
        self.log = tk.Text(fr, wrap="word", font="TkFixedFont")
        sbl = ttk.Scrollbar(fr, orient=tk.VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=sbl.set)
        sbl.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(fill=tk.BOTH, expand=True)
        # --- statistiche
        fs = ttk.Frame(nb, padding=12)
        nb.add(fs, text="📊 Statistiche")
        self.lbl_stat = ttk.Label(fs, text="", justify="left", style="Campo.TLabel")
        self.lbl_stat.pack(anchor="nw")
        self._aggiorna_cartella()
        self.lbl_motore.configure(text=f"Motore di ricerca: {M.motore_ricerca()}   ·   cartella: {self.cartella}")

    # ---------------------------------------------------------------- azioni
    def _opzioni(self):
        try:
            mag = float(self.var_mag.get().replace(",", "."))
        except ValueError:
            mag = 13.0
        try:
            par = max(1, int(self.var_par.get()))
        except ValueError:
            par = 2
        return {"missioni": {k: v.get() for k, v in self.var_mis.items()}, "mag_ffi": mag, "paralleli": par,
                "avvio_automatico": self.var_auto.get()}

    def _salva_opzioni(self):
        self.cfg.update(self._opzioni())
        salva_config(self.cfg)

    def scrivi(self, m):
        self.log.insert(tk.END, f"{datetime.now():%H:%M:%S}  {m}\n")
        self.log.see(tk.END)
        if int(self.log.index("end-1c").split(".")[0]) > 5000:
            self.log.delete("1.0", "1000.0")

    def _stato_nas(self):
        """Contenuto del "battito" del servizio NAS se è recente (< 20 minuti), altrimenti None."""
        p = self.cartella / M.FILE_SERVIZIO
        try:
            if time.time() - p.stat().st_mtime > 1200:
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _controlla_nas(self):
        if not (self.thread and self.thread.is_alive()):
            d = self._stato_nas()
            if d:
                self.btn_avvia.configure(state=tk.DISABLED)
                testo = "Ricerca in corso sul NAS" if d.get("rete", True) else "NAS: in attesa di Internet"
                self.lbl_stato.configure(text=testo, foreground="#0a5aa0")
                k, tot = d.get("fatte", 0), d.get("totale", 0)
                self.prog.configure(value=1000 * k / max(tot, 1))
                self.lbl_prog.configure(text=f"NAS — {d.get('missione', '')} {d.get('lotto', '')}: {k}/{tot} stelle  ·  "
                                             f"{d.get('stelle_ora', 0):.1f} stelle/ora  ·  ultima: {d.get('ultima', '')}  ·  "
                                             f"aggiornato {d.get('ora', '')}")
                n = d.get("candidati_totali")
                if n is not None and n != getattr(self, "_n_cand_nas", n):
                    self._carica_candidati()
                self._n_cand_nas = n
                self._nas_attivo = True
            elif getattr(self, "_nas_attivo", False):
                self._nas_attivo = False
                self.btn_avvia.configure(state=tk.NORMAL)
                self.lbl_stato.configure(text="Fermo", foreground="black")
        self.after(30000, self._controlla_nas)

    def _avvia(self):
        if self.thread and self.thread.is_alive():
            return
        if self._stato_nas():
            messagebox.showinfo(NOME, "La ricerca su questa cartella sta già girando sul NAS:\n"
                                      "qui puoi solo guardare i risultati.")
            return
        self._salva_opzioni()
        self.ferma.clear()
        cacc = Cacciatore(self.cartella, self._opzioni(), self.coda, self.ferma)

        def corpo():
            try:
                cacc.esegui()
            except Exception:
                self.coda.put(("log", "ERRORE:\n" + traceback.format_exc()))
            self.coda.put(("fermo", None))
        self.thread = threading.Thread(target=corpo, daemon=True)
        self.thread.start()
        self.btn_avvia.configure(state=tk.DISABLED)
        self.btn_pausa.configure(state=tk.NORMAL)
        self.lbl_stato.configure(text="In ricerca…", foreground="#0a7a0a")

    def _pausa(self):
        self.ferma.set()
        self.lbl_stato.configure(text="Pausa: finisco le stelle in corso…", foreground="#b06000")
        self.btn_pausa.configure(state=tk.DISABLED)

    def _aggiorna_noti(self):
        def lavoro():
            M.aggiorna_cataloghi_noti(self.cartella, lambda m: self.coda.put(("log", m)), giorni=0)
            self.coda.put(("log", f"Pianeti e candidati noti: {len(M.Noti(self.cartella))}"))
        threading.Thread(target=lavoro, daemon=True).start()
        self.nb.select(1)

    def _prova(self):
        def lavoro():
            for r in prova_servizi():
                self.coda.put(("log", r))
        self.scrivi("Prova dei servizi in rete (qualche minuto)…")
        self.nb.select(1)
        threading.Thread(target=lavoro, daemon=True).start()

    def _controlla_coda(self):
        try:
            while True:
                tipo, d = self.coda.get_nowait()
                if tipo == "log":
                    self.scrivi(d)
                elif tipo == "progresso":
                    mis, lotto, k, tot, ora, resto, ident = d
                    nome = dict(M.MISSIONI)[mis]
                    self.prog.configure(value=1000 * k / max(tot, 1))
                    self.lbl_prog.configure(text=f"{nome} — {lotto}: {k}/{tot} stelle  ·  {ora:.0f} stelle/ora  ·  "
                                                 f"fine del lotto tra circa {resto / 3600:.1f} ore  ·  ultima: {ident}")
                    if k % 20 == 0:
                        self._statistiche()
                elif tipo == "candidato":
                    self._aggiungi_riga(d)
                    if d["confronto"] in ("nuovo", "nuovo in sistema noto") and d["controlli"] == "superati":
                        self._avviso(d)
                elif tipo == "fermo":
                    self.btn_avvia.configure(state=tk.NORMAL)
                    self.btn_pausa.configure(state=tk.DISABLED)
                    self.lbl_stato.configure(text="Fermo", foreground="black")
                    self._statistiche()
        except queue.Empty:
            pass
        self.after(200, self._controlla_coda)

    def _avviso(self, r):
        testo = (f"Nuovo candidato: {r['stella']} (segnale {r['segnale']})\nperiodo {r['periodo_giorni']} giorni, "
                 f"raggio ~{r['raggio_terre']} R⊕, SDE {r['sde']}\n{r['confronto']} {r['dettaglio']}")
        self.scrivi("⭐ " + testo.replace("\n", " · "))
        try:
            subprocess.Popen(["notify-send", "-i", "starred", f"{NOME}: nuovo candidato", testo])
        except Exception:
            pass
        self.bell()
        d = tk.Toplevel(self)
        d.title("⭐ Nuovo candidato")
        d.transient(self)
        ttk.Label(d, text=testo, padding=16, justify="left", style="Campo.TLabel").pack()
        bb = ttk.Frame(d, padding=(16, 0, 16, 12))
        bb.pack(fill=tk.X)
        ttk.Button(bb, text="📄 Apri la scheda", command=lambda: self._apri_file(self._cart_cand(r) / "scheda.pdf")
                   ).pack(side=tk.LEFT)
        ttk.Button(bb, text="OK", style="Grande.TButton", command=d.destroy).pack(side=tk.RIGHT)

    def _carica_candidati(self):
        self.tab.delete(*self.tab.get_children())
        self._righe = {}
        p = self.cartella / M.FILE_CANDIDATI
        if p.exists():
            import csv
            with open(p, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f, delimiter=";"):
                    self._aggiungi_riga(r)
        self._statistiche()

    def _aggiungi_riga(self, r):
        if self.var_solo_nuovi.get() and r.get("confronto") not in ("nuovo", "nuovo in sistema noto"):
            return
        if self.var_solo_puliti.get() and r.get("controlli") != "superati":
            return
        iid = self.tab.insert("", 0, values=[r.get(k, "") for k, _, _ in COLONNE])
        self._righe[iid] = r

    def _ridimensiona_grafico(self, e):
        self.lbl_graf.configure(wraplength=max(200, e.width - 20))
        if abs(e.width - getattr(self, "_larg_graf", 0)) > 30:
            self._larg_graf = e.width
            if getattr(self, "_t_graf", None):
                self.after_cancel(self._t_graf)
            self._t_graf = self.after(250, self._mostra_grafico)

    def _scelto(self):
        s = self.tab.selection()
        return self._righe.get(s[0]) if s else None

    def _mostra_grafico(self):
        r = self._scelto()
        if not r or not r.get("cartella"):
            self.lbl_graf.configure(image="", text="Grafici disponibili solo per i candidati nuovi")
            return
        p = self._cart_cand(r) / "grafici.png"
        try:
            from PIL import Image, ImageTk
            im = Image.open(p)
            w = max(300, self.lbl_graf.winfo_width() - 10)
            h = max(200, self.lbl_graf.winfo_height() - 10)
            im.thumbnail((w, h))
            self._foto = ImageTk.PhotoImage(im)
            self.lbl_graf.configure(image=self._foto, text="")
        except Exception:
            self.lbl_graf.configure(image="", text=f"Grafico non trovato:\n{p}")

    def _apri_file(self, p):
        try:
            if sys.platform == "win32":
                os.startfile(p)
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            messagebox.showerror("Apri", str(e))

    def _cart_cand(self, r):
        """Cartella del candidato: relativa alla cartella dei risultati (anche se calcolata sul NAS)."""
        p = Path(r["cartella"])
        if not p.is_absolute():
            return self.cartella / p
        if p.exists():
            return p
        return self.cartella / M.CARTELLA_CANDIDATI / p.name

    def _apri_scheda(self):
        r = self._scelto()
        if r and r.get("cartella"):
            self._apri_file(self._cart_cand(r) / "scheda.pdf")

    def _apri_cart_cand(self):
        r = self._scelto()
        if r and r.get("cartella"):
            self._apri_file(self._cart_cand(r))

    def _apri_cartella(self):
        self.cartella.mkdir(parents=True, exist_ok=True)
        self._apri_file(self.cartella)

    def _scegli_cartella(self):
        if self.thread and self.thread.is_alive():
            messagebox.showinfo("Cartella", "Metti prima in pausa la ricerca.")
            return
        d = filedialog.askdirectory(title="Cartella dei risultati", initialdir=str(self.cartella.parent))
        if d:
            self.cartella = Path(d)
            self.cfg["cartella"] = d
            salva_config(self.cfg)
            self._aggiorna_cartella()
            self._carica_candidati()

    def _aggiorna_cartella(self):
        self.lbl_cartella.configure(text=f"Risultati in: {self.cartella}")

    def _statistiche(self):
        try:
            tot, per = M.Stato(self.cartella).conteggi()
        except Exception:
            tot, per = 0, {}
        n_c = len(self._righe)
        righe = [f"Stelle analizzate in tutto: {tot}"]
        for k, et in M.MISSIONI:
            righe.append(f"   {et}: {per.get(k, 0)}")
        righe += ["", f"Candidati mostrati nella tabella: {n_c}",
                  f"Motore di ricerca: {M.motore_ricerca()}", f"Cartella: {self.cartella}"]
        self.lbl_stat.configure(text="\n".join(righe))

    def _informazioni(self):
        messagebox.showinfo(f"Informazioni su {NOME}",
                            f"{NOME} {M.VERSIONE}\n{M.COPYRIGHT}\n\nDati: TESS, Kepler e K2 dall'archivio MAST "
                            f"(STScI). Pianeti noti: NASA Exoplanet Archive (Caltech/IPAC). Ricerca dei transiti: "
                            f"Transit Least Squares (Hippke & Heller 2019) o Box Least Squares.")

    def _chiudi(self):
        if self.thread and self.thread.is_alive():
            if not messagebox.askyesno("Uscire?", "La ricerca è in corso. Uscire? (riprenderà da dove era rimasta)"):
                return
            self.ferma.set()
        self.destroy()


# =============================================================================
# PROVE
# =============================================================================
def prova_servizi():
    """Prova in rete: elenchi, una stella con pianeta noto per TESS e Kepler, archivi."""
    out = []
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="exo_diag_"))
    try:
        t0 = time.time()
        try:
            s = M.ultimo_settore_tess()
            out.append(f"[ok] ultimo settore TESS a 2 minuti: {s} ({time.time() - t0:.0f} s)")
        except Exception as e:
            out.append(f"[ERRORE] ultimo settore TESS: {e}")
        t0 = time.time()
        try:
            el = M.stelle_tess_2min(1)
            out.append(f"[ok] elenco TESS settore 1: {len(el)} stelle ({time.time() - t0:.0f} s)")
        except Exception as e:
            el = []
            out.append(f"[ERRORE] elenco TESS: {type(e).__name__}: {e}")
        t0 = time.time()
        try:
            M.aggiorna_cataloghi_noti(d, lambda m: out.append("       " + m), giorni=0)
            n = M.Noti(d)
            out.append(f"[ok] NASA Exoplanet Archive: {len(n)} pianeti e candidati noti ({time.time() - t0:.0f} s)")
        except Exception as e:
            n = None
            out.append(f"[ERRORE] NASA Exoplanet Archive: {type(e).__name__}: {e}")
        pi_men = [x for x in el if x[0] == "TIC 261136679"]
        if pi_men:
            t0 = time.time()
            try:
                riga, cand = M.lavora_stella("tess2", "s0001", pi_men[0][0], pi_men[0][1], d, n, max(1, n_nuclei()))
                c = cand[0] if cand else None
                out.append(f"[ok] TESS pi Mensae (pianeta c, 6,27 g): trovato periodo {riga['periodo_migliore']} g, "
                           f"SDE {riga['sde_migliore']}, motore {riga['motore']}, confronto "
                           f"{c['noto'] if c else '-'} ({time.time() - t0:.0f} s)")
            except Exception as e:
                out.append(f"[ERRORE] TESS pi Mensae: {type(e).__name__}: {e}")
        t0 = time.time()
        try:
            urls = M.file_kepler(M.URL_KEPLER + "0119/011904151/")
            loc = []
            for u in urls[:4]:
                loc.append(M.scarica_file(u, d / u.split("/")[-1]))
            t, f, e, info = M.leggi_curva(loc)
            pul, seg = M.analizza_stella(t, f, e, info, max(1, n_nuclei()))
            out.append(f"[ok] Kepler-10 (pianeta b, 0,837 g; 4 trimestri): trovato periodo "
                       f"{seg[0]['periodo']:.4f} g, SDE {seg[0]['sde']:.1f} ({time.time() - t0:.0f} s)")
        except Exception as e:
            out.append(f"[ERRORE] Kepler: {type(e).__name__}: {e}")
        t0 = time.time()
        try:
            c = M.campagne_k2()
            out.append(f"[ok] K2: campagne {', '.join(c[:6])}… ({len(c)}) ({time.time() - t0:.0f} s)")
        except Exception as e:
            out.append(f"[ERRORE] K2: {type(e).__name__}: {e}")
        t0 = time.time()
        try:
            from astroquery.mast import Observations
            obs = Observations.query_criteria(provenance_name="TESS-SPOC", sequence_number=1,
                                              dataproduct_type="timeseries")
            out.append(f"[ok] TESS-SPOC settore 1: {len(obs)} curve dalle immagini a campo intero ({time.time() - t0:.0f} s)")
        except Exception as e:
            out.append(f"[ERRORE] TESS-SPOC: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


def _curva_fits(percorso, t, f, e, tic=123456789):
    from astropy.io import fits
    import numpy as np
    cols = [fits.Column(name="TIME", format="D", array=t), fits.Column(name="PDCSAP_FLUX", format="E", array=f * 5000),
            fits.Column(name="PDCSAP_FLUX_ERR", format="E", array=e * 5000),
            fits.Column(name="QUALITY", format="J", array=np.zeros(len(t), int))]
    hp = fits.Header()
    hp.update(TELESCOP="TESS", TICID=tic, RA_OBJ=120.0, DEC_OBJ=-30.0, TESSMAG=10.5, TEFF=5700.0, RADIUS=1.0)
    fits.HDUList([fits.PrimaryHDU(header=hp), fits.BinTableHDU.from_columns(cols, name="LIGHTCURVE")]
                 ).writeto(percorso, overwrite=True)


def autotest():
    import tempfile
    import numpy as np
    print(f"AUTOTEST {NOME} {M.VERSIONE} - {M.COPYRIGHT}")
    ok = True

    def v(c, t):
        nonlocal ok
        print(("[ok] " if c else "[ERRORE] ") + t, flush=True)
        ok &= bool(c)

    global FILE_CONFIG
    d = Path(tempfile.mkdtemp(prefix="autotest_exo_"))
    try:
        motore = M.motore_ricerca()
        print(f"[info] motore di ricerca disponibile: {motore}")
        t, f, e = M.curva_sintetica()
        t0 = time.time()
        pul, seg = M.analizza_stella(t, f, e, {"raggio_stella": 1.0}, n_nuclei(), motore)
        s = seg[0]
        v(abs(s["periodo"] / 3.2 - 1) < 0.01 and s["superato"],
          f"transito simulato ritrovato con {s['motore']}: periodo {s['periodo']:.4f} g (vero 3.2), "
          f"profondità {s['profondita'] * 1e6:.0f} ppm (vera 1500), SDE {s['sde']:.1f} ({time.time() - t0:.0f} s)")
        v(len(seg) == 1 or not seg[1]["superato"], "nessun secondo pianeta inventato")
        tb, fb, eb = M.curva_sintetica(periodo=2.0, profondita=0.0, seme=3)
        fase = ((tb - 1500.7) / 2.0 + 0.5) % 1 - 0.5
        fb[np.abs(fase) * 2.0 < 0.06] -= 0.02
        fb[np.abs(np.abs(fase) - 0.5) * 2.0 < 0.06] -= 0.006               # eclisse secondaria: binaria
        _, segb = M.analizza_stella(tb, fb, eb, {"raggio_stella": 1.0}, n_nuclei(), motore)
        v(segb and any("secondaria" in a for a in segb[0]["avvisi"]),
          f"binaria a eclisse riconosciuta: {segb[0]['avvisi'] if segb else '-'}")
        p = d / "tess2018206045859-s0001-0000000123456789-0120-s_lc.fits"
        _curva_fits(p, t, f, e)
        t2, f2, e2, info = M.leggi_curva([p])
        v(len(t2) == len(t) and abs(info["mag"] - 10.5) < 1e-6 and info["raggio_stella"] == 1.0,
          f"lettura di una curva di luce FITS ({len(t2)} punti, informazioni sulla stella)")
        (d / M.CARTELLA_CATALOGHI).mkdir()
        (d / M.CARTELLA_CATALOGHI / "toi.csv").write_text(
            "toi,tid,tfopwg_disp,pl_orbper,ra,dec\n700.01,999,PC,6.0,10,10\n", encoding="utf-8")
        noti = M.Noti(d)
        riga, cand = M.lavora_stella("tess2", "s0001", "TIC 123456789", p.as_uri(), d, noti, n_nuclei(), motore)
        v(cand and cand[0]["noto"][0] == "nuovo" and (Path(cand[0]["cartella"]) / "scheda.pdf").exists(),
          "stella completa: download, analisi, candidato nuovo con grafici e scheda PDF")
        v(not (d / M.CARTELLA_DOWNLOAD / "TIC_123456789").exists(), "FITS scaricati cancellati dopo l'analisi")
        v(noti.confronta("TIC 999", 10, 10, 12.0)[0] == "noto", "confronto con i pianeti noti (anche periodo doppio)")
        st = M.Stato(d)
        st.segna("tess2", "s0001", "TIC 123456789", "prova")
        v("TIC 123456789" in M.Stato(d).fatte("tess2", "s0001"), "stato salvato: si riprende da dove ci si era fermati")
        lista = M.stelle_tess_2min.__doc__
        v(bool(lista), "funzioni degli archivi presenti")
        FILE_CONFIG = d / "cfg.json"
        salva_config({"cartella": str(d)})
        M.aggiungi_csv(d / M.FILE_CANDIDATI, M.riga_candidato(cand[0]))
        app = App()
        app.geometry("1280x800+0+0")
        app.update()
        time.sleep(0.3)
        app.update()
        menu = app.nametowidget(app.cget("menu"))
        voci = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "cascade"]
        v(voci == ["File", "Ricerca", "Opzioni", "Informazioni"] and len(app._righe) == 1,
          f"finestra: menu {' / '.join(voci)}, {len(app._righe)} candidato in tabella")
        app.tab.selection_set(app.tab.get_children()[0])
        app.update()
        app._mostra_grafico()
        v(app._foto is not None, "grafici del candidato mostrati nella finestra")
        app.destroy()
    except Exception:
        traceback.print_exc()
        ok = False
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("AUTOTEST SUPERATO" if ok else "AUTOTEST FALLITO")
    return 0 if ok else 1


def diagnostica():
    print(f"DIAGNOSTICA {NOME} - {datetime.now():%Y-%m-%d %H:%M}  (motore: {M.motore_ricerca()})")
    for r in prova_servizi():
        print(r, flush=True)
    return 0


def _uscita_testo(nome):
    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        sys.stdout = sys.stderr = open(Path.cwd() / f"{nome}_risultato.txt", "w", encoding="utf-8", buffering=1)


def main():
    if "--autotest" in sys.argv:
        _uscita_testo("autotest")
        sys.exit(autotest())
    if "--diagnostica" in sys.argv:
        _uscita_testo("diagnostica")
        sys.exit(diagnostica())
    if getattr(sys, "frozen", False) or sys.stderr is None:
        try:
            log = open(Path.home() / ".exoplanet_searcher.log", "a", encoding="utf-8", buffering=1)
            log.write(f"\n--- avvio {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
            sys.stdout = sys.stderr = log
        except OSError:
            sys.stdout = sys.stderr = open(os.devnull, "w")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
