"""Öffentliche Suchseiten von jobs.ch und LinkedIn; keine Anmeldung oder Sperrumgehung."""
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

import requests

from src import discovery, jobs, skill_search

SOURCES = ("jobs.ch", "LinkedIn")
HEADERS = {"User-Agent": "Bewerbungs-Tool/0.2 (personal job search)",
           "Accept-Language": "de-CH,de;q=0.9"}


class PortalError(RuntimeError):
    pass


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def find(self, *, tag=None, cls=None):
        for child in self.children:
            if not isinstance(child, Node):
                continue
            if (tag is None or child.tag == tag) and (cls is None or cls in (child.attrs.get("class") or "").split()):
                yield child
            yield from child.find(tag=tag, cls=cls)


class Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _first(node, **kwargs):
    found = next(node.find(**kwargs), None)
    return found.text() if found else ""


def search_url(source, term, location, radius=25, page=1):
    if source == "jobs.ch":
        # jobs.ch erwartet den Ortsnamen, LinkedIn akzeptiert «Ort, Land».
        params = {"term": term, "location": location.split(",")[0].strip(), "page": page}
        return "https://www.jobs.ch/de/stellenangebote/?" + urlencode(params)
    if source == "LinkedIn":
        # LinkedIn definiert distance in Meilen.
        params = {"keywords": term, "location": location, "distance": max(0, round(radius / 1.609344)),
                  "start": (page - 1) * 25}
        return "https://www.linkedin.com/jobs/search/?" + urlencode(params)
    raise ValueError("Unbekannte Quelle")


