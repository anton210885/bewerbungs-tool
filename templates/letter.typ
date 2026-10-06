#let d = json("letter.json")
#let accent = rgb(d.at("akzent", default: "#1f4e79"))
#let muted = rgb("#555555")

#set document(title: d.betreff)
#set page(paper: "a4", margin: (left: 2.5cm, right: 2cm, top: 2cm, bottom: 2cm))
#set text(font: ("Calibri", "Carlito", "Arial", "Liberation Sans"), size: 11pt, lang: "de", region: d.region)
#set text(font: d.schrift) if "schrift" in d
#set text(size: d.groesse * 1em) if "groesse" in d
#set par(justify: true, leading: 0.65em, spacing: 1.1em)

#text(size: 16pt, weight: "bold", fill: accent, d.absender.name)
#v(-0.6em)
#text(size: 9.5pt, fill: muted, d.kontaktzeile)
#v(-0.6em)
#line(length: 100%, stroke: 0.6pt + accent)

#v(1.2cm)
#d.empfaenger.join(linebreak())

#v(1cm)
#align(right, d.ort_datum)

#v(0.6cm)
#text(weight: "bold", fill: accent, d.betreff)

#v(0.3cm)
#d.anrede

#for absatz in d.absaetze {
  par(absatz)
}

#d.gruss

#v(1.2cm)
#d.absender.name

#v(0.8cm)
#text(size: 9.5pt, fill: muted, d.anlagen)
