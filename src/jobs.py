import re
from dataclasses import dataclass
from html.parser import HTMLParser

import requests

from src.config import ADZUNA_APP_ID, ADZUNA_APP_KEY, COUNTRY

BA_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
BA_API_KEY = "jobboerse-jobsuche"
ADZUNA_URL = f"https://api.adzuna.com/v1/api/jobs/{COUNTRY}/search/1"
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
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY fehlen in der .env")
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": was,
        "results_per_page": size,
        "content-type": "application/json",
    }
    if wo:
        params |= {"where": wo, "distance": umkreis}
    resp = requests.get(ADZUNA_URL, params=params, timeout=20)
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
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return html_to_text(resp.text)[:max_chars]


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
