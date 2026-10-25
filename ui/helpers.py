"""Gemeinsame Bausteine der Oberfläche."""
import json
import re
from pathlib import Path

import streamlit as st

from src import config, db, documents, jobs, word
from src.generate import analyze_match, render_cv_fitted
from src.matching import KRITERIEN
from ui import state as S

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def download(label: str, path: str | None, key: str, col=st):
    if path and Path(path).exists():
        mime = DOCX_MIME if Path(path).suffix == ".docx" else "application/pdf"
        col.download_button(label, Path(path).read_bytes(), file_name=Path(path).name, mime=mime, key=key)


@st.cache_data(show_spinner=False, max_entries=40, ttl=600)
def _pdf_preview_pages(path_str: str, mtime: float, dpi: int, max_pages: int) -> tuple[list[bytes], int]:
    """Gibt (Seitenbilder, Gesamtseitenzahl) zurück."""
    path = Path(path_str)
    import pymupdf
    with pymupdf.open(path) as pdf:
        total = len(pdf)
    pages = documents.pdf_to_images(path, dpi=dpi, max_pages=max_pages)
    return pages, total


def show_pdf_preview(path: str, dpi: int = 72, max_pages: int = 2) -> None:
    """Schnelle PDF-Vorschau (gecacht, nur erste Seiten)."""
    p = Path(path)
    if not p.exists():
        st.caption("PDF nicht gefunden.")
        return
    try:
        pages, total = _pdf_preview_pages(str(p.resolve()), p.stat().st_mtime, dpi, max_pages)
    except Exception as e:
        st.caption(f"Vorschau nicht möglich: {e}")
        return
    for page in pages:
        st.image(page, width="stretch")
    if total > max_pages:
        st.caption(f"Vorschau: erste {max_pages} von {total} Seiten")


def styled_cv(data: dict, out_dir: Path, filename: str) -> Path:
    """Erstellt den Lebenslauf im gewählten Design als PDF und zusätzlich als Word-Datei daneben."""
    pdf, used_options, _ = render_cv_fitted(data, out_dir, filename, template=S.CV_TEMPLATE, accent=S.CV_ACCENT,
                                            options=S.CV_OPTIONS)
    word.save_cv_docx(data, pdf.with_suffix(".docx"), template=S.CV_TEMPLATE, accent=S.CV_ACCENT,
                      options=used_options)
    return pdf


def _photo_stamp(data: dict) -> float:
    foto = Path(data.get("foto") or "")
    foto = foto if foto.is_absolute() else config.data_dir() / foto
    return foto.stat().st_mtime if data.get("foto") and foto.exists() else 0.0


@st.cache_data(show_spinner=False, max_entries=60)
def template_preview(template: str, accent: str, data_json: str, dpi: int, photo_stamp: float,
                     options_json: str):
    data = json.loads(data_json)
    pdf, used_options, notes = render_cv_fitted(data, config.output_dir() / "vorlagen" / f"{template}_{dpi}",
                                                "vorschau.pdf", template=template, accent=accent,
                                                options=json.loads(options_json))
    return pdf.read_bytes(), documents.pdf_to_images(pdf, dpi=dpi), used_options, notes


@st.cache_data(show_spinner=False, max_entries=20)
def cv_photo_candidates_cached(files: tuple) -> list[tuple[str, bytes]]:
    return documents.cv_photo_candidates()


@st.cache_data(show_spinner=False, max_entries=200)
def _doc_thumb(path_str: str, mtime: float) -> bytes | None:
    return documents.document_thumbnail(Path(path_str))


