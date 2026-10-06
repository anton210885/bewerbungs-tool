#let d = json("cv.json")
#let p = d.persoenlich
#let accent = rgb(d.akzent)
#let muted = rgb("#5a5a5a")
#let sp = d.at("abstand", default: 1.0)
#let fs = d.at("fotofaktor", default: 1.0)
#let kopf = d.at("angaben_im_kopf", default: false)

#set document(title: "Lebenslauf " + p.name)
#set page(paper: "a4", margin: (x: 2cm, y: 1.8cm))
#set text(font: ("Cambria", "Georgia", "Libertinus Serif"), size: 10pt, lang: "de", region: d.region)
#set text(font: d.schrift) if "schrift" in d
#set text(size: d.groesse * 1em) if "groesse" in d
#set par(leading: 0.6em)
#set list(indent: 0.3em, spacing: 0.45em * sp, marker: text(fill: accent)[◆])

#let section(title) = {
  v(1.1em * sp)
  align(center, {
    text(size: 11.5pt, fill: accent, tracking: 0.12em, smallcaps(title))
  })
  v(-0.5em)
  align(center, line(length: 30%, stroke: 0.6pt + accent))
  v(0.3em * sp)
}

#let entry(e) = {
  grid(
    columns: (1fr, auto),
    column-gutter: 0.8em,
    text(weight: "bold", e.titel),
    text(style: "italic", fill: muted, e.zeitraum),
  )
  if e.untertitel != "" { text(style: "italic", fill: accent, e.untertitel) }
  if e.punkte.len() > 0 {
    v(0.1em)
    list(..e.punkte)
  }
  v(0.6em * sp)
}

#align(center, {
  if d.foto != "" {
    box(clip: true, radius: 1.6cm * fs, width: 3.2cm * fs, height: 3.2cm * fs,
      image(d.foto, width: 3.2cm * fs, height: 3.2cm * fs, fit: "cover"))
    v(0.4em)
  }
  text(size: 24pt, fill: accent, tracking: 0.04em, smallcaps(p.name))
  if p.titel != "" {
    linebreak()
    text(size: 11pt, style: "italic", fill: muted, p.titel)
  }
  v(0.3em)
  text(size: 9pt, fill: muted, d.kontaktzeile)
  if kopf and d.angaben.len() > 0 {
    linebreak()
    text(size: 9pt, fill: muted, d.angaben.map(a => a.label + ": " + a.text).join("  ·  "))
  }
})
#v(0.2em)
#line(length: 100%, stroke: 0.8pt + accent)
#v(-0.75em)
#line(length: 100%, stroke: 0.3pt + accent)

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

#let unten = if kopf { d.kenntnisse } else { (..d.kenntnisse, ..d.angaben) }
#if unten.len() > 0 {
  section(if kopf { "Kenntnisse" } else { "Kenntnisse & Persönliches" })
  for k in unten {
    grid(columns: (3.4cm, 1fr), column-gutter: 0.8em, text(style: "italic", fill: muted, k.label), k.text)
    v(0.35em * sp)
  }
}

#if d.referenzen.len() > 0 {
  section("Referenzen")
  align(center, for r in d.referenzen {
    r
    linebreak()
  })
}
