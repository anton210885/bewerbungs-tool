import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

import requests

from src import config

BA_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
BA_API_KEY = "jobboerse-jobsuche"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Bewerbungs-Tool/0.1"


@dataclass
class Job:
    source: str
    external_id: str | None
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    published: str = ""


def search_ba(was: str, wo: str = "", umkreis: int = 25, size: int = 25) -> list[Job]:
    params = {"was": was, "angebotsart": 1, "size": size, "page": 1}
    if wo:
        params |= {"wo": wo, "umkreis": umkreis}
    resp = requests.get(
        BA_URL,
        params=params,
        headers={"X-API-Key": BA_API_KEY, "User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    jobs = []
    for item in resp.json().get("stellenangebote", []):
        refnr = item.get("refnr", "")
        jobs.append(
            Job(
                source="Bundesagentur für Arbeit",
                external_id=refnr,
                title=item.get("titel") or item.get("beruf", ""),
                company=item.get("arbeitgeber", ""),
                location=(item.get("arbeitsort") or {}).get("ort", ""),
                url=item.get("externeUrl") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}",
                published=item.get("aktuelleVeroeffentlichungsdatum", ""),
            )
        )
    return jobs


def search_adzuna(was: str, wo: str = "", umkreis: int = 25, size: int = 25) -> list[Job]:
    if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
        raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY fehlen in den API-Einstellungen")
    params = {
        "app_id": config.ADZUNA_APP_ID,
        "app_key": config.ADZUNA_APP_KEY,
        "what": was,
        "results_per_page": size,
        "content-type": "application/json",
    }
    if wo:
        params |= {"where": wo, "distance": umkreis}
    url = f"https://api.adzuna.com/v1/api/jobs/{config.COUNTRY}/search/1"
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return [
        Job(
            source="Adzuna",
            external_id=str(item.get("id")),
            title=_strip_tags(item.get("title", "")),
            company=(item.get("company") or {}).get("display_name", ""),
            location=(item.get("location") or {}).get("display_name", ""),
            url=item.get("redirect_url", ""),
            description=_strip_tags(item.get("description", "")),
            published=item.get("created", "")[:10],
        )
        for item in resp.json().get("results", [])
    ]


def fetch_url_text(url: str, max_chars: int = 15000) -> str:
    return fetch_job(url, max_chars)["description"]


_GENERIC_TITLES = re.compile(
    r"^(stellenangebot|stelle|job|jobs|karriere|careers?|offene stellen|job details|"
    r"stellenausschreibung|vacancy|position)\b",
    re.I,
)


def resolve_job_title(meta: dict | None, analysis: dict | None, job: dict | None, url: str = "") -> str:
    """Bester Stellentitel aus Meta, Analyse, Fetch und URL."""
    meta, analysis, job = meta or {}, analysis or {}, job or {}
    for candidate in (meta.get("title"), analysis.get("titel"), job.get("title"), title_from_url(url)):
        if t := clean_job_title(candidate or ""):
            return t
    return "Ohne Titel"


def clean_job_title(title: str, company: str = "") -> str:
    """Entfernt Website-Suffixe und generische Titel wie «Stellenangebot | Firma»."""
    t = html.unescape(_s(title))
    if not t:
        return ""
    # «AI Engineer Job Details | Hero Group» / «Titel | Firma»
    if " | " in t:
        left, right = t.split(" | ", 1)
        if company and right.strip().lower() == company.strip().lower():
            t = left.strip()
        elif _GENERIC_TITLES.match(left.strip()) and not _GENERIC_TITLES.match(right.strip()):
            t = right.strip()
        else:
            t = left.strip()
    t = re.sub(r"\s+[-–—]\s+(Job Details|Careers?|Karriere|Stellenangebot).*$", "", t, flags=re.I)
    t = re.sub(r"\s+Job Details\s*$", "", t, flags=re.I).strip()
    if _GENERIC_TITLES.match(t) and len(t) < 40:
        return ""
    if t.lower() in {"jobtitel", "job title", "position", "inhalt wird geladen"}:
        return ""
    return t


def title_from_url(url: str) -> str:
    """Fallback: Stellentitel aus der URL, z.B. .../job/AI-Engineer/4064 → AI Engineer."""
    if not url:
        return ""
    path = re.sub(r"[?#].*$", "", url)
    parts = [p for p in path.split("/") if p]
    skip = {"job", "jobs", "stelle", "stellen", "karriere", "careers", "detail", "offene-stellen",
            "de", "en", "fr", "it", "en_us", "en_US", "pub", "jobdetail", "www"}
    candidates = []
    for p in parts:
        pl = p.lower()
        if pl in skip or re.fullmatch(r"\d+", p) or re.fullmatch(r"[0-9a-f-]{8,}", p, re.I):
            continue
        # «4064-en_US» o.ä. überspringen
        if re.match(r"^\d+([-_]en([-_]us)?)?$", pl):
            continue
        if len(p) < 4 or "%" in p or "." in p:
            continue
        candidates.append(p)
    if not candidates:
        return ""
    # Längsten sprechenden Slug nehmen (nicht die letzte ID)
    raw = max(candidates, key=lambda s: (("-" in s or "_" in s), len(s)))
    raw = re.sub(r"[-_]+", " ", raw)
    if " " not in raw and raw.islower() and len(raw) < 8:
        return ""
    # «Jobtitel» aus Templates verwerfen
    if raw.lower() in {"jobtitel", "job title", "stellenangebot", "position"}:
        return ""
    return raw.strip()


def is_thin_job_page(description: str) -> bool:
    """True bei SPA-/Cookie-Seiten ohne echten Anzeigentext."""
    text = description or ""
    if len(text) < 150:
        return True
    markers = ("{{", "Inhalt wird geladen", "content is loading", "please enable javascript",
               "cookie", "consent manager", "{{Jobtitel}}", "{{Pensum}}", "{{Ort}}")
    hits = sum(1 for m in markers if m.lower() in text.lower())
    # Viele Platzhalter oder kaum Buchstaben → unbrauchbar
    letters = sum(c.isalpha() for c in text)
    return hits >= 2 or letters < 120


def fetch_job(url: str, max_chars: int = 15000) -> dict:
    """Lädt eine Stellenanzeige. Nutzt strukturierte JobPosting-Daten, falls die Seite welche hat."""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "de-CH,de;q=0.9"},
                        timeout=20, allow_redirects=True)
    resp.raise_for_status()
    page = resp.text
    posting = _find_jobposting(page) or {}

    location = posting.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else {}
    address = (location or {}).get("address") or {}

    org = posting.get("hiringOrganization") or {}
    company = _s(org.get("name") if isinstance(org, dict) else org)
    description = html_to_text(html.unescape(posting.get("description") or ""))
    if len(description) < 200:
        description = html_to_text(page)

    title_tag = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I)
    h1_text = html_to_text(h1.group(1)).strip() if h1 else ""
    raw_title = (
        _s(posting.get("title"))
        or h1_text
        or (html.unescape(title_tag.group(1)).strip() if title_tag else "")
    )
    title = clean_job_title(raw_title, company) or title_from_url(url)

    return {
        "title": title,
        "company": company,
        "location": _s(address.get("addressLocality") if isinstance(address, dict) else ""),
        "description": description[:max_chars],
        "thin": is_thin_job_page(description),
    }


def _find_jobposting(page: str) -> dict | None:
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                types = item.get("@type")
                if types == "JobPosting" or (isinstance(types, list) and "JobPosting" in types):
                    return item
                stack.extend(v for v in item.values() if isinstance(v, (list, dict)))
    return None


def _s(value) -> str:
    return "" if value is None else str(value).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr", "section", "article", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
            if tag == "li" and not self._skip_depth:
                self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)
