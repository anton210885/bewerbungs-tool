"""Firmen in der Umgebung (OpenStreetMap) und ihre Karriereseiten finden. Ohne KI, ohne Kosten.

Stufe 1: Liste der Firmen mit Webseite und, wo möglich, die Adresse der Karriereseite.
Respektiert robots.txt und ruft pro Firma nur wenige Seiten ab.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests

from src import config

USER_AGENT = "Bewerbungs-Tool/0.5 (personal job search; respects robots.txt)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Öffentliche Overpass-Server; ist einer überlastet, wird der nächste versucht
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter")
MAX_RADIUS_KM = 50
WORKERS = 8
TIMEOUT = 15

# Anzeigename -> OSM-Filter (Schlüssel, Werte; None = jeder Wert)
BRANCHEN = {
    "IT & Software": [("office", ["it", "telecommunication"])],
    "Firmen allgemein": [("office", ["company", "yes"])],
    "Ingenieurwesen & Architektur": [("office", ["engineer", "architect", "surveyor", "geodesist"])],
    "Industrie & Produktion": [("industrial", None), ("man_made", ["works"])],
    "Finanzen, Treuhand & Versicherung": [("office", ["financial", "accountant", "tax_advisor", "insurance",
                                                      "financial_advisor"])],
    "Beratung & Dienstleistung": [("office", ["consulting", "advertising_agency", "employment_agency", "lawyer",
                                              "research", "logistics", "notary"])],
    "Verwaltung & Verbände": [("office", ["government", "association", "ngo", "educational_institution"])],
    "Gesundheit": [("amenity", ["hospital", "clinic"])],
    "Handwerk": [("craft", None)],
}
STANDARD_BRANCHEN = ["IT & Software", "Firmen allgemein", "Ingenieurwesen & Architektur", "Industrie & Produktion"]

STATUS = {
    "offen": "noch nicht geprüft",
    "gefunden": "Karriereseite gefunden",
    "keine": "keine Karriereseite gefunden",
    "gesperrt": "Abruf nicht erlaubt (robots.txt)",
    "fehler": "Webseite nicht erreichbar",
}

# Typische Bewerbungssysteme: ein Link dorthin ist fast sicher die Stellenseite
ATS_HOSTS = ("refline.ch", "personio.", "softgarden.", "successfactors.", "myworkdayjobs.", "workday.com",
             "prospective.ch", "umantis.", "abacuscity.ch", "rexx-systems.", "onlyfy.", "join.com",
             "ostendis.", "smartrecruiters.", "greenhouse.io", "lever.co", "recruitee.com", "jobs.ch/de/firma",
             "dvinci", "concludis.", "jobbase.io", "coveto.", "talentsoft.", "taleo.net", "jobylon.")
# \b vor «stellen»/«jobs», sonst zählt z.B. «Webseite erstellen»
KEYWORDS = re.compile(r"karriere|career|\bjobs?\b|\bstellen|vakanz|vacanc|arbeiten[- ]bei|arbeiten[- ]für|"
                      r"join[- ]us|offene[- ]positionen|mitarbeiten|work[- ]with[- ]us|emploi|lavora", re.I)
STRONG = re.compile(r"offene[- ]stellen|\bstellenangebote|\bjobs?\b|karriere|careers?", re.I)
NEGATIVE = re.compile(r"jobs?[- ]?ticket|newsletter|login|anmelden|\.pdf$|mailto:|tel:|"
                      r"karrieretag|blog/|news/|lehrstellen-?boerse", re.I)
COMMON_PATHS = ("/karriere", "/jobs", "/stellen", "/offene-stellen", "/de/karriere", "/de/jobs",
                "/careers", "/career", "/stellenangebote", "/ueber-uns/karriere", "/unternehmen/karriere")


# ---------------------------------------------------------------- Speicherung

def companies_path():
    return config.data_dir() / "firmen.json"


def load() -> dict:
    path = companies_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("firmen"), list):
                return data
        except (ValueError, OSError):
            pass
    return {"ort": "", "radius": 20, "branchen": list(STANDARD_BRANCHEN), "firmen": []}


def save(data: dict) -> None:
    path = companies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


# ---------------------------------------------------------------- Hilfen

def normalize_website(url: str) -> str:
    url = (url or "").strip().split(";")[0].strip()
    if not url:
        return ""
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    parts = urlsplit(url)
    if not parts.netloc or "." not in parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def full_url(url: str) -> str:
    """Adresse vollständig lassen (auch ?parameter), nur fehlendes https:// ergänzen."""
    url = (url or "").strip()
    if url and not re.match(r"https?://", url, re.I):
        url = "https://" + url
    return url


def domain(url: str) -> str:
    host = urlsplit(normalize_website(url)).netloc
    return host[4:] if host.startswith("www.") else host


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "de-CH,de;q=0.9,en;q=0.5"})
    return session


# ---------------------------------------------------------------- Firmen finden

