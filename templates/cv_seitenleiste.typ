#let d = json("cv.json")
#let p = d.persoenlich
#let accent = rgb(d.akzent)
#let muted = rgb("#555555")
#let side-width = 6.4cm

#set document(title: "Lebenslauf " + p.name)
#set page(
  paper: "a4",
  margin: (left: 0pt, right: 1.5cm, top: 1.4cm, bottom: 1.4cm),
  background: place(left + top, rect(width: side-width, height: 100%, fill: accent)),
)
#set text(font: ("Calibri", "Carlito", "Arial", "Liberation Sans"), size: 9.5pt, lang: "de", region: d.region)
#set text(font: d.schrift) if "schrift" in d
#set text(size: d.groesse * 1em) if "groesse" in d
#set par(leading: 0.55em)
#set list(indent: 0.1em, spacing: 0.4em, marker: text(fill: accent)[•])

#let side-title(t) = {
  v(1.1em)
  text(size: 10pt, weight: "bold", fill: white, tracking: 0.08em, upper(t))
  v(-0.55em)
  line(length: 100%, stroke: 0.5pt + white.transparentize(40%))
  v(0.15em)
}

#let main-title(t) = {
  v(1em)
  text(size: 12pt, weight: "bold", fill: accent, tracking: 0.05em, upper(t))
  v(-0.55em)
  line(length: 100%, stroke: 0.7pt + accent)
  v(0.2em)
}

#let entry(e) = {
  grid(
    columns: (1fr, auto),
    column-gutter: 0.6em,
    text(weight: "bold", e.titel),
    text(size: 8.5pt, fill: accent, e.zeitraum),
  )
  if e.untertitel != "" { text(style: "italic", fill: muted, e.untertitel) }
  if e.punkte.len() > 0 {
    v(0.15em)
    list(..e.punkte)
  }
  v(0.55em)
}

#let sidebar = block(width: 100%, inset: (x: 0.7cm), {
  set text(fill: white)
  if d.foto != "" {
    align(center, box(clip: true, radius: 1.8cm, width: 3.6cm, height: 3.6cm,
      image(d.foto, width: 3.6cm, height: 3.6cm, fit: "cover")))
  }
  if d.kontakt.len() > 0 {
    side-title("Kontakt")
    for k in d.kontakt {
      k
      linebreak()
    }
  }
  if d.angaben.len() > 0 {
    side-title("Persönliches")
    for a in d.angaben {
      text(size: 8.5pt, fill: white.transparentize(30%), a.label)
      linebreak()
      a.text
      v(0.35em)
    }
  }
  for k in d.kenntnisse {
    side-title(k.label)
    k.text
  }
})

#let main = {
  text(size: 24pt, weight: "bold", fill: accent, p.name)
  if p.titel != "" {
    linebreak()
    text(size: 12pt, fill: muted, p.titel)
  }
  if d.kurzprofil != "" {
    main-title("Profil")
    par(justify: true, d.kurzprofil)
  }
  if d.berufserfahrung.len() > 0 {
    main-title("Berufserfahrung")
    for e in d.berufserfahrung { entry(e) }
  }
  if d.ausbildung.len() > 0 {
    main-title("Ausbildung")
    for e in d.ausbildung { entry(e) }
  }
  if d.projekte.len() > 0 {
    main-title("Projekte")
    for e in d.projekte { entry(e) }
  }
  if d.referenzen.len() > 0 {
    main-title("Referenzen")
    for r in d.referenzen {
      r
      v(0.2em)
    }
  }
}

#grid(columns: (side-width, 1fr), column-gutter: 0.9cm, sidebar, main)
