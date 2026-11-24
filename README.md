# Exoplanet Searcher

*Automatic transit search in TESS, Kepler and K2 light curves, star after star*

Runs on its own while the computer is on: downloads a star's light curve, searches for planetary transits with Transit Least Squares, checks for false positives and already-known planets, saves the results, deletes the FITS files and moves to the next star. It can run as a low-priority Docker service on a NAS (`nas/`), with the desktop app used only to look at the results.

## Features

* TESS, Kepler and K2 light curves from MAST (lightkurve-free, via astroquery)
* Transit Least Squares, odd/even and secondary-eclipse checks, comparison with the NASA Exoplanet Archive
* Candidate cards (`grafici.png`, `scheda.pdf`) in English, ready to attach to a report
* Waits and retries when the Internet is down; NAS mode shows progress in the desktop app

> **Language note.** The interface is in **Italian** (large, adjustable text); plots, PDF/PNG cards and scientific output are in **English**. Code comments are in Italian. The original Italian guide is [`LEGGIMI.txt`](LEGGIMI.txt).

**Version:** 1.1 (2026-11-04). **Status:** Stable: running on a NAS since 4 Nov 2026.

## Quick start

Requirements: Python 3.10+ (tested with Python 3.14 on Ubuntu) with `tkinter` (Ubuntu: `sudo apt install python3-tk`) and Docker for the server part.

```bash
git clone https://github.com/EDOKILLER/exoplanet-searcher.git
cd exoplanet-searcher
python3 -m pip install -r requirements.txt

python3 exoplanet_searcher.py --autotest
python3 nas/servizio_exo.py --prova
python3 exoplanet_searcher.py        # opens the window
```

### Standalone executable

`bash crea_eseguibile_ubuntu.sh` builds a single-file executable with PyInstaller in a temporary virtual environment, runs the self-test, and adds the program with its icon to the application menu and the desktop (first time on GNOME: right-click → *Allow launching*). On Windows 11 install Python from python.org (tick *Add python.exe to PATH*) and double-click `crea_eseguibile_windows.bat`.

The build scripts were written for the author's machine: check the paths at the top before running them.

### Server / NAS part

The `nas/` folder runs in a `python:3.12` Docker container (tested on a UGREEN NAS with UGOS Docker, any Linux box works). Copy the files into the shared folder, edit the volume path in `nas/docker-compose.yml`, and deploy it; the container installs its libraries on first start and runs at the lowest CPU and disk priority. Step-by-step Italian instructions: `nas/LEGGIMI_NAS.txt`.

## Data sources and acknowledgements

Data are downloaded at run time from public services. If you publish results, please follow their acknowledgement policies:

* [Mikulski Archive for Space Telescopes (STScI): Hubble, JWST, Kepler, TESS, GALEX, Pan-STARRS](https://archive.stsci.edu/)
* [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/)

This project is independent and not endorsed by any of these institutions.

## License

Code: [BSD 3-Clause](LICENSE) © 2026 Edoardo Battistel. You can use, modify and redistribute it, also commercially, as long as you keep the copyright notice; the author's name may not be used to promote derived works without permission. If you use it in research, see [`CITATION.cff`](CITATION.cff).

---
Part of a series of astronomy programs by Edoardo Battistel — see also [X-rays from Black Holes](https://github.com/EDOKILLER/x-rays-from-black-holes) and the other repositories on [this profile](https://github.com/EDOKILLER?tab=repositories).