def geocode(place: str, session=None) -> dict:
    """Ort -> {lat, lon, name}. Nur im eingestellten Land."""
    session = session or _session()
    try:
        response = session.get(NOMINATIM_URL, params={"q": place, "format": "json", "limit": 1,
                                                      "countrycodes": config.COUNTRY}, timeout=TIMEOUT)
        response.raise_for_status()
        hits = response.json()
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError(f"Ort konnte nicht nachgeschlagen werden: {error}") from error
    if not hits:
        raise ValueError(f"Ort «{place}» nicht gefunden.")
    return {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]), "name": hits[0].get("display_name", place)}


def overpass_query(lat: float, lon: float, radius_km: float) -> str:
    """Alle benannten Orte mit Webseite im Umkreis; die Branche filtert danach parse_overpass.
    Eine einfache Abfrage belastet die öffentlichen Server weniger als viele einzelne Filter."""
    radius = int(min(max(radius_km, 1), MAX_RADIUS_KM) * 1000)
    area = f"(around:{radius},{lat},{lon})"
    return f'[out:json][timeout:90];(nwr{area}["website"]["name"];nwr{area}["contact:website"]["name"];);out tags center;'


def _branche_of(tags: dict, branchen=None) -> str:
    for branche, filters in BRANCHEN.items():
        if branchen is not None and branche not in branchen:
            continue
        for key, values in filters:
            if key in tags and (values is None or tags[key] in values):
                return branche
    return ""


def parse_overpass(elements: list[dict], branchen=None) -> list[dict]:
    """Nur gewählte Branchen; ein Eintrag pro Webseite (Filialen derselben Firma werden zusammengefasst)."""
    found = {}
    for element in elements:
        tags = element.get("tags") or {}
        website = normalize_website(tags.get("website") or tags.get("contact:website") or "")
        name = (tags.get("name") or "").strip()
        branche = _branche_of(tags, branchen)
        if not website or not name or not branche:
            continue
        key = domain(website)
        if key in found:
            continue
        found[key] = {
            "name": name,
            "website": website,
            "branche": branche,
            "ort": tags.get("addr:city") or tags.get("addr:place") or "",
            "quelle": "OpenStreetMap",
            "karriere": "",
            "status": "offen",
            "geprueft": "",
            "ausgeblendet": False,
        }
    return sorted(found.values(), key=lambda c: c["name"].casefold())


def find_companies(place: str, radius_km: float, branchen: list[str], session=None) -> list[dict]:
    if not branchen:
        raise ValueError("Bitte mindestens eine Branche wählen.")
    session = session or _session()
    location = geocode(place, session)
    query = overpass_query(location["lat"], location["lon"], radius_km)
    elements, last_error = None, None
    for url in OVERPASS_URLS:
        for attempt in range(2):
            try:
                response = session.post(url, data={"data": query}, timeout=90)
                if response.status_code in (429, 502, 503, 504) and attempt == 0:
                    time.sleep(5)  # Server kurz ausgelastet
                    continue
                response.raise_for_status()
                elements = response.json().get("elements", [])
            except (requests.RequestException, ValueError) as error:
                last_error = error
            break
        if elements is not None:
            break
    if elements is None:
        raise RuntimeError("OpenStreetMap ist gerade nicht erreichbar, bitte in ein paar Minuten erneut versuchen "
                           f"({last_error}).") from last_error
    return parse_overpass(elements, branchen)


def merge(existing: list[dict], found: list[dict]) -> tuple[list[dict], int]:
    """Neue Firmen ergänzen; geprüfte, ausgeblendete und von Hand ergänzte bleiben erhalten."""
    by_domain = {domain(c["website"]): c for c in existing}
    added = 0
    for company in found:
        key = domain(company["website"])
        if key in by_domain:
            if not by_domain[key].get("branche"):
                by_domain[key]["branche"] = company["branche"]
            continue
        by_domain[key] = company
        added += 1
    return sorted(by_domain.values(), key=lambda c: c["name"].casefold()), added


def add_manual(data: dict, name: str, website: str, karriere: str = "") -> dict:
    website = normalize_website(website)
    if not website:
        raise ValueError("Bitte eine gültige Webseite angeben, z.B. www.firma.ch")
    if any(domain(c["website"]) == domain(website) for c in data["firmen"]):
        raise ValueError("Diese Firma steht schon in der Liste.")
    karriere = full_url(karriere)
    company = {"name": name.strip() or domain(website), "website": website, "branche": "", "ort": "",
               "quelle": "von Hand", "karriere": karriere, "status": "gefunden" if karriere else "offen",
               "geprueft": "", "ausgeblendet": False, "quelle_karriere": "von Hand" if karriere else ""}
    data["firmen"] = sorted(data["firmen"] + [company], key=lambda c: c["name"].casefold())
    return company


# ---------------------------------------------------------------- Karriereseite finden

class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._href, self._text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs = dict(attrs)
            self._href, self._text = attrs.get("href"), [attrs.get("title") or "", attrs.get("aria-label") or ""]

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None


