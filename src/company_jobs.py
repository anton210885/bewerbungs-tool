"""Stufe 2: Stellen auf den Karriereseiten der Firmen finden, vorsortieren und die besten bewerten.

Ablauf (jeder Schritt einzeln aufrufbar):
1. collect_all   – Karriereseiten lesen, Links zu einzelnen Stellen erkennen (strukturierte Daten, sonst KI)
2. load_details  – Anzeigentexte neuer Stellen laden (ohne KI)
3. rank_open     – nach Ähnlichkeit mit den eigenen Aufgaben sortieren (Embeddings, sehr günstig)
4. evaluate_best – nur die besten mit dem Profil bewerten (KI, ca. 3 Rappen pro Stelle)
Bereits bekannte Stellen werden nie zweimal bewertet; verworfene kommen nicht wieder.
"""
import hashlib
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlsplit

import requests

from src import companies, config, db, discovery, jobs, scraper, task_search

WORKERS = 6
EVAL_WORKERS = 4
MAX_LINKS = 250
MAX_DETAILS = 400  # pro Lauf; vielversprechende Titel zuerst
MIN_TEXT = 150
SKIP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".doc", ".docx", ".mp4", ".ics")

STATUS = {
    "neu": "neu",
    "bewertet": "bewertet",
    "verworfen": "interessiert nicht",
    "übernommen": "im Tracker",
    "ausgeschlossen": "ausgeschlossen (Suchwunsch)",
    "zu_weit": "zu weit entfernt",
}
OPEN = ("neu", "bewertet")
# Vom Tool gesetzt (nicht von dir): verschwinden, wenn die Firma die Stelle nicht mehr ausschreibt
AUTOMATIC = OPEN + ("ausgeschlossen", "zu_weit")
# Typische Merkmale eines Stellentitels: «(m/w/d)», «Monteur*in», «80–100 %»
JOB_MARKER = re.compile(r"\((?:[mwfdx]\s*/\s*){1,3}[mwfdx]\)|\b[mwf]/[mwf](?:/[dx])?\b|\w\*in\b|\w/in\b|all genders|"
                        r"\b\d{2,3}\s*(?:[-–]|bis)\s*\d{2,3}\s*%|\b\d{2,3}\s*%(?!\s*rabatt)", re.I)
NO_JOB = re.compile(r"rabatt|\baktion|\bsale\b|zins|rendite|skonto|lehrstellen-?b|schnupper", re.I)


# ---------------------------------------------------------------- Speicherung

def store_path():
    return config.data_dir() / "firmen_stellen.json"


def load() -> dict:
    path = store_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("stellen"), dict):
                return data
        except (ValueError, OSError):
            pass
    return {"zeit": "", "stellen": {}}


def save(store: dict) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


# ---------------------------------------------------------------- Stellen auf einer Karriereseite

def clean_text(text: str) -> str:
    text = re.sub(r"\{[^{}]*\}", " ", text or "")  # Reste von Inline-CSS
    return " ".join(text.split())[:160]


def candidate_links(html: str, base: str) -> list[tuple[str, str]]:
    seen, result = set(), []
    for url, text in companies.links(html, base):
        text = clean_text(text)
        lowered = url.lower()
        if (len(text) < 4 or urlsplit(url).scheme not in ("http", "https") or url in seen
                or url.rstrip("/") == base.rstrip("/") or lowered.split("?")[0].endswith(SKIP_EXTENSIONS)):
            continue
        seen.add(url)
        result.append((url, text))
    return result[:MAX_LINKS]


def links_hash(links: list[tuple[str, str]]) -> str:
    return hashlib.sha1("\n".join(f"{u}|{t}" for u, t in links).encode("utf-8")).hexdigest()[:16]


def _job(company: dict, url: str, title: str, location: str = "", description: str = "") -> dict:
    return {"url": url, "title": " ".join((title or "").split())[:200] or jobs.title_from_url(url),
            "company": company["name"], "website": company["website"], "karriere": company.get("karriere", ""),
            "location": location or "", "description": description or "", "status": "neu", "gefunden": _now()}


