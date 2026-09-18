# Speaker LNB

Outil de préparation des annonces micro pour les rencontres LNB.
Effectifs, nationalités, statistiques officielles et staff sont récupérés sur
lnb.fr ; les compositions, arbitres et table de marque se préparent dans
l'application. **Tout fonctionne sans réseau une fois l'application installée.**

## Ce que contient le dossier

| Fichier | Rôle |
|---|---|
| `index.html` | L'application entière (aucune dépendance à installer) |
| `sw.js` | Cache hors ligne |
| `manifest.webmanifest`, `icon-*.png` | Installation sur l'écran d'accueil |
| `lnb-data.json` | Les données LNB : 4 compétitions, 72 équipes, 862 joueurs, 942 matchs, classements, 72 logos et 443 photos (4,3 Mo) |
| `scraper/scrape_lnb.py` | Le script qui régénère `lnb-data.json` |
| `sync/` | Service Cloudflare : synchronisation Mac ↔ iPad et relais vers l'API LNB |
| `build.py` | Fabrique une version autonome dans `dist/` (données intégrées à la page) |
| `.github/workflows/update-lnb.yml` | Mise à jour automatique chaque matin |

## Mise en ligne (une seule fois, ~10 minutes)

L'application doit être servie en HTTPS pour être installable et fonctionner
hors ligne. GitHub Pages fait ça gratuitement et héberge aussi la mise à jour
automatique.

1. **Créer le dépôt**

   Sur github.com : *New repository* → nom `speaker-lnb` → **Private** →
   *Create repository*.

2. **Envoyer les fichiers** depuis ce dossier :

   ```bash
   git init
   git add .
   git commit -m "Speaker LNB"
   git branch -M main
   git remote add origin https://github.com/TON-COMPTE/speaker-lnb.git
   git push -u origin main
   ```

3. **Activer Pages** : *Settings* → *Pages* → Source : `Deploy from a branch`,
   branche `main`, dossier `/ (root)` → *Save*.

   L'adresse apparaît après une minute :
   `https://TON-COMPTE.github.io/speaker-lnb/`

   > Un dépôt privé nécessite GitHub Pro pour publier des Pages. Si tu restes
   > sur un compte gratuit, mets le dépôt en public : il ne contient aucune
   > donnée personnelle — ta préparation reste sur tes appareils, jamais dans
   > le dépôt.

4. **Vérifier la mise à jour automatique** : onglet *Actions* → *Mise a jour des
   donnees LNB* → *Run workflow*. Elle tourne ensuite chaque matin à 7h et ne
   remplace le fichier que s'il est complet.

## Installation sur tes appareils

**iPad** — ouvrir l'adresse dans Safari → bouton Partager → *Sur l'écran
d'accueil*. L'application s'ouvre alors en plein écran, sans barre d'adresse.

**Mac** — ouvrir l'adresse dans Safari → *Fichier* → *Ajouter au Dock*
(ou dans Chrome : icône d'installation dans la barre d'adresse).

Après cette première ouverture, les données sont stockées sur l'appareil :
coupure réseau ou mode avion, l'application reste complète.

## Hors ligne : ce qui marche, ce qui ne marche pas

| | Sans réseau |
|---|---|
| Compositions, 5 majeur, conducteur | ✅ |
| Annuaires arbitres et table de marque | ✅ |
| Prononciations notées | ✅ |
| Bouton *Actualiser* | ❌ — reprend dès le retour du réseau |

Les deux appareils gardent leur propre préparation. Pour transférer un annuaire
de l'un à l'autre : onglet *Données* → *Exporter*, puis *Importer* sur l'autre.

## Les images

Logos et photos sont **redimensionnés puis embarqués dans `lnb-data.json`** en
data: URI. C'est volontaire : un lien vers le serveur d'images de la LNB ne
s'afficherait pas sans réseau, ce qui viderait le conducteur de ses repères
visuels en plein match.

Le redimensionnement utilise Pillow, ou `sips` à défaut (déjà présent sur macOS).
Pour régénérer sans images — fichier dix fois plus léger :

```bash
python3 scraper/scrape_lnb.py 2026 lnb-data.json --sans-images
```

## Changer de saison

Le script prend l'année de début de saison en argument :

```bash
python3 scraper/scrape_lnb.py 2027 lnb-data.json
```

Pour l'automatisation, définir la variable `LNB_SEASON` dans
*Settings* → *Secrets and variables* → *Actions* → *Variables*.

## D'où viennent les données

L'application interroge l'API publique qui alimente lnb.fr :

| Donnée | Endpoint |
|---|---|
| Compétitions de la saison | `competition/getMainCompetition?year=` |
| Équipes d'une compétition | `competition/getCompetitionTeams?competition_external_id=` |
| Effectif, nationalités, stats | `teams/getRoster?team_external_id=` |
| Staff technique | `altrstats/getCoachingStaff` (POST, `teamExternalId=`) |

Un jeton est demandé à `lnb.fr/api/token` et renouvelé automatiquement
(durée de vie : 15 minutes).

Ces endpoints ne sont pas documentés publiquement : la LNB peut les modifier
sans préavis. Si une mise à jour échoue, l'application continue de fonctionner
avec les dernières données valides — c'est le rôle du garde-fou dans le
workflow. Le script reste volontairement peu gourmand (une requête toutes les
250 ms).

**Les arbitres et les officiels de table ne sont pas publiés par la LNB.**
Ces deux annuaires se remplissent à la main, une fois par personne, et se
conservent d'une rencontre à l'autre.