def links(html: str, base: str) -> list[tuple[str, str]]:
    parser = _Links()
    try:
        parser.feed(html)
    except Exception:  # kaputtes HTML: verwerten, was gelesen wurde
        pass
    result = []
    for href, text in parser.links:
        if not href or href.startswith(("#", "javascript:")):
            continue
        result.append((urljoin(base, href).split("#")[0], text))
    return result


def _score(url: str, text: str, home_domain: str) -> int:
    if NEGATIVE.search(url) or NEGATIVE.search(text):
        return 0
    lowered = url.lower()
    if any(host in lowered for host in ATS_HOSTS):
        return 100
    target = domain(url)
    path = urlsplit(url).path
    score = 0
    if STRONG.search(text):
        score += 50
    elif KEYWORDS.search(text):
        score += 30
    if STRONG.search(path):
        score += 30
    elif KEYWORDS.search(path):
        score += 15
    if score and target != home_domain and not target.endswith("." + home_domain):
        score -= 10  # fremde Seite ohne bekanntes Bewerbungssystem: eher Partnerlink
    return score


def best_career_link(html: str, base: str) -> str:
    home = domain(base)
    scored = [(_score(url, text, home), -len(url), url) for url, text in links(html, base)]
    scored = [s for s in scored if s[0] >= 30 and normalize_website(s[2]) != normalize_website(base)]
    return max(scored)[2] if scored else ""


class _Robots:
    """robots.txt pro Domain einmal laden; ohne erreichbare Datei ist der Abruf erlaubt."""

    def __init__(self, session):
        self.session, self.cache, self.lock = session, {}, threading.Lock()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        with self.lock:
            parser = self.cache.get(root)
        if parser is None:
            parser = robotparser.RobotFileParser()
            try:
                response = self.session.get(root + "/robots.txt", timeout=TIMEOUT)
                parser.parse(response.text.splitlines() if response.status_code == 200 else [])
            except requests.RequestException:
                parser.parse([])
            with self.lock:
                self.cache[root] = parser
        return parser.can_fetch(USER_AGENT, url)


def _get(session, url):
    response = session.get(url, timeout=TIMEOUT)
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or ("html" not in content_type and content_type):
        return None, response.url
    return response.text, response.url


def find_career_page(website: str, session=None, robots=None) -> dict:
    """-> {karriere, status, hinweis}. Startseite lesen, sonst übliche Adressen probieren."""
    session = session or _session()
    robots = robots or _Robots(session)
    if not robots.allowed(website):
        return {"karriere": "", "status": "gesperrt", "hinweis": "Die Firma erlaubt das automatische Abrufen nicht."}
    try:
        html, final = _get(session, website)
    except requests.RequestException:
        return {"karriere": "", "status": "fehler", "hinweis": "Webseite nicht erreichbar."}
    if html is None:
        return {"karriere": "", "status": "fehler", "hinweis": "Startseite liefert keine lesbare Seite."}
    link = best_career_link(html, final)
    if link:
        return {"karriere": link, "status": "gefunden", "hinweis": ""}
    root = f"{urlsplit(final).scheme}://{urlsplit(final).netloc}"
    for path in COMMON_PATHS:
        candidate = root + path
        if not robots.allowed(candidate):
            continue
        try:
            page, landed = _get(session, candidate)
        except requests.RequestException:
            continue
        # Umleitung auf die Startseite oder eine Fehlerseite zählt nicht
        if page and normalize_website(landed) != normalize_website(root) and KEYWORDS.search(page[:20000]) \
                and not re.search(r"<title[^>]*>[^<]*(404|nicht gefunden|not found)", page, re.I):
            return {"karriere": landed, "status": "gefunden", "hinweis": "über eine übliche Adresse gefunden"}
    few_links = len(links(html, final)) < 5
    return {"karriere": "", "status": "keine",
            "hinweis": "Seite wird erst im Browser aufgebaut – bitte selbst ansehen." if few_links
            else "Kein Link zu Stellen gefunden – bitte selbst ansehen."}


def check_career_pages(data: dict, recheck: bool = False, on_progress=None, workers: int = WORKERS) -> dict:
    """Karriereseiten parallel suchen (verschiedene Firmen, pro Firma nacheinander). -> Zähler je Status."""
    # Von Hand eingetragene Karriereseiten werden nie überschrieben
    todo = [c for c in data["firmen"] if not c.get("ausgeblendet")
            and c.get("quelle_karriere") != "von Hand"
            and (recheck or c.get("status") == "offen")]
    session = _session()
    robots = _Robots(session)
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers * 2, pool_maxsize=workers * 2)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    counts = {key: 0 for key in STATUS}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(find_career_page, c["website"], session, robots): c for c in todo}
        for done, future in enumerate(as_completed(futures), 1):
            company = futures[future]
            try:
                result = future.result()
            except Exception as error:  # einzelne Firma darf den Lauf nicht abbrechen
                result = {"karriere": "", "status": "fehler", "hinweis": str(error)[:200]}
            company.update(result, geprueft=datetime.now().isoformat(timespec="minutes"))
            counts[result["status"]] += 1
            if on_progress:
                on_progress(done, len(todo), company)
            if done % 25 == 0:
                save(data)
    save(data)
    return counts