def jobs_from_jsonld(html: str, page_url: str, company: dict) -> list[dict]:
    items = []
    for posting in scraper._postings(html):
        meta = scraper._metadata(posting)
        url = posting.get("url") if isinstance(posting.get("url"), str) else ""
        # Mehrere Anzeigen ohne eigene Adresse auf derselben Seite auseinanderhalten
        url = url or f"{page_url}#{re.sub(r'[^a-z0-9]+', '-', meta['title'].casefold()).strip('-')}"
        items.append(_job(company, url, meta["title"], meta["location"], meta["description"]))
    return items


def _choose(links):
    from src.batch import choose_job_links
    return choose_job_links(links)


def collect_company(company: dict, session, robots, choose=_choose) -> dict:
    """-> {stellen: [...] | None (unverändert), hinweis, links_hash}. Folgt höchstens einem Link «Offene Stellen»."""
    url, visited, first_digest = company["karriere"], set(), ""
    for _ in range(2):
        if not robots.allowed(url):
            return {"stellen": [], "hinweis": "Abruf nicht erlaubt (robots.txt)", "links_hash": ""}
        html, final = companies._get(session, url)
        if html is None:
            return {"stellen": [], "hinweis": "Karriereseite nicht lesbar", "links_hash": ""}
        visited.add(companies.normalize_website(final))
        found = jobs_from_jsonld(html, final, company)
        if found:
            return {"stellen": found, "hinweis": "", "links_hash": ""}
        links = candidate_links(html, final)
        digest = links_hash(links)
        first_digest = first_digest or digest
        if digest == company.get("links_hash"):
            # Seite unverändert seit dem letzten Lauf: keine KI nötig, bekannte Stellen bleiben
            return {"stellen": None, "hinweis": company.get("stellen_hinweis", ""), "links_hash": digest}
        if len(links) >= 3:
            found = [_job(company, j["url"], j["title"], j.get("location", "")) for j in choose(links)]
            known = {j["url"] for j in found}
            # Was die KI übersieht, aber eindeutig wie ein Stellentitel aussieht, trotzdem aufnehmen
            found += [_job(company, u, t) for u, t in links
                      if u not in known and 10 <= len(t) <= 160 and JOB_MARKER.search(t) and not NO_JOB.search(t)]
            if found:
                return {"stellen": found, "hinweis": "", "links_hash": digest}
        hop = companies.best_career_link(html, final)
        if not hop or companies.normalize_website(hop) in visited:
            break
        url = hop
    return {"stellen": [], "hinweis": "Keine Stellen erkannt – vielleicht gerade keine offen, oder die Seite wird "
                                      "erst im Browser aufgebaut.", "links_hash": first_digest}


def _exclude_terms(preferences: dict) -> list[str]:
    return [t.strip().casefold() for t in str(preferences.get("exclude") or "").split(",") if t.strip()]


def merge(store: dict, company: dict, found: list[dict], exclude=(), tracked=frozenset()) -> int:
    """Neue Stellen einer Firma aufnehmen, nicht mehr ausgeschriebene offene entfernen. -> Anzahl neu."""
    current = {j["url"] for j in found}
    for url, job in list(store["stellen"].items()):
        if job.get("website") == company["website"] and url not in current and job.get("status") in AUTOMATIC:
            del store["stellen"][url]
    added = 0
    for job in found:
        if job["url"] in store["stellen"]:
            continue
        if job["url"] in tracked:
            job["status"] = "übernommen"
        elif any(term in job["title"].casefold() for term in exclude):
            job["status"] = "ausgeschlossen"
        else:
            added += 1
        store["stellen"][job["url"]] = job
    return added


