"""Dauerhafter Speicher für Embeddings: jeder Text wird pro Modell nur einmal umgewandelt und bezahlt.

Gilt für alle Profile (dieselbe Anzeige ergibt denselben Vektor) und liegt in data/vektoren/<modell>.npz.
Gespeichert wird in halber Genauigkeit (float16): für Kosinus-Vergleiche reicht das und halbiert die Grösse.
"""
import hashlib
import re
import threading

import numpy as np

from src import config

FOLDER_NAME = "vektoren"
MAX_ENTRIES = 60000  # pro Modell ca. 180 MB bei 1536 Dimensionen; älteste Einträge fallen zuerst weg

_lock = threading.RLock()
_stores: dict[str, dict[str, np.ndarray]] = {}
_loaded_root = None


def folder():
    return config.DATA_ROOT / FOLDER_NAME


def path(model: str):
    return folder() / (re.sub(r"[^A-Za-z0-9._-]+", "_", model) + ".npz")


def key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]


def _load(model: str) -> dict[str, np.ndarray]:
    global _loaded_root
    if _loaded_root != folder():  # anderer Datenordner (Tests): alles neu lesen
        _stores.clear()
        _loaded_root = folder()
    if model not in _stores:
        store = {}
        try:
            with np.load(path(model), allow_pickle=False) as data:
                keys, matrix = data["keys"], data["vectors"]
                store = {str(k): matrix[i] for i, k in enumerate(keys)}
        except (OSError, KeyError, ValueError):
            pass  # fehlt oder beschädigt: wird neu aufgebaut
        _stores[model] = store
    return _stores[model]


def get(model: str, texts: list[str]) -> dict[str, np.ndarray]:
    """Bekannte Vektoren als {text: vektor}."""
    with _lock:
        store = _load(model)
        found = {}
        for text in texts:
            vector = store.get(key(text))
            if vector is not None:
                found[text] = vector
        return found


def put(model: str, vectors: dict[str, list[float]]) -> None:
    if not vectors:
        return
    with _lock:
        store = _load(model)
        for text, vector in vectors.items():
            k = key(text)
            store.pop(k, None)  # neu einfügen = ans Ende (jüngster Eintrag)
            store[k] = np.asarray(vector, dtype=np.float16)
        for k in list(store)[:max(0, len(store) - MAX_ENTRIES)]:
            del store[k]
        _save(model, store)


def _save(model: str, store: dict) -> None:
    keys = list(store)
    target = path(model)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.stem + ".tmp.npz")
    np.savez(temporary, keys=np.array(keys), vectors=np.stack([store[k] for k in keys]))
    temporary.replace(target)


def count(model: str) -> int:
    with _lock:
        return len(_load(model))
