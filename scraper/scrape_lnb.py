#!/usr/bin/env python3
"""
Recupere les donnees officielles LNB (equipes, effectifs, nationalites, stats, staff,
logos et photos) et produit un fichier JSON unique consommable hors ligne.

Les images sont redimensionnees puis embarquees en data: URI. C'est indispensable :
un lien vers assets.altrstat.xyz ne s'affiche ni sans reseau, ni dans un contexte
a politique de securite stricte.

API decouverte sur lnb.fr (backend IP-Web / altrstat) :
  GET  /api/token                                  (sur lnb.fr)  -> JWT valable ~15 min
  GET  competition/getMainCompetition?year=YYYY                  -> competitions de la saison
  GET  competition/getCompetitionTeams?competition_external_id=  -> equipes, logos, couleurs
  GET  teams/getRoster?team_external_id=                         -> joueurs + nationalite + stats
  POST altrstats/getCoachingStaff  (form-encoded: teamExternalId=) -> staff technique

Usage :
  python3 scrape_lnb.py [annee] [sortie.json] [--sans-images]
"""
import base64, io, json, os, shutil, subprocess, sys, tempfile, time
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

API = "https://api-prod.lnb.fr/"
TOKEN_URL = "https://lnb.fr/api/token"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/152 Safari/537.36"

DIVISIONS = {1: "Betclic ELITE", 2: "ELITE 2", 3: "Espoirs ELITE", 4: "Espoirs ELITE 2"}

PX_PHOTO = 96        # vignette visage (recadree)
PX_LOGO = 72         # logo equipe

# Nationalites en francais : l'API renvoie les libelles en anglais, or l'annonce se fait en francais.
PAYS_FR = {
    "ao": "Angola", "ag": "Antigua-et-Barbuda", "bb": "Barbade", "by": "Bielorussie",
    "be": "Belgique", "bj": "Benin", "ba": "Bosnie-Herzegovine", "br": "Bresil",
    "cm": "Cameroun", "ca": "Canada", "cg": "Congo", "cd": "Republique democratique du Congo",
    "hr": "Croatie", "ci": "Cote d'Ivoire", "ee": "Estonie", "fi": "Finlande",
    "fr": "France", "ga": "Gabon", "gm": "Gambie", "de": "Allemagne", "gh": "Ghana",
    "gr": "Grece", "gd": "Grenade", "gn": "Guinee", "ht": "Haiti", "hu": "Hongrie",
    "ir": "Iran", "ie": "Irlande", "it": "Italie", "jm": "Jamaique", "lb": "Liban",
    "mg": "Madagascar", "ml": "Mali", "me": "Montenegro", "ma": "Maroc",
    "nl": "Pays-Bas", "nz": "Nouvelle-Zelande", "ng": "Nigeria", "pt": "Portugal",
    "sn": "Senegal", "rs": "Serbie", "si": "Slovenie", "ss": "Soudan du Sud",
    "es": "Espagne", "se": "Suede", "ch": "Suisse", "bs": "Bahamas",
    "gb": "Royaume-Uni", "us": "Etats-Unis",
}

ROLES_FR = {
    "HEAD_COACH": "Entraineur",
    "ASSISTANT_COACH": "Entraineur adjoint",
    "ATHLETIC_TRAINER": "Preparateur physique",
    "PHYSIOTHERAPIST": "Kinesitherapeute",
    "DOCTOR": "Medecin",
    "TEAM_MANAGER": "Team manager",
    "GENERAL_MANAGER": "Manager general",
    "STATISTICIAN": "Statisticien",
    "VIDEO_ANALYST": "Analyste video",
}


# ---------------------------------------------------------------- images
try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False
HAVE_SIPS = shutil.which("sips") is not None