def collect_all(data: dict, store: dict, preferences: dict | None = None, on_progress=None, choose=_choose,
                workers: int = WORKERS) -> dict:
    targets = [c for c in data["firmen"] if c.get("karriere") and not c.get("ausgeblendet")]
    exclude = _exclude_terms(preferences or {})
    tracked = frozenset(a["url"] for a in db.list_applications() if a.get("url"))
    session = companies._session()
    robots = companies._Robots(session)
    counts = {"firmen": len(targets), "mit_stellen": 0, "neu": 0, "fehler": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        known = {}
        for job in store["stellen"].values():
            known[job.get("website")] = known.get(job.get("website"), 0) + 1
        for company in targets:
            # Fehlen bekannte Stellen (z.B. Liste gelöscht oder aus Sicherung), Seite trotz gleichem Inhalt neu lesen
            if known.get(company["website"], 0) < (company.get("stellen_anzahl") or 0):
                company.pop("links_hash", None)
        futures = {pool.submit(collect_company, c, session, robots, choose): c for c in targets}
        for done, future in enumerate(as_completed(futures), 1):
            company = futures[future]
            try:
                result = future.result()
            except Exception as error:  # Firma bleibt mit alten Stellen stehen
                counts["fehler"] += 1
                company.update(stellen_hinweis=f"Fehler: {str(error)[:150]}", stellen_geprueft=_now())
                result = None
            if result is not None:
                if result["stellen"] is not None:
                    counts["neu"] += merge(store, company, result["stellen"], exclude, tracked)
                    company["stellen_anzahl"] = len(result["stellen"])
                company.update(stellen_hinweis=result["hinweis"], links_hash=result["links_hash"],
                               stellen_geprueft=_now())
            if company.get("stellen_anzahl"):
                counts["mit_stellen"] += 1
            if on_progress:
                on_progress(done, len(targets), company)
    store["zeit"] = _now()
    companies.save(data)
    save(store)
    return counts


# ---------------------------------------------------------------- Anzeigentexte und Vorsortierung

def _pdf_text(session, url: str) -> str:
    import pymupdf
    response = session.get(url, timeout=20)
    response.raise_for_status()
    with pymupdf.open(stream=response.content, filetype="pdf") as pdf:
        return "\n".join(page.get_text() for page in pdf)[:15000]


def _detail(job: dict, session, robots) -> dict:
    if not robots.allowed(job["url"]):
        return {"detail_fehler": "Abruf nicht erlaubt (robots.txt)"}
    if urlsplit(job["url"]).path.lower().endswith(".pdf"):
        text = _pdf_text(session, job["url"])
        return {"description": text} if len(text) >= MIN_TEXT else {"detail_fehler": "PDF ohne lesbaren Text"}
    details = jobs.fetch_job(job["url"])
    if details["thin"]:
        return {"detail_fehler": "kaum Anzeigentext (Seite wird vermutlich erst im Browser aufgebaut)"}
    result = {"description": details["description"]}
    if details.get("location") and (not job.get("location") or job.get("ort_quelle") == "Firmensitz"):
        result.update(location=details["location"], ort_quelle="Anzeige")
    return result


def missing_details(store: dict) -> list[dict]:
    """Offene Stellen, von denen nur der Titel bekannt ist (und deren Abruf nicht schon gescheitert ist)."""
    return [j for j in store["stellen"].values()
            if j["status"] == "neu" and len(j.get("description", "")) < MIN_TEXT and not j.get("detail_fehler")]


def load_details(store: dict, profile: dict, tasks=None, on_progress=None, limit: int = MAX_DETAILS,
                 workers: int = WORKERS) -> int:
    todo = missing_details(store)
    if len(todo) > limit:  # vielversprechende Titel zuerst laden
        todo = task_search.rank(profile, todo, tasks)[:limit]
    session = companies._session()
    robots = companies._Robots(session)
    loaded = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_detail, job, session, robots): job for job in todo}
        for done, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            try:
                job.update(future.result())
            except (requests.RequestException, ValueError, RuntimeError) as error:
                job["detail_fehler"] = f"nicht abrufbar ({str(error)[:100]})"
            except Exception as error:  # einzelne Anzeige darf den Lauf nicht abbrechen
                job["detail_fehler"] = str(error)[:120]
            loaded += "description" in job and len(job["description"]) >= MIN_TEXT
            if on_progress:
                on_progress(done, len(todo), job)
    save(store)
    return loaded


def comparison_tasks(preferences: dict) -> list[str] | None:
    """Gewählte Tätigkeitsfelder aus der Aufgaben-Suche; sonst alle Aufgaben aus dem Profil."""
    fields = preferences.get("task_fields") or []
    return task_search.selected_tasks(fields, preferences.get("selected_fields") or []) or None


def rank_open(store: dict, profile: dict, tasks=None) -> None:
    items = [j for j in store["stellen"].values() if j["status"] in OPEN]
    task_search.rank(profile, items, tasks)
    save(store)


# ---------------------------------------------------------------- Ort aus dem Anzeigentext

_LABEL_PATTERN = (r"\b(?:Arbeitsort|Standort|Einsatzort|Arbeitsplatz|Dienstort|Arbeitsstandort|Location|Workplace|"
                  r"Lieu de travail)\b\s*[:：]\s*([^\n|•;]{2,60})")
