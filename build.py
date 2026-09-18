#!/usr/bin/env python3
"""Produit une version autonome de l'app avec les donnees LNB integrees dans la page."""
import json, pathlib, sys

base = pathlib.Path(__file__).parent
html = (base / "index.html").read_text(encoding="utf-8")
data = json.loads((base / "lnb-data.json").read_text(encoding="utf-8"))

# Le JSON part dans un <script type="application/json"> : seul "</" doit etre neutralise.
blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

if "__LNB_DATA__" not in html:
    sys.exit("gabarit __LNB_DATA__ introuvable")
out = html.replace("__LNB_DATA__", blob)

# La version integree n'a ni manifeste ni service worker a sa disposition.
out = out.replace('<link rel="manifest" href="manifest.webmanifest">\n', "")

dest = base / "dist" / "index.html"
dest.write_text(out, encoding="utf-8")
print(f"{dest} — {dest.stat().st_size/1024:.0f} Ko")
