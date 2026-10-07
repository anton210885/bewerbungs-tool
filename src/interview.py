"""Vorbereitung auf das Vorstellungsgespräch, Übungsgespräch und Nachfass-Mails."""
import json

from src import zeugnisse
from src.generate import L, _localize, _profile_for_llm
from src.llm import chat_json, chat_messages

PREP_SYSTEM = f"""Du bist eine erfahrene Karriereberaterin und Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Bereite die Person konkret auf das Vorstellungsgespräch für diese Stelle vor. Nutze nur Fakten aus dem Profil
für Beispiele und erfinde nichts. Denke an typische Fragen in der Schweiz (Motivation, Fachwissen,
Verhaltensfragen nach der STAR-Methode, Lücken und Wechsel im Lebenslauf, Lohnvorstellung, Verfügbarkeit).
Antworte mit JSON:
{{"einschaetzung": "<2-3 Sätze: worauf es in diesem Gespräch ankommt>",
  "fragen": [{{"frage": "...", "kategorie": "<Motivation | Fachlich | Verhalten | Lebenslauf | Rahmenbedingungen>",
              "warum": "<was die Firma damit herausfinden will>",
              "tipp": "<wie man gut antwortet>",
              "beispiel": "<konkretes Beispiel aus dem Profil, in der Ich-Form, 2-4 Sätze>"}}],
  "stolpersteine": [{{"thema": "<heikler Punkt, z.B. Lücke oder fehlende Anforderung>", "antwort": "<wie ehrlich und souverän ansprechen>"}}],
  "eigene_fragen": ["<gute Fragen an die Firma>"],
  "vorbereitung": ["<konkrete To-dos vor dem Gespräch, z.B. Firmenrecherche zu ...>"]}}
Erstelle 10-12 Fragen, 2-4 Stolpersteine, 5 eigene Fragen und 3-5 To-dos."""

INTERVIEWER_SYSTEM = """Du führst ein realistisches Vorstellungsgespräch auf Deutsch (Schweizer Rechtschreibung,
kein ß) für die unten genannte Stelle. Du bist die Personalverantwortliche der Firma.
Ablauf: Stelle immer genau EINE Frage. Wenn die Person geantwortet hat, gib zuerst kurzes, ehrliches
Feedback (2-3 Sätze: was gut war, was besser ginge) in einer Zeile, die mit «Feedback:» beginnt,
und stelle danach in einer neuen Zeile, die mit «Frage:» beginnt, die nächste Frage.
Mische Motivations-, Fach-, Verhaltens- und Lebenslauf-Fragen und gehe auf die Antworten ein.

STELLE:
{stelle}

LEBENSLAUF DER PERSON (nur zur Orientierung):
{profil}"""

SUMMARY_PROMPT = ("Das Gespräch ist beendet. Gib eine Gesamtauswertung: Gesamteindruck in 2 Sätzen, "
                  "3 Stärken, 3 konkrete Verbesserungen und eine Note von 1-10. Formatiere mit kurzen Überschriften.")

FOLLOWUP_SYSTEM = f"""Du schreibst eine kurze, höfliche Nachfass-E-Mail zu einer Bewerbung auf dem
{L["markt"]} Arbeitsmarkt. {L["stil"]}
Maximal 120 Wörter, freundlich und selbstbewusst, nicht drängend. Bekräftige kurz das Interesse mit einem
konkreten Bezug zur Stelle und frage nach dem Stand. Grussformel: «{L["gruss"]}».
Antworte mit JSON: {{"betreff": "...", "text": "<vollständige E-Mail mit Anrede und Gruss>"}}"""


def _job_text(app: dict) -> str:
    return (f"{app.get('title')} bei {app.get('company')} ({app.get('location')})\n\n"
            f"{(app.get('description') or '')[:6000]}")


def prepare(profile: dict, app: dict, analysis: dict | None) -> dict:
    user = (f"PROFIL:\n{json.dumps(_profile_for_llm(profile), ensure_ascii=False, default=str)}\n\n"
            f"STELLE:\n{_job_text(app)}\n\nANALYSE DER PASSUNG:\n{json.dumps(analysis or {}, ensure_ascii=False)}")
    if hinweise := zeugnisse.interview_context():
        user += f"\n\nAUS DEN ARBEITSZEUGNISSEN (heikle Punkte als Stolpersteine, Zitate als Belege nutzen):\n{hinweise}"
    return _localize(chat_json(PREP_SYSTEM, user, temperature=0.4, max_tokens=8000))


def interviewer(profile: dict, app: dict, messages: list[dict]) -> str:
    system = INTERVIEWER_SYSTEM.format(
        stelle=_job_text(app),
        profil=json.dumps(_profile_for_llm(profile), ensure_ascii=False, default=str)[:8000],
    )
    start = {"role": "user", "content": "Bitte beginne das Gespräch mit einer kurzen Begrüssung und der ersten Frage."}
    return _localize(chat_messages(system, [start, *messages], temperature=0.6))


def summarize_interview(profile: dict, app: dict, messages: list[dict]) -> str:
    return interviewer(profile, app, [*messages, {"role": "user", "content": SUMMARY_PROMPT}])


def followup_email(profile: dict, app: dict) -> dict:
    name = (profile.get("persoenlich") or {}).get("name", "")
    user = (f"BEWERBER: {name}\nSTELLE: {app.get('title')} bei {app.get('company')}\n"
            f"BEWORBEN AM: {app.get('applied_at') or 'unbekannt'}\n\nANZEIGE (Auszug):\n"
            f"{(app.get('description') or '')[:2500]}")
    return _localize(chat_json(FOLLOWUP_SYSTEM, user, temperature=0.5, max_tokens=1200))
