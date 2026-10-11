#let d = json("cv.json")
#let p = d.persoenlich
#let u = d.at("ueberschriften", default: (:))
#let t(key, fallback) = u.at(key, default: fallback)
#let accent = rgb(d.akzent)
#let muted = rgb("#6b6b6b")
#let sp = d.at("abstand", default: 1.0)
#let fs = d.at("fotofaktor", default: 1.0)
#let kopf = d.at("angaben_im_kopf", default: false)

#set document(title: "Lebenslauf " + p.name)
#set page(paper: "a4", margin: (x: 2.2cm, y: 2cm))
#set text(font: ("Arial", "Helvetica", "Liberation Sans"), size: 9.5pt, lang: "de", region: d.region)
#set text(font: d.schrift) if "schrift" in d
#set text(size: d.groesse * 1em) if "groesse" in d
#set par(leading: 0.6em)
#set list(indent: 0em, spacing: 0.45em * sp, marker: text(fill: muted)[–])

#let section(title) = {
  v(1.3em * sp)
  text(size: 8.5pt, weight: "bold", fill: accent, tracking: 0.18em, upper(title))
  v(0.4em * sp)
}

#let row(left, right) = {
  grid(columns: (3.4cm, 1fr), column-gutter: 0.8em, text(fill: muted, left), right)
  v(0.3em * sp)
}

#let entry(e) = row(e.zeitraum, {
  text(weight: "bold", e.titel)
  if e.untertitel != "" {
    linebreak()
    text(fill: muted, e.untertitel)
  }
  if e.punkte.len() > 0 {
    v(0.15em)
    list(..e.punkte)
  }
})

#grid(
  columns: (1fr, auto),
  column-gutter: 1em,
  align(horizon, {
    text(size: 22pt, weight: "light", fill: accent, tracking: 0.02em, p.name)
    if p.titel != "" {
      linebreak()
      text(size: 10.5pt, fill: muted, p.titel)
    }
    v(0.5em)
    text(size: 8.5pt, fill: muted, d.kontaktzeile)
    if kopf and d.angaben.len() > 0 {
      v(0.4em)
      set text(size: 8.5pt)
      grid(columns: (auto, 1fr), column-gutter: 1em, row-gutter: 0.35em,
        ..d.angaben.map(a => (text(fill: muted, a.label), a.text)).flatten())
    }
  }),
  if d.foto != "" { image(d.foto, width: 2.8cm * fs) } else [],
)
#v(0.4em)
#line(length: 100%, stroke: 0.4pt + rgb("#cccccc"))

#if d.kurzprofil != "" {
  section(t("profil", "Profil"))
  par(justify: true, d.kurzprofil)
}

#if d.angaben.len() > 0 and not kopf {
  section(t("angaben", "Persönliche Angaben"))
  for a in d.angaben { row(a.label, a.text) }
}

#if d.berufserfahrung.len() > 0 {
  section(t("berufserfahrung", "Berufserfahrung"))
  for e in d.berufserfahrung { entry(e) }
}

#if d.ausbildung.len() > 0 {
  section(t("ausbildung", "Ausbildung"))
  for e in d.ausbildung { entry(e) }
}

#if d.projekte.len() > 0 {
  section(t("projekte", "Projekte"))
  for e in d.projekte { entry(e) }
}

#if d.kenntnisse.len() > 0 {
  section(t("kenntnisse", "Kenntnisse"))
  for k in d.kenntnisse { row(k.label, k.text) }
}

#if d.referenzen.len() > 0 {
  section(t("referenzen", "Referenzen"))
  for r in d.referenzen { row("", r) }
}