def _download(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://lnb.fr/"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception:
        return None


def _shrink_png(raw, px):
    """Redimensionne un PNG en conservant la transparence (logos)."""
    if HAVE_PIL:
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
            im.thumbnail((px, px), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            return buf.getvalue(), "image/png"
        except Exception:
            return None, None
    if HAVE_SIPS:
        tmp = tempfile.mkdtemp()
        try:
            src, dst = os.path.join(tmp, "in.png"), os.path.join(tmp, "out.png")
            open(src, "wb").write(raw)
            subprocess.run(["sips", "-Z", str(px), src, "--out", dst],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return open(dst, "rb").read(), "image/png"
        except Exception:
            return None, None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return None, None


# Fenetre de recadrage sur le visage, en proportion de la photo d'origine.
# Les portraits LNB sont cadres en buste : la tete occupe le haut, centree.
HEAD = (0.26, 0.03, 0.74, 0.51)      # gauche, haut, droite, bas


def _head_jpeg(raw, px):
    """Recadre sur la tete et sort un JPEG : quatre fois plus leger qu'un PNG
    pour une photo, et le visage devient lisible a petite taille."""
    l, t, r, b = HEAD
    if HAVE_PIL:
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
            W, H = im.size
            im = im.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
            fond = Image.new("RGB", im.size, (235, 237, 240))
            fond.paste(im, mask=im.split()[3])
            fond.thumbnail((px, px), Image.LANCZOS)
            buf = io.BytesIO()
            fond.save(buf, "JPEG", quality=72, optimize=True)
            return buf.getvalue(), "image/jpeg"
        except Exception:
            return None, None
    if HAVE_SIPS:
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "in.png")
            mid = os.path.join(tmp, "crop.png")
            dst = os.path.join(tmp, "out.jpg")
            open(src, "wb").write(raw)
            dim = subprocess.run(["sips", "-g", "pixelWidth", src],
                                 capture_output=True, text=True).stdout
            W = int(dim.strip().split(":")[-1])
            subprocess.run(["sips", "-c", str(int((b - t) * W)), str(int((r - l) * W)),
                            "--cropOffset", str(int(t * W)), str(int(l * W)), src, "--out", mid],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "72",
                            "-Z", str(px), mid, "--out", dst],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return open(dst, "rb").read(), "image/jpeg"
        except Exception:
            return None, None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return None, None


_thumbs = {}


def collect_thumbs(jobs, log=print):
    """jobs : liste de (url, nature). nature = "logo" (PNG) ou "head" (JPEG recadre)."""
    jobs = [(u, k) for (u, k) in dict.fromkeys(jobs) if u and u not in _thumbs]
    if not jobs:
        return
    if not (HAVE_PIL or HAVE_SIPS):
        log("  ! ni Pillow ni sips : images ignorees (pip install pillow)")
        return
    log(f"  {len(jobs)} images a preparer...")
    done = [0]

    def one(job):
        url, kind = job
        raw = _download(url)
        if not raw:
            return url, None
        data, mime = (_head_jpeg(raw, PX_PHOTO) if kind == "head" else _shrink_png(raw, PX_LOGO))
        done[0] += 1
        if done[0] % 150 == 0:
            log(f"    {done[0]}/{len(jobs)}")
        if not data:
            return url, None
        return url, "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")

    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, data in pool.map(one, jobs):
            _thumbs[url] = data
    ok = sum(1 for v in _thumbs.values() if v)
    log(f"  {ok} images embarquees")


def thumb(url):
    return _thumbs.get(url) if url else None


# ---------------------------------------------------------------- API
class Lnb:
    def __init__(self):
        self._tok = None
        self._exp = 0

    def token(self):
        if self._tok and time.time() < self._exp:
            return self._tok
        req = urllib.request.Request(TOKEN_URL, headers={"User-Agent": UA})
        self._tok = json.load(urllib.request.urlopen(req, timeout=30))["token"]
        self._exp = time.time() + 780          # le JWT vit 15 min, on renouvelle a 13
        return self._tok

    def call(self, path, body=None, form=False, retries=3):
        for attempt in range(retries):
            try:
                headers = {
                    "Authorization": "Bearer " + self.token(),
                    "device_type": "web",
                    "Origin": "https://lnb.fr",
                    "Referer": "https://lnb.fr/",
                    "User-Agent": UA,
                }
                data = None
                if body is not None:
                    if form:
                        data = urllib.parse.urlencode(body).encode()
                        headers["Content-Type"] = "application/x-www-form-urlencoded"
                    else:
                        data = json.dumps(body).encode()
                        headers["Content-Type"] = "application/json"
                req = urllib.request.Request(API + path, data=data, headers=headers)
                return json.load(urllib.request.urlopen(req, timeout=45))
            except urllib.error.HTTPError as e:
                if e.code == 401:                 # token expire -> on force le renouvellement
                    self._tok = None
                    continue
                if attempt == retries - 1:
                    raise
            except Exception:
                if attempt == retries - 1:
                    raise
            time.sleep(1.5 * (attempt + 1))

    def competitions(self, year):
        return self.call(f"competition/getMainCompetition?year={year}").get("data", [])

    def teams(self, cid):
        return self.call(f"competition/getCompetitionTeams?competition_external_id={cid}").get("data", [])

    def roster(self, tid):
        return self.call(f"teams/getRoster?team_external_id={tid}").get("data", [])

    def staff(self, tid):
        return self.call("altrstats/getCoachingStaff", {"teamExternalId": tid}, form=True).get("data", [])


# ---------------------------------------------------------------- mise en forme
def photo_url(node):
    # On part du 450px : le recadrage sur la tete en garde moins de la moitie.
    ph = (node or {}).get("photo") or {}
    return ph.get("md") or ph.get("sm")


def logo_urls(team):
    def pick(d):
        d = d or {}
        return d.get("sm") or d.get("md")
    return pick(team.get("logo_white")), pick(team.get("logo_black"))


def couleur(team):
    c = (team.get("colour_primary") or "").strip().lstrip("#")
    return "#" + c if len(c) == 6 else None


def clean_player(entry):
    """Aplatit une entree de roster en fiche joueur utile a l'annonce."""
    p = entry.get("person") or {}
    role = entry.get("player_role") or {}
    pos = (role.get("playing_position") or "").strip()
    return {
        "id": p.get("external_id"),
        "prenom": (p.get("first_name") or "").strip(),
        "nom": (p.get("family_name") or "").strip(),
        "numero": (role.get("shirt_number") or "").strip(),
        "poste": pos,
        "poste_court": pos.split(" - ")[0] if " - " in pos else pos,
        "nationalite": PAYS_FR.get((p.get("nationality_code") or "").lower(), p.get("nationality")),
        "code_pays": (p.get("nationality_code") or "").lower() or None,
        "taille": p.get("height"),
        "age": p.get("age"),
        "date_naissance": (p.get("dob") or "")[:10] or None,
        "photo": thumb(photo_url(p)),
        # Adresse pleine definition : sert a l'agrandissement quand il y a du reseau.
        "photo_url": photo_url(p),
        "stats": {
            "points": entry.get("s_points_average"),
            "rebonds": entry.get("s_rebounds_total_average"),
            "passes": entry.get("s_assists_average"),
            "evaluation": entry.get("s_efficiency_custom_average"),
        },
    }


def clean_staff(s):
    """Le staff est imbrique sous 'person', le role est dans role_type / sub_role_type."""
    p = s.get("person") or {}
    role_type = s.get("role_type") or ""
    return {
        "id": p.get("external_id"),
        "prenom": (p.get("first_name") or "").strip(),
        "nom": (p.get("family_name") or "").strip(),
        "role": ROLES_FR.get(role_type, (s.get("sub_role_type") or role_type.replace("_", " ").title()).strip()),
        "role_code": role_type,
        "photo": thumb(photo_url(p)),
        "photo_url": photo_url(p),
    }


def tri_numero(joueurs):
    return sorted(joueurs, key=lambda j: (j["numero"] == "",
                                          int(j["numero"]) if j["numero"].isdigit() else 999,
                                          j["nom"]))


# ---------------------------------------------------------------- collecte
def stats_saison_precedente(api, year, divisions, log=print):
    """La saison en cours demarre a 0. On recupere les stats de l'an dernier
    pour que l'annonce dispose de chiffres parlants des le premier match."""
    prev = str(int(year) - 1)
    index = {}
    try:
        comps = api.competitions(prev)
    except Exception as e:
        log(f"  (stats {prev} indisponibles: {e})")
        return index, prev
    for comp in comps:
        if comp["division_external_id"] not in divisions:
            continue
        try:
            teams = api.teams(comp["external_id"])
        except Exception:
            continue
        for t in teams:
            try:
                for r in api.roster(t["external_id"]):
                    pid = (r.get("person") or {}).get("external_id")
                    if not pid:
                        continue
                    st = {
                        "points": r.get("s_points_average"),
                        "rebonds": r.get("s_rebounds_total_average"),
                        "passes": r.get("s_assists_average"),
                        "evaluation": r.get("s_efficiency_custom_average"),
                    }
                    if any(v for v in st.values()):
                        index[pid] = {"equipe": t.get("team_name"), **st}
            except Exception:
                continue
            time.sleep(0.15)
    log(f"  stats {prev}/{int(prev)+1} : {len(index)} joueurs indexes")
    return index, prev


def scrape(year, divisions, avec_images=True, log=print):
    api = Lnb()
    log("Statistiques de la saison precedente...")
    stats_prev, prev_year = stats_saison_precedente(api, year, divisions, log)

    comps = api.competitions(year)
    if not comps:
        raise SystemExit(f"Aucune competition pour {year}")

    # Passe 1 : on aspire tout le brut, sans traiter les images.
    brut = []
    for comp in sorted(comps, key=lambda c: c["division_external_id"]):
        if comp["division_external_id"] not in divisions:
            continue
        cid = comp["external_id"]
        log(f"\n=== {comp['competition_name']} (cid={cid}) ===")
        equipes = []
        for t in api.teams(cid):
            tid = t["external_id"]
            try:
                roster = api.roster(tid)
            except Exception as e:
                log(f"  ! roster {t.get('team_name')}: {e}")
                roster = []
            try:
                staff = api.staff(tid)
            except Exception:
                staff = []
            log(f"  {t.get('team_name','?'):26} {len(roster):2} joueurs  {len(staff)} staff")
            equipes.append((t, roster, staff))
            time.sleep(0.25)          # on reste poli avec le serveur
        brut.append((comp, equipes))

    # Passe 2 : toutes les images d'un coup, en parallele.
    if avec_images:
        log("\n=== Images ===")
        jobs = []
        for comp, equipes in brut:
            for t, roster, staff in equipes:
                lw, lb = logo_urls(t)
                jobs += [(lw, "logo"), (lb, "logo")]
                for r in roster:
                    jobs.append((photo_url(r.get("person")), "head"))
                for membre in staff:
                    jobs.append((photo_url(membre.get("person")), "head"))
        collect_thumbs(jobs, log)

    # Passe 3 : mise en forme finale.
    out = {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "saison": f"{year}/{int(year)+1}",
        "annee": int(year),
        "source": "lnb.fr (API officielle)",
        "saison_stats_precedente": f"{prev_year}/{int(prev_year)+1}",
        "competitions": [],
    }
    for comp, equipes in brut:
        bloc = {
            "id": comp["external_id"],
            "division": comp["division_external_id"],
            "nom": comp["competition_name"],
            "abrev": comp["competition_abbrev"],
            "equipes": [],
        }
        for t, roster, staff in equipes:
            joueurs = [clean_player(r) for r in roster]
            joueurs = [j for j in joueurs if j["nom"] or j["prenom"]]
            for j in joueurs:
                j["stats_precedentes"] = stats_prev.get(j["id"])
            lw, lb = logo_urls(t)
            bloc["equipes"].append({
                "id": t["external_id"],
                "club_id": t.get("club_external_id"),
                "nom": t.get("team_name"),
                "nom_complet": t.get("team_nickname") or t.get("team_name"),
                "code": t.get("team_code"),
                "couleur": couleur(t),
                # Les deux variantes sont souvent identiques : on garde la version
                # couleur, posee sur une pastille claire dans l'application.
                "logo": thumb(lb) or thumb(lw),
                "joueurs": tri_numero(joueurs),
                "staff": sorted((clean_staff(s) for s in staff),
                                key=lambda m: (0 if m["role_code"] == "HEAD_COACH" else
                                               1 if m["role_code"] == "ASSISTANT_COACH" else 2,
                                               m["nom"])),
            })
        out["competitions"].append(bloc)
    return out



def fusionner(neuf, ancien_path, log=print):
    """Filet de securite : l'API renvoie parfois un effectif vide (constate sur les
    Espoirs en debut de saison). Plutot que de perdre des joueurs connus, on reprend
    ceux du fichier precedent. Leurs photos sont ecartees : elles viennent d'un autre
    cadrage et jureraient au milieu des portraits recents."""
    try:
        with open(ancien_path, encoding="utf-8") as f:
            ancien = json.load(f)
    except Exception:
        return neuf
    idx = {}
    for c in ancien.get("competitions", []):
        for e in c.get("equipes", []):
            idx[(c["id"], e["id"])] = e
    repris = 0
    for c in neuf["competitions"]:
        for e in c["equipes"]:
            if e["joueurs"]:
                continue
            anc = idx.get((c["id"], e["id"]))
            if not anc or not anc.get("joueurs"):
                continue
            for j in anc["joueurs"]:
                j = dict(j)
                j["photo"] = None
                j["effectif_repris"] = True
                e["joueurs"].append(j)
            if not e["staff"] and anc.get("staff"):
                e["staff"] = anc["staff"]
            repris += len(anc["joueurs"])
            log(f"  effectif repris du fichier precedent : {e['nom']} ({len(anc['joueurs'])} joueurs)")
    if repris:
        log(f"  {repris} joueurs conserves malgre un effectif vide cote API")
    return neuf


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    avec_images = "--sans-images" not in sys.argv
    year = args[0] if args else "2026"
    dest = args[1] if len(args) > 1 else "lnb-data.json"

    data = scrape(year, {1, 2, 3, 4}, avec_images)
    if os.path.exists(dest):
        data = fusionner(data, dest)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    tot_j = sum(len(e["joueurs"]) for c in data["competitions"] for e in c["equipes"])
    tot_e = sum(len(c["equipes"]) for c in data["competitions"])
    tot_l = sum(1 for c in data["competitions"] for e in c["equipes"] if e["logo"])
    tot_p = sum(1 for c in data["competitions"] for e in c["equipes"] for j in e["joueurs"] if j["photo"])
    mo = os.path.getsize(dest) / 1048576
    print(f"\nOK -> {dest}  |  {len(data['competitions'])} competitions, {tot_e} equipes, "
          f"{tot_j} joueurs, {tot_l} logos, {tot_p} photos  ({mo:.1f} Mo)")
