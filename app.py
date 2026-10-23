import streamlit as st

from src import __version__, db, documents
from ui import sidebar, state, tab_check, tab_cv, tab_docs, tab_photo, tab_search, tab_tracker

st.set_page_config(page_title="Bewerbungs-Tool", layout="wide")
db.init_db()
st.session_state.setdefault("upload_round", 0)
st.session_state.setdefault("nav_page", "unterlagen")
state.refresh()

PAGES = {
    "unterlagen": ("1. Meine Unterlagen", tab_docs),
    "lebenslauf": ("Mein Lebenslauf", tab_cv),
    "foto": ("Bewerbungsfoto", tab_photo),
    "bewerben": ("2. Stelle prüfen & bewerben", tab_check),
    "suche": ("Stellensuche", tab_search),
    "tracker": ("Tracker", tab_tracker),
}

st.title("Bewerbungs-Tool")
if not state.LLM_OK:
    st.warning("Kein KI-API-Schlüssel gesetzt – links unter **Einstellungen → API & KI** eintragen.")
if notice := st.session_state.pop("notice", None):
    st.success(notice)

# Kosten: Session-Cache, eingeklappt – nicht bei jedem Klick neu rechnen/laden
try:
    from src.costs import dashboard, format_money, provider_summary
    import time as _time

    force_costs = st.session_state.pop("kosten_force", False)
    cache = st.session_state.get("kosten_cache")
    if force_costs or not cache or (_time.time() - cache.get("ts", 0) > 120):
        if force_costs:
            provider_summary(force=True)
        st.session_state["kosten_cache"] = {"ts": _time.time(), "info": dashboard()}
    info = st.session_state["kosten_cache"]["info"]
    local = info["local"]
    with st.expander(
        f"Kosten: heute {format_money(local['heute_usd'])} · gesamt {format_money(local['gesamt_usd'])}",
        expanded=False,
    ):
        c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 0.8])
        c1.metric("Heute (geschätzt)", format_money(local["heute_usd"]))
        c2.metric("Gesamt in diesem Tool", format_money(local["gesamt_usd"]))
        if info["remaining"] is not None:
            c3.metric("Restguthaben", format_money(info["remaining"], info["currency"]))
        elif info.get("spent_30d") is not None:
            c3.metric("Anbieter 30 Tage", format_money(info["spent_30d"]))
        else:
            c3.metric("Restguthaben", "–")
        if c4.button("Aktualisieren", key="kosten_refresh", help="Guthaben neu laden"):
            st.session_state["kosten_force"] = True
            st.session_state.pop("kosten_cache", None)
            st.rerun()
        if hinweis := (info.get("provider") or {}).get("hinweis") or (info.get("provider") or {}).get("balance_hinweis"):
            st.caption(hinweis)
except Exception:
    pass

# Onboarding nur wenn Profil noch fehlt (keine DB-/Docs-Scans im Normalbetrieb)
if not state.PROFILE_READY and not st.session_state.get("onboarding_dismissed"):
    has_cv = bool(documents.active_documents("lebenslauf"))
    steps = [
        ("API-Schlüssel", state.LLM_OK, "unterlagen",
         "Links unter Einstellungen → API & KI eintragen."),
        ("Lebenslauf hochladen", has_cv, "unterlagen",
         "Unter «1. Meine Unterlagen» hochladen."),
        ("Profil bereit", False, "unterlagen",
         "Wird nach dem Upload automatisch erstellt."),
    ]
    st.info("**Start-Checkliste** – erledige diese Punkte der Reihe nach:")
    for name, done, page, tip in steps:
        mark = "✅" if done else "⬜"
        c_a, c_b = st.columns([4, 1])
        c_a.markdown(f"{mark} **{name}** – {tip}" if not done else f"{mark} **{name}**")
        if not done and c_b.button("Öffnen", key=f"onb_{page}_{name}"):
            st.session_state.nav_page = page
            st.rerun()
    if st.button("Checkliste ausblenden", key="onb_hide"):
        st.session_state.onboarding_dismissed = True
        st.rerun()

sidebar.render()
st.sidebar.caption(f"Version {__version__}")

# Navigation (statt Tabs → Sprung aus Tracker/Checkliste möglich)
if st.session_state.nav_page not in PAGES:
    st.session_state.nav_page = "unterlagen"
page = st.radio(
    "Bereich",
    list(PAGES),
    format_func=lambda k: PAGES[k][0],
    horizontal=True,
    key="nav_page",
    label_visibility="collapsed",
)
PAGES[page][1].render()