_LABEL = re.compile(_LABEL_PATTERN, re.I)
_TOWN = r"(?:St\.\s?)?[A-ZÄÖÜ][a-zäöüéèàâ]+(?:[- ][A-ZÄÖÜ][a-zäöüéèàâ]+)?"  # auch «St. Gallen»
_CANTON = r"(?:\s(?:AG|SO|ZH|LU|BE|SG|TG|ZG|BL|BS|SZ|FR|VS|GR|TI|NE|VD|GE|JU|SH|AR|AI|GL|NW|OW|UR)\b)?"
# «5033 Buchs AG», «CH-8957 Spreitenbach», «87787 Wolfertschwenden» (deutsche PLZ verrät Stellen im Ausland)
_POSTCODE = re.compile(rf"(?<![\d.,'’])(CH-?\s?|D-?\s?)?\b(\d{{4,5}})\s+({_TOWN}{_CANTON})")
_NOT_TOWN = {"mitarbeitende", "mitarbeiter", "mitarbeiterinnen", "franken", "chf", "stunden", "kunden", "personen",
             "angestellte", "employees", "stellen", "standorten", "standorte", "länder", "ländern", "mal", "jahre",
             "jahren", "mitglieder", "fachkräfte", "projekte", "tonnen", "quadratmeter", "lernende", "teilnehmende",
             "menschen", "betriebe", "filialen", "kilometer", "einwohner"}
_CONNECTORS = {"bei", "am", "an", "der", "im", "sur", "sous", "de"}


def _looks_like_place(value: str) -> bool:
    words = value.replace(",", " ").split()
    return (0 < len(words) <= 4 and (value[0].isupper() or value[0].isdigit())
            and all(w[0].isupper() or w[0].isdigit() or w in _CONNECTORS or w.isupper() for w in words))


def location_from_text(text: str) -> str:
    """Arbeitsort aus dem Anzeigentext: ausdrückliche Angabe («Arbeitsort: Aarau»), sonst erste Postleitzahl mit Ort.
    Ob es den Ort gibt, prüft danach das Nachschlagen (apply_distance)."""
    for match in _LABEL.finditer(text or ""):
        value = re.split(r"\s[-–]\s|\.\s", match.group(1))[0].strip(" .,-")
        if _looks_like_place(value):
            return value
    for match in _POSTCODE.finditer(text or ""):
        prefix, number, town = match.groups()
        if town.split()[0].casefold() in _NOT_TOWN:
            continue
        if len(number) == 4 and 1900 <= int(number) <= 2100 and not prefix:  # eher eine Jahreszahl
            continue
        return f"{number} {town}"
    return ""


def fill_locations(store: dict, data: dict | None = None) -> int:
    """Fehlende Orte ergänzen: aus dem Anzeigentext, sonst der Ort der Firma (als «Firmensitz» markiert).
    -> Anzahl ergänzter Stellen."""
    towns = {c.get("website"): c.get("ort") for c in (data or {}).get("firmen", []) if c.get("ort")}
    filled = 0
    for job in store["stellen"].values():
        if job.get("location") and job.get("ort_quelle") != "Firmensitz":
            continue
        found = location_from_text(job.get("description", ""))
        if found:
            job.update(location=found, ort_quelle="Anzeigentext")
            job.pop("distanz_km", None)
            filled += 1
        elif not job.get("location") and towns.get(job.get("website")):
            job.update(location=towns[job["website"]], ort_quelle="Firmensitz")
            filled += 1
    save(store)
    return filled


# ---------------------------------------------------------------- Entfernung

NOT_A_PLACE = re.compile(r"^(nicht angegeben|unbekannt|diverse|verschiedene|mehrere|remote|home ?office|-)$", re.I)
GEO_WAIT = 1.1  # Nominatim erlaubt höchstens eine Anfrage pro Sekunde
MAX_LOOKUPS = 150


def geo_cache_path():
    return config.DATA_ROOT / "orte.json"  # Ortsnamen sind keine persönlichen Daten: für alle Personen gemeinsam


