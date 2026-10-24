#!/bin/bash
# Bewerbungs-Tool für macOS: Doppelklick startet das Tool, beim ersten Mal mit Einrichtung.
cd "$(dirname "$0")" || exit 1

fehler() {
    echo
    echo "$1"
    read -r -p "Enter drücken zum Schliessen ..."
    exit 1
}

if [ ! -f .venv/installiert.ok ]; then
    PY=""
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>/dev/null; then
            PY="$c"
            break
        fi
    done
    [ -n "$PY" ] || fehler "Python 3.10 oder neuer wurde nicht gefunden. Bitte von https://www.python.org/downloads/ installieren und start.command erneut öffnen."

    echo "Erster Start: Das Programm wird eingerichtet. Das dauert einige Minuten und braucht Internet."
    [ -x .venv/bin/python ] || "$PY" -m venv .venv || fehler "Die Einrichtung ist fehlgeschlagen."
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt || fehler "Die Einrichtung ist fehlgeschlagen. Internetverbindung prüfen und erneut starten."
    echo ok > .venv/installiert.ok
fi

[ -f .env ] || cp .env.example .env
echo "Bewerbungs-Tool startet. Dieses Fenster offen lassen; Schliessen beendet das Programm."
(sleep 5; open http://localhost:8501) &
exec .venv/bin/python -m streamlit run app.py --server.headless true --server.port 8501