def _document_card(path: Path) -> None:
    info = documents.document_info(path)
    summary = documents.load_summary(path) or {}
    excluded = documents.is_excluded(path)
    key = f"{path.parent.name}_{path.name}"
    with st.container(border=True):
        c_img, c_txt, c_act = st.columns([1, 5, 1.4])
        thumb = _doc_thumb(str(path), path.stat().st_mtime)
        if thumb:
            c_img.image(thumb, width="stretch")
        else:
            c_img.markdown(f"**{path.suffix.upper().lstrip('.')}**")
        with c_txt:
            st.markdown(f"**{summary.get('titel') or path.name}**"
                        + ("  ·  :orange[nicht verwendet]" if excluded else ""))
            meta = [path.name, f"hochgeladen {info['hochgeladen']}",
                    f"{info['seiten']} Seite(n)" if info["seiten"] else "", f"{info['groesse_kb']} KB"]
            st.caption("  ·  ".join(m for m in meta if m))
            if summary:
                facts = [f"**{summary.get('typ', '')}**", summary.get("aussteller", ""),
                         summary.get("zeitraum", ""),
                         f"Stand {summary['stand']}" if summary.get("stand") else ""]
                st.markdown("  ·  ".join(f for f in facts if f and f != "****"))
                if summary.get("bewertung"):
                    st.markdown(f"**Bewertung:** {summary['bewertung']}")
                if summary.get("kernaussagen"):
                    st.markdown("".join(f"\n- {x}" for x in summary["kernaussagen"]))
                if hinweise := [h for h in summary.get("hinweise", []) if h]:
                    st.warning("**Auffällig:**" + "".join(f"\n- {x}" for x in hinweise))
            else:
                st.caption("Noch kein Steckbrief – oben auf „Steckbriefe erstellen“ klicken.")
        with c_act:
            st.session_state[f"use_{key}"] = not excluded
            st.toggle("Verwenden", key=f"use_{key}",
                      on_change=lambda: documents.set_excluded(path, not st.session_state[f"use_{key}"]),
                      help="Fliesst ins Profil, in die Lebenslauf-Analyse und ins Dossier ein.")
            if st.button("Löschen", key=f"del_{key}", width="stretch"):
                documents.delete_document(path)
                st.rerun()


def _cv_comparison(docs: list[Path]) -> None:
    st.markdown(f"**Deine {len(docs)} Lebensläufe im Vergleich**")
    cmp = documents.load_cv_comparison(docs)
    if st.button("Neu vergleichen" if cmp else "Lebensläufe von KI vergleichen lassen", key="cmp_cvs",
                 type="secondary" if cmp else "primary", disabled=not S.LLM_OK):
        with st.spinner("KI vergleicht deine Lebensläufe ..."):
            try:
                documents.compare_cvs(docs)
                st.rerun()
            except Exception as e:
                st.error(f"Vergleich fehlgeschlagen: {e}")
    if not cmp:
        return
    st.info(cmp.get("zusammenfassung", ""))
    st.caption(f"Erstellt am {cmp.get('erstellt', '')}")
    entries = cmp.get("dokumente", [])
    for col, d in zip(st.columns(max(1, len(entries))), entries):
        with col, st.container(border=True):
            st.markdown(f"**{d.get('datei', '')}**  \nStand: {d.get('stand') or 'unbekannt'}")
            st.markdown("Stärken" + "".join(f"\n- {x}" for x in d.get("staerken", [])))
            st.markdown("Schwächen" + "".join(f"\n- {x}" for x in d.get("schwaechen", [])))
    for item in cmp.get("nur_in", []):
        if item.get("inhalte"):
            st.markdown(f"**Steht nur in {item.get('datei', '')}:**" + "".join(f"\n- {x}" for x in item["inhalte"]))
    if cmp.get("widersprueche"):
        st.warning("**Widersprüche zwischen den Lebensläufen:**"
                   + "".join(f"\n- **{w.get('thema', '')}:** {w.get('details', '')}" for w in cmp["widersprueche"]))
    if cmp.get("empfehlung"):
        st.success(f"**Empfehlung:** {cmp['empfehlung']}")
    st.caption("Tipp: Einen veralteten Lebenslauf kannst du oben mit „Verwenden“ ausschalten. Widersprüche "
               "klärst du am besten im Feld „Ergänzungen & Wünsche“ und erstellst danach das Profil neu.")


