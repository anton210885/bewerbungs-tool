"""Viele Stellen von einer Übersichtsseite auf einmal prüfen."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from src.generate import L, analyze_match
from src.jobs import USER_AGENT, fetch_job
from src.llm import chat_json

MAX_LINKS = 300
PARALLEL = 4

EXTRACT_SYSTEM = """Du erhältst die Links einer Webseite (Linktext -> Adresse).
Finde alle Links, die zu einer EINZELNEN Stellenanzeige führen. Ignoriere Navigation, Filter, Kategorien,
Firmenprofile, Werbung, Login, Seitennummern und Ähnliches.
Gib folgendes JSON zurück:
{"stellen": [{"index": <Nummer des Links>, "titel": "<Stellentitel>", "firma": "<Firma, falls erkennbar>",
              "ort": "<Ort, falls erkennbar>"}, ...]}"""

PRESELECT_SYSTEM = f"""Du bist Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
Du erhältst ein Bewerberprofil und eine Liste von Stellen (nur Titel, Firma, Ort).
Wähle die Stellen aus, die am wahrscheinlichsten gut zum Profil und zu den Wünschen passen.
"""
PRESELECT_SYSTEM += """Gib folgendes JSON zurück: {"auswahl": [<index>, ...]}  (beste zuerst)"""


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None


def extract_jobs(page_url: str) -> list[dict]:
    """Findet die Stellenanzeigen auf einer Übersichtsseite."""
    resp = requests.get(page_url, headers={"User-Agent": USER_AGENT}, timeout=25)
    resp.raise_for_status()
    parser = _LinkParser()
    parser.feed(resp.text)

    seen, links = set(), []
    for href, text in parser.links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")) or len(text) < 4:
            continue
        absolute = urljoin(page_url, href).split("#")[0]
        if urlparse(absolute).scheme not in ("http", "https") or absolute in seen or absolute == page_url:
            continue
        seen.add(absolute)
        links.append((absolute, text[:160]))
        if len(links) >= MAX_LINKS:
            break
    if not links:
        raise ValueError("Auf der Seite wurden keine Links gefunden. Manche Portale laden ihre Inhalte erst im "
                         "Browser – dann funktioniert diese Funktion dort leider nicht.")

    listing = "\n".join(f"{i}. {text} -> {url}" for i, (url, text) in enumerate(links))
    result = chat_json(EXTRACT_SYSTEM, listing, temperature=0.0, max_tokens=8000)
    jobs = []
    for item in result.get("stellen") or []:
        i = item.get("index")
        if isinstance(i, int) and 0 <= i < len(links):
            jobs.append({"url": links[i][0], "title": item.get("titel") or links[i][1],
                         "company": item.get("firma") or "", "location": item.get("ort") or ""})
    return list({j["url"]: j for j in jobs}.values())


def preselect(profile: dict, jobs: list[dict], count: int) -> list[dict]:
    if len(jobs) <= count:
        return jobs
    summary = {
        "titel": (profile.get("persoenlich") or {}).get("titel"),
        "kurzprofil": profile.get("kurzprofil"),
        "positionen": [e.get("position") for e in profile.get("berufserfahrung") or []],
        "skills": profile.get("skills"),
        "wuensche": profile.get("wuensche"),
    }
    listing = "\n".join(f"{i}. {j['title']} | {j['company']} | {j['location']}" for i, j in enumerate(jobs))
    user = (f"PROFIL:\n{json.dumps(summary, ensure_ascii=False, default=str)}\n\n"
            f"STELLEN:\n{listing}\n\nWähle die {count} passendsten.")
    result = chat_json(PRESELECT_SYSTEM, user, temperature=0.0, max_tokens=1000)
    chosen = [jobs[i] for i in result.get("auswahl") or [] if isinstance(i, int) and 0 <= i < len(jobs)]
    return list({j["url"]: j for j in chosen}.values())[:count] or jobs[:count]


def _evaluate_one(profile: dict, job: dict) -> dict:
    details = fetch_job(job["url"])
    if len(details["description"]) < 150:
        raise ValueError("kaum Text auf der Seite")
    analysis = analyze_match(profile, details["description"])
    return {**job, "description": details["description"],
            "company": job["company"] or details["company"] or analysis.get("firma", ""),
            "location": job["location"] or details["location"] or analysis.get("ort", ""),
            "analysis": analysis}


def evaluate(profile: dict, jobs: list[dict], on_progress=None) -> tuple[list[dict], list[str]]:
    """Prüft die Stellen parallel. Gibt (Ergebnisse sortiert nach Passung, Fehlermeldungen) zurück."""
    results, errors = [], []
    with ThreadPoolExecutor(PARALLEL) as pool:
        futures = {pool.submit(_evaluate_one, profile, job): job for job in jobs}
        for done, future in enumerate(as_completed(futures), start=1):
            job = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                errors.append(f"{job['title']}: {e}")
            if on_progress:
                on_progress(f"{done}/{len(jobs)} geprüft: {job['title']}")
    results.sort(key=lambda r: r["analysis"].get("score", 0), reverse=True)
    return results, errors