def _load_geo_cache() -> dict:
    try:
        return json.loads(geo_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def place_key(location: str) -> str:
    """Erster Ort einer Angabe wie «5033 Buchs AG, Schweiz» oder «Aarau / Zürich»."""
    first = re.split(r"[;/|]| und | oder ", location or "")[0].strip(" ,")
    return "" if not first or NOT_A_PLACE.match(first) or len(first) < 2 else first.casefold()


def _lookup(session, place: str, center: tuple[float, float]):
    """Ohne Länderbeschränkung (sonst würde «München» in der Schweiz gesucht). Bei gleichnamigen Orten
    (Muri AG / Muri bei Bern) gilt der nächstgelegene: im Zweifel bleibt eine Stelle sichtbar."""
    lat, lon = center
    response = session.get(companies.NOMINATIM_URL, timeout=companies.TIMEOUT, params={
        "q": place, "format": "json", "limit": 5,
        "viewbox": f"{lon - 1.5},{lat + 1},{lon + 1.5},{lat - 1}", "bounded": 0})
    response.raise_for_status()
    points = [(float(h["lat"]), float(h["lon"])) for h in response.json()]
    return list(min(points, key=lambda p: distance_km(center, p))) if points else None


def apply_distance(store: dict, center: tuple[float, float], max_km: float, session=None, on_progress=None,
                   sleep=time.sleep) -> int:
    """Entfernung je Stelle eintragen; zu weit entfernte offene Stellen ausblenden. -> Anzahl ausgeblendet.
    Stellen ohne Ortsangabe bleiben (unbekannt ist nicht weit weg)."""
    cache = _load_geo_cache()
    session = session or companies._session()
    relevant = OPEN + ("zu_weit",)
    pending = sorted({place_key(j.get("location", "")) for j in store["stellen"].values()
                      if j["status"] in relevant} - set(cache) - {""})[:MAX_LOOKUPS]
    for done, place in enumerate(pending, 1):
        try:
            cache[place] = _lookup(session, place, center)
        except (requests.RequestException, ValueError, KeyError):
            continue  # beim nächsten Lauf erneut versuchen
        if on_progress:
            on_progress(done, len(pending), place)
        if done < len(pending):
            sleep(GEO_WAIT)
    if pending:
        geo_cache_path().parent.mkdir(parents=True, exist_ok=True)
        geo_cache_path().write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    hidden = 0
    for job in store["stellen"].values():
        point = cache.get(place_key(job.get("location", "")))
        if job["status"] not in relevant or not point:
            continue
        job["distanz_km"] = round(distance_km(center, tuple(point)))
        if job["distanz_km"] > max_km and job["status"] == "neu":
            job["status"] = "zu_weit"
            hidden += 1
        elif job["distanz_km"] <= max_km and job["status"] == "zu_weit":  # Umkreis vergrössert
            job["status"] = "neu"
    save(store)
    return hidden


# ---------------------------------------------------------------- Bewertung

def open_jobs(store: dict) -> list[dict]:
    """Bewertete zuerst (nach Passung), dann nach Aufgaben-Nähe."""
    def order(job):
        match = job.get("aufgaben_match") or {}
        return ((job.get("analysis") or {}).get("score", -1), match.get("staerke", -1))
    return sorted((j for j in store["stellen"].values() if j["status"] in OPEN), key=order, reverse=True)


def next_candidates(store: dict, count: int) -> list[dict]:
    ready = [j for j in store["stellen"].values()
             if j["status"] == "neu" and len(j.get("description", "")) >= MIN_TEXT]
    ready.sort(key=lambda j: (j.get("aufgaben_match") or {}).get("staerke", -1), reverse=True)
    return ready[:count]


def evaluate_best(store: dict, profile: dict, count: int, wishes: str = "", on_progress=None) -> list[str]:
    chosen = next_candidates(store, count)
    errors = []
    with ThreadPoolExecutor(max_workers=EVAL_WORKERS) as pool:
        futures = {pool.submit(discovery.evaluate, profile, job, wishes): job for job in chosen}
        for done, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            try:
                job.update(analysis=future.result()["analysis"], status="bewertet", bewertet=_now())
            except Exception as error:
                errors.append(f"{job['title']}: {error}")
            if on_progress:
                on_progress(done, len(chosen), job)
    save(store)
    return errors


def set_status(store: dict, url: str, status: str) -> None:
    if url in store["stellen"] and status in STATUS:
        store["stellen"][url]["status"] = status
        save(store)