def show_documents_overview() -> None:
    all_docs = {k: documents.list_documents(k) for k in documents.KATEGORIEN}
    if not any(all_docs.values()):
        return
    st.subheader("Übersicht deiner Unterlagen")
    missing = [p for docs in all_docs.values() for p in docs if documents.load_summary(p) is None]
    o1, o2 = st.columns([3, 1])
    o1.caption("Zu jedem Dokument erstellt die KI einen kurzen Steckbrief. Mit „Verwenden“ legst du fest, ob ein "
               "Dokument ins Profil, die Analyse und das Dossier einfliesst – z.B. einen veralteten Lebenslauf "
               "ausschalten.")
    if missing and o2.button(f"Steckbriefe erstellen ({len(missing)})", disabled=not S.LLM_OK, width="stretch"):
        progress = st.progress(0.0)
        failed = []
        for i, path in enumerate(missing):
            progress.progress(i / len(missing), text=f"KI liest {path.name} ...")
            try:
                documents.summarize_document(path)
            except Exception as e:
                failed.append(f"{path.name}: {e}")
        if failed:
            st.error("Nicht geklappt:" + "".join(f"\n- {f}" for f in failed))
        else:
            st.rerun()
    for kat, label in documents.KATEGORIEN.items():
        docs = all_docs[kat]
        if not docs:
            continue
        used = sum(not documents.is_excluded(p) for p in docs)
        with st.expander(f"{label}: {len(docs)} Dokument(e), davon {used} verwendet", expanded=kat == "lebenslauf"):
            for path in docs:
                _document_card(path)
            if kat == "lebenslauf" and len(docs) >= 2:
                _cv_comparison(docs)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _lines(text: str) -> list[str]:
    return [re.sub(r"^\s*[-•*]\s*", "", line).strip() for line in text.splitlines() if line.strip()]


def _looks_like_url(value: str) -> bool:
    v = (value or "").strip()
    return v.startswith("http://") or v.startswith("https://")


def check_job(url: str, text: str = "", meta: dict | None = None) -> None:
    """Stelle laden, mit dem Profil vergleichen und im Tracker speichern."""
    meta = meta or {}
    url = (url or "").strip()
    text = (text or "").strip()
    # Link versehentlich nur im Textfeld → als URL behandeln
    if not url and _looks_like_url(text) and "\n" not in text and len(text) < 500:
        url, text = text, ""

    job = {"title": "", "company": "", "location": "", "description": text}
    fetch_error = None
    if url:
        with st.spinner("Lade Stellenanzeige ..."):
            try:
                fetched = jobs.fetch_job(url)
                thin = fetched.get("thin") or jobs.is_thin_job_page(fetched.get("description") or "")
                if thin and text and len(text) >= 150:
                    # SPA/Cookie-Seite: Titel aus URL/Fetch behalten, Text vom Nutzer
                    job = {
                        "title": fetched.get("title") or jobs.title_from_url(url),
                        "company": fetched.get("company") or "",
                        "location": fetched.get("location") or "",
                        "description": text,
                    }
                elif not thin and len(fetched.get("description") or "") >= 150:
                    job = fetched
                elif text and len(text) >= 150:
                    job = {
                        **fetched,
                        "description": text,
                        "title": fetched.get("title") or jobs.title_from_url(url),
                    }
                else:
                    job = fetched
            except Exception as e:
                fetch_error = e
                if text and len(text) >= 150:
                    job = {
                        "title": jobs.title_from_url(url),
                        "company": "",
                        "location": "",
                        "description": text,
                    }
                elif not meta.get("description"):
                    st.error(
                        f"Die Seite konnte nicht geladen werden ({e}). "
                        "Viele Portale (z.B. SuccessFactors) zeigen den Text erst im Browser. "
                        "Bitte den Anzeigentext ins Textfeld kopieren."
                    )
                    return

    if len(job["description"]) < 200 and meta.get("description"):
        job["description"] = meta["description"]
    if jobs.is_thin_job_page(job.get("description") or "") and not (text and len(text) >= 150):
        st.error(
            "Die Seite liefert keinen echten Anzeigentext (oft JavaScript/Cookies). "
            "Bitte den vollständigen Anzeigentext aus dem Browser hier ins Textfeld kopieren."
        )
        return
    if len(job["description"]) < 150:
        hint = f" (Laden: {fetch_error})" if fetch_error else ""
        st.error(
            "Kaum Stellen-Text gefunden" + hint + ". "
            "Bitte den vollständigen Anzeigentext ins Textfeld kopieren und nochmals prüfen."
        )
        return

    with st.spinner("KI prüft, ob die Stelle zu dir passt ..."):
        try:
            analysis = analyze_match(S.profile, job["description"])
        except Exception as e:
            st.error(f"Analyse fehlgeschlagen: {e}")
            return

    app_id = store_job(url, job, analysis, meta)
    if not app_id:
        st.error("Stelle konnte nicht gespeichert werden.")
        return
    title = jobs.resolve_job_title(meta, analysis, job, url)
    st.session_state["current_app"] = app_id
    st.session_state["show_app_detail"] = True
    st.session_state["notice"] = f"Stelle geprüft: {title} ({analysis['score']} % Passung)."
    st.rerun()


