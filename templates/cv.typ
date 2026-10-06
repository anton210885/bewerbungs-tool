#let d = json("cv.json")
#let p = d.persoenlich
#let accent = rgb(d.akzent)
#let muted = rgb("#555555")

#set document(title: "Lebenslauf " + p.name)
#set page(paper: "a4", margin: (x: 1.8cm, y: 1.6cm))
#set text(font: ("Calibri", "Carlito", "Arial", "Liberation Sans"), size: 10pt, lang: "de", region: d.region)
#set text(font: d.schrift) if "schrift" in d
#set text(size: d.groesse * 1em) if "groesse" in d
#set par(leading: 0.55em)
#set list(indent: 0.2em, spacing: 0.45em, marker: text(fill: accent)[•])

#let section(title) = {
  v(0.9em)
  text(size: 11.5pt, weight: "bold", fill: accent, tracking: 0.05em, upper(title))
  v(-0.55em)
  line(length: 100%, stroke: 0.6pt + accent)
  v(0.2em)
}

#let zeile(label, inhalt) = {
  grid(columns: (3.2cm, 1fr), column-gutter: 0.6em, text(fill: muted, label), inhalt)
  v(0.35em)
}

#let entry(e) = {
  grid(
    columns: (3.2cm, 1fr),
    column-gutter: 0.6em,
    text(fill: muted, e.zeitraum),
    {
      text(weight: "bold", e.titel)
      if e.untertitel != "" {
        linebreak()
        text(style: "italic", fill: muted, e.untertitel)
      }
      if e.punkte.len() > 0 {
        v(0.1em)
        list(..e.punkte)
      }
    },
  )
  v(0.5em)
}

#grid(
  columns: (1fr, auto),
  column-gutter: 1em,
  {
    text(size: 24pt, weight: "bold", fill: accent, p.name)
    if p.titel != "" {
      linebreak()
      text(size: 12pt, fill: muted, p.titel)
    }
    v(0.3em)
    text(size: 9.5pt, d.kontaktzeile)
  },
  if d.foto != "" { box(clip: true, radius: 3pt, image(d.foto, width: 3.2cm)) } else [],
)

#if d.angaben.len() > 0 {
  section("Persönliche Angaben")
  for a in d.angaben { zeile(a.label, a.text) }
}

#if d.kurzprofil != "" {
  section("Profil")
  par(justify: true, d.kurzprofil)
}

#if d.berufserfahrung.len() > 0 {
  section("Berufserfahrung")
  for e in d.berufserfahrung { entry(e) }
}

#if d.ausbildung.len() > 0 {
  section("Ausbildung")
  for e in d.ausbildung { entry(e) }
}

#if d.projekte.len() > 0 {
  section("Projekte")
  for e in d.projekte { entry(e) }
}

#if d.kenntnisse.len() > 0 {
  section("Kenntnisse")
  for k in d.kenntnisse { zeile(k.label, k.text) }
}

#if d.referenzen.len() > 0 {
  section("Referenzen")
  for r in d.referenzen {
    r
    v(0.2em)
  }
}
