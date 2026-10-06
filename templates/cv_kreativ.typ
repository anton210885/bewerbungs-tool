#let d = json("cv.json")
#let p = d.persoenlich
#let accent = rgb(d.akzent)
#let muted = rgb("#555555")
#let sp = d.at("abstand", default: 1.0)
#let fs = d.at("fotofaktor", default: 1.0)
#let kopf = d.at("angaben_im_kopf", default: false)
#let mx = 1.8cm
#let mt = 1.5cm

#set document(title: "Lebenslauf " + p.name)
#set page(paper: "a4", margin: (x: mx, top: mt, bottom: 1.5cm))
#set text(font: ("Calibri", "Carlito", "Arial", "Liberation Sans"), size: 9.8pt, lang: "de", region: d.region)
#set text(font: d.schrift) if "schrift" in d
#set text(size: d.groesse * 1em) if "groesse" in d
#set par(leading: 0.55em)
#set list(indent: 0.2em, spacing: 0.42em * sp, marker: text(fill: accent)[●])

#let section(title) = {
  v(1em * sp)
  grid(
    columns: (auto, 1fr),
    column-gutter: 0.5em,
    box(width: 5pt, height: 13pt, fill: accent, radius: 1pt),
    text(size: 12.5pt, weight: "bold", fill: accent, title),
  )
  v(0.25em * sp)
}

#let entry(e) = {
  block(
    width: 100%,
    inset: (left: 0.8em),
    stroke: (left: 1.5pt + accent.lighten(65%)),
    {
      text(size: 8.5pt, weight: "bold", fill: accent, upper(e.zeitraum))
      linebreak()
      text(weight: "bold", size: 10.5pt, e.titel)
      if e.untertitel != "" {
        linebreak()
        text(fill: muted, e.untertitel)
      }
      if e.punkte.len() > 0 {
        v(0.15em)
        list(..e.punkte)
      }
    },
  )
  v(0.5em * sp)
}

#pad(x: -mx, top: -mt, block(width: 100%, fill: accent, inset: (x: mx, y: 1.1cm * sp), {
  set text(fill: white)
  grid(
    columns: (auto, 1fr),
    column-gutter: 1.2em,
    if d.foto != "" {
      box(clip: true, radius: 1.6cm * fs, width: 3.2cm * fs, height: 3.2cm * fs, stroke: 2pt + white,
        image(d.foto, width: 3.2cm * fs, height: 3.2cm * fs, fit: "cover"))
    } else [],
    align(horizon, {
      text(size: 26pt, weight: "bold", p.name)
      if p.titel != "" {
        linebreak()
        text(size: 13pt, p.titel)
      }
      v(0.4em)
      text(size: 9pt, d.kontaktzeile)
      if kopf and d.angaben.len() > 0 {
        linebreak()
        text(size: 9pt, d.angaben.map(a => a.label + ": " + a.text).join("  ·  "))
      }
    }),
  )
}))

#if d.kurzprofil != "" {
  section("Über mich")
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

#let unten = if kopf { d.kenntnisse } else { (..d.kenntnisse, ..d.angaben) }
#if unten.len() > 0 {
  section(if kopf { "Kenntnisse" } else { "Kenntnisse & Persönliches" })
  for k in unten {
    grid(columns: (3.3cm, 1fr), column-gutter: 0.6em, text(weight: "bold", fill: accent, k.label), k.text)
    v(0.35em * sp)
  }
}

#if d.referenzen.len() > 0 {
  section("Referenzen")
  for r in d.referenzen {
    r
    linebreak()
  }
}