def store_job(url: str, job: dict, analysis: dict, meta: dict | None = None) -> int:
    """Geprüfte Stelle im Tracker speichern (bzw. aktualisieren). Gibt die ID zurück."""
    meta = meta or {}
    title = jobs.resolve_job_title(meta, analysis, job, url)
    # Firma/Ort: echte Fetch-Werte, sonst Analyse (nicht «Unbekannt» bevorzugen)
    company = (meta.get("company") or job.get("company") or "").strip()
    if not company or company.lower() in ("unbekannt", "unknown", "?"):
        company = (analysis.get("firma") or "").strip()
        if company.lower() in ("unbekannt", "unknown"):
            company = ""
    location = (meta.get("location") or job.get("location") or analysis.get("ort") or "").strip()
    fields = {
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "description": job.get("description", ""),
        "score": analysis["score"],
        "analysis": json.dumps(analysis, ensure_ascii=False),
    }
    source = meta.get("source") or ("Link" if url else "Text")
    external_id = meta.get("external_id") or url or None
    existing = db.find_application(source, external_id) if external_id else None
    if existing:
        db.update_application(existing["id"], **fields)
        return existing["id"]
    new_id = db.add_application({"source": source, "external_id": external_id, **fields})
    if new_id:
        return new_id
    # INSERT OR IGNORE: parallel/doppelt → vorhandene Zeile aktualisieren
    existing = db.find_application(source, external_id) if external_id else None
    if existing:
        db.update_application(existing["id"], **fields)
        return existing["id"]
    raise RuntimeError("Stelle konnte nicht in der Datenbank gespeichert werden.")


def show_analysis(analysis: dict) -> None:
    score = analysis.get("score", 0)
    c1, c2 = st.columns([1, 5])
    c1.metric("Passung", f"{score} %")
    fazit = analysis.get("fazit") or analysis.get("zusammenfassung", "")
    box = c2.success if score >= 70 else c2.warning if score >= 45 else c2.error
    box(fazit)
    if analysis.get("ko"):
        st.error("**K.-o.-Kriterien** (Score auf höchstens 20 % begrenzt)"
                 + "".join(f"\n- {x}" for x in analysis["ko"]))
    if kriterien := analysis.get("kriterien"):
        cols = st.columns(len(kriterien))
        for col, (key, k) in zip(cols, kriterien.items()):
            wert = "–" if k.get("wert") is None else f"{k['wert']:g}/10"
            col.metric(f"{KRITERIEN.get(key, key)} ({k.get('gewicht', 0):g} %)", wert,
                       help=k.get("begruendung") or None)
    if analysis.get("muss_check"):
        with st.expander("Muss-Anforderungen im Einzelnen"):
            icons = {"ja": "✅", "teilweise": "🟡", "nein": "❌"}
            for c in analysis["muss_check"]:
                beleg = f" – {c['beleg']}" if c.get("beleg") else ""
                st.markdown(f"{icons.get(str(c.get('erfuellt')).lower(), '❔')} {c.get('anforderung', '')}{beleg}")
    if analysis.get("fazit") and analysis.get("zusammenfassung"):
        st.write(analysis["zusammenfassung"])
    a1, a2 = st.columns(2)
    a1.markdown("**Was passt**" + "".join(f"\n- {x}" for x in analysis.get("staerken", [])))
    a2.markdown("**Was fehlt**" + "".join(f"\n- {x}" for x in analysis.get("luecken", [])))
    if analysis.get("keywords"):
        st.markdown("**Wichtige Begriffe aus der Anzeige:** " + ", ".join(analysis["keywords"]))
    if analysis.get("empfehlung"):
        st.info(f"**Empfehlung:** {analysis['empfehlung']}")
