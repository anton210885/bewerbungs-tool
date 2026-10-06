#let d = json("cv.json")
#let p = d.persoenlich
#let accent = rgb(d.akzent)
#let muted = rgb("#555555")

#set document(title: "Lebenslauf " + p.name)
#set page(paper: "a4", margin: (x: 1.4cm, y: 1.3cm))
#set text(font: ("Calibri", "Carlito", "Arial", "Liberation Sans"), size: 9pt, lang: "de", region: d.region)
#set par(leading: 0.5em)
#set list(indent: 0.1em, spacing: 0.32em, marker: text(fill: accent)[▪])

#let section(title) = {
  v(0.75em)
  block(width: 100%, fill: accent.lighten(88%), inset: (x: 0.4em, y: 0.3em),
    text(size: 9.5pt, weight: "bold", fill: accent, upper(title)))
  v(0.25em)
}

#let entry(e) = {
  grid(
    columns: (2.6cm, 1fr),
    column-gutter: 0.6em,
    text(size: 8.5pt, fill: muted, e.zeitraum),
    {
      text(weight: "bold", e.titel)
      if e.untertitel != "" { text(fill: muted, " · " + e.untertitel) }
      if e.punkte.len() > 0 {
        v(0.05em)
        list(..e.punkte)
      }
    },
  )
  v(0.35em)
}

#grid(
  columns: (auto, 1fr),
  column-gutter: 0.9em,
  if d.foto != "" { box(clip: true, radius: 2pt, image(d.foto, width: 2.4cm)) } else [],
  align(horizon, {
    text(size: 19pt, weight: "bold", fill: accent, p.name)
    if p.titel != "" { text(size: 11pt, fill: muted, "  " + p.titel) }
    v(0.25em)
    text(size: 8.5pt, d.kontaktzeile)
    if d.angaben.len() > 0 {
      linebreak()
      text(size: 8.5pt, fill: muted, d.angaben.map(a => a.label + ": " + a.text).join("  ·  "))
    }
  }),
)

#if d.kurzprofil != "" {
  section("Profil")
  par(justify: true, d.kurzprofil)
}

#if d.berufserfahrung.len() > 0 {
  section("Berufserfahrung")
  for e in d.berufserfahrung { entry(e) }
}

#grid(
  columns: (1fr, 1fr),
  column-gutter: 1.2em,
  {
    if d.ausbildung.len() > 0 {
      section("Ausbildung")
      for e in d.ausbildung {
        text(weight: "bold", e.titel)
        linebreak()
        text(size: 8.5pt, fill: muted, e.untertitel + (if e.zeitraum != "" { " · " + e.zeitraum } else { "" }))
        for pt in e.punkte {
          linebreak()
          text(size: 8.5pt, pt)
        }
        v(0.4em)
      }
    }
  },
  {
    if d.kenntnisse.len() > 0 {
      section("Kenntnisse")
      for k in d.kenntnisse {
        text(weight: "bold", fill: accent, k.label + ": ")
        k.text
        v(0.3em)
      }
    }
  },
)

#if d.projekte.len() > 0 {
  section("Projekte")
  for e in d.projekte { entry(e) }
}

#if d.referenzen.len() > 0 {
  section("Referenzen")
  d.referenzen.join("  ·  ")
}