def _job_url(url, source):
    url = discovery.canonical_url(url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    if source == "jobs.ch":
        return url if (host == "jobs.ch" or host.endswith(".jobs.ch")) and "/stellenangebote/detail/" in parts.path else ""
    return url if (host == "linkedin.com" or host.endswith(".linkedin.com")) and "/jobs/view/" in parts.path else ""


def _postings(page):
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            stack = [json.loads(block)]
        except ValueError:
            continue
        while stack:
            entry = stack.pop()
            if isinstance(entry, list):
                stack.extend(reversed(entry))
            elif isinstance(entry, dict):
                kind = entry.get("@type")
                if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                    yield entry
                else:
                    stack.extend(reversed([v for v in entry.values() if isinstance(v, (list, dict))]))


def _metadata(posting):
    org = posting.get("hiringOrganization") or {}
    location = posting.get("jobLocation") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = (location.get("address") or {}) if isinstance(location, dict) else {}
    return {"title": jobs.clean_job_title(posting.get("title", "")),
            "company": org.get("name", "") if isinstance(org, dict) else str(org),
            "location": address.get("addressLocality", "") if isinstance(address, dict) else "",
            "description": jobs.html_to_text(posting.get("description") or ""),
            "published": posting.get("datePosted", "")}


def parse_listing(page, source):
    root = Tree(page).root
    items = []
    for posting in _postings(page):
        url = _job_url(posting.get("url", ""), source)
        if url:
            items.append({**_metadata(posting), "url": url, "source": source, "preliminary": True})
    if source == "LinkedIn":
        for card in root.find(cls="base-search-card"):
            link = next(card.find(tag="a", cls="base-card__full-link"), None)
            url = _job_url(link.attrs.get("href", "") if link else "", source)
            if url:
                items.append({"url": url, "source": source, "preliminary": True,
                              "title": _first(card, cls="base-search-card__title"),
                              "company": _first(card, cls="base-search-card__subtitle"),
                              "location": _first(card, cls="job-search-card__location"), "description": ""})
    # Fallback für einfache Ergebnislisten; keine KI für die Linkerkennung nötig.
    base = "https://www.jobs.ch" if source == "jobs.ch" else "https://www.linkedin.com"
    for link in root.find(tag="a"):
        url = _job_url(urljoin(base, link.attrs.get("href") or ""), source)
        title = _first(link, tag="h3") or _first(link, tag="h2") or link.text()
        if url and title:
            items.append({"url": url, "title": title[:250], "company": "", "location": "",
                          "description": "", "source": source, "preliminary": True})
    return discovery.deduplicate(items)


def parse_detail(page, source):
    posting = next(_postings(page), None)
    details = _metadata(posting) if posting else {}
    if len(details.get("description", "")) < 150:
        root = Tree(page).root
        content = _first(root, cls="show-more-less-html__markup")
        if len(content) >= 150:
            details["description"] = content
        details.setdefault("title", _first(root, tag="h1"))
    details["preliminary"] = len(details.get("description", "")) < 150
    return details


class Client:
    def __init__(self):
        self.session = requests.Session()
        self.last_request = 0.0

    def get(self, url):
        time.sleep(max(0, 1.0 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        try:
            response = self.session.get(url, headers=HEADERS, timeout=20)
        except requests.RequestException as error:
            raise PortalError("Verbindungsfehler oder Zeitüberschreitung.") from error
        if response.status_code in {401, 403, 429, 999}:
            raise PortalError(f"Portal blockiert den Zugriff (HTTP {response.status_code}). Quelle wird angehalten.")
        if response.status_code != 200:
            raise PortalError(f"Seite nicht abrufbar (HTTP {response.status_code}).")
        path = urlsplit(response.url).path.lower()
        title = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.S | re.I)
        title = title.group(1).lower() if title else ""
        if any(x in path for x in ("/login", "/authwall", "/checkpoint", "/challenge")) or any(
            x in title for x in ("access denied", "just a moment", "security verification", "captcha")
        ):
            raise PortalError("Portal verlangt Anmeldung oder Sicherheitsprüfung. Quelle wird angehalten.")
        return response.text


def search(preferences, sources, pages=1, detail_limit=10, on_progress=None):
    progress = on_progress or (lambda message: None)
    client = Client()
    items, errors, blocked = [], [], set()
    try:
        for source in sources:
            if source not in SOURCES:
                continue
            for term in skill_search.search_terms(preferences):
                for page in range(1, max(1, min(2, pages)) + 1):
                    url = search_url(source, term, preferences.get("location", ""), int(preferences.get("radius", 25)), page)
                    progress(f"{source}: «{term}», Seite {page} ...")
                    try:
                        found = parse_listing(client.get(url), source)
                    except PortalError as error:
                        errors.append(f"{source}: {error}")
                        blocked.add(source)
                        break
                    if not found:
                        errors.append(f"{source}: Keine auslesbaren Treffer für «{term}». Suche kann leer sein oder das Seitenformat wurde geändert.")
                        break
                    items.extend({**item, "search_terms": [term]} for item in found)
                if source in blocked:
                    break
        items = skill_search.rank(discovery.deduplicate(items, preferences.get("exclude", "")), preferences)
        # Quellen UND Suchbegriffe abwechseln, damit auch weitere Fähigkeiten vertieft werden.
        groups = [[j for j in items if j["source"] == source and term in j.get("search_terms", [])]
                  for term in skill_search.search_terms(preferences) for source in sources]
        ordered = discovery.deduplicate([group[index] for index in range(max((len(g) for g in groups), default=0))
                                         for group in groups if index < len(group)])
        for index, item in enumerate(ordered[:max(0, min(15, detail_limit))]):
            source = item["source"]
            if source in blocked:
                continue
            progress(f"Lade Anzeigentext {index + 1}: {item['title']} ...")
            try:
                details = parse_detail(client.get(item["url"]), source)
                item.update({k: v for k, v in details.items() if v or k == "preliminary"})
            except PortalError as error:
                errors.append(f"{source}: {error}")
                blocked.add(source)
        return skill_search.rank(discovery.deduplicate(ordered, preferences.get("exclude", "")), preferences), errors
    finally:
        client.session.close()
