/**
 * Synchronisation de la preparation Speaker LNB entre appareils.
 *
 * Un seul document par cle : la preparation complete (compositions, annuaires,
 * prononciations). Elle est petite — quelques kilo-octets — donc on la transmet
 * entiere plutot que de gerer des deltas, ce qui evite toute fusion hasardeuse.
 *
 * D1 (et non KV) parce que KV est a coherence differee : une ecriture peut mettre
 * jusqu'a une minute a se propager, ce qui est incompatible avec "instantane".
 *
 * Il sert aussi de relais vers l'API de la LNB : le navigateur ne peut pas
 * l'interroger directement (CORS), alors que le Worker le peut. C'est ce qui rend
 * le classement et le calendrier actualisables en direct, sans attendre la
 * regeneration quotidienne du fichier de donnees.
 *
 * Protocole :
 *   GET  /            -> { rev, updatedAt, device, data }
 *   PUT  /            <- { baseRev, device, data, force? }
 *                     -> 200 { rev, updatedAt }
 *                     -> 409 { erreur:"conflit", rev, updatedAt, device, data }
 * La cle passe dans l'en-tete X-Sync-Key (ou ?k= pour les requetes simples).
 *
 *   GET  /lnb/standings?cid=317
 *   GET  /lnb/calendar?abbrev=PROA&div=1&year=2026
 *   POST /lnb/api        <- { path, body, form? }  relais generique, chemins LNB seulement
 *   GET  /lnb/img?u=...                      relais d'image, assets.altrstat.xyz seulement
 *
 * Ces deux dernieres routes existent parce que la LNB refuse les adresses des
 * serveurs GitHub (403) : la collecte quotidienne passe donc par ici.
 * Ces deux routes sont publiques : elles ne renvoient que des donnees deja
 * publiques sur lnb.fr, et n'exposent aucune preparation.
 */

const API = "https://api-prod.lnb.fr/";
const ASSETS = "https://assets.altrstat.xyz/";

// Le relais generique n'accepte que les chemins de l'API LNB : il ne doit jamais
// pouvoir servir a joindre autre chose.
const CHEMINS_LNB = /^(competition|teams|altrstats|match|common)\//;

async function jeton() {
  const r = await fetch("https://lnb.fr/api/token", {
    headers: { "User-Agent": "Mozilla/5.0", "Accept": "application/json" },
  });
  if (!r.ok) throw new Error("jeton indisponible");
  return (await r.json()).token;
}

async function appelLnb(chemin, corps, form) {
  const t = await jeton();
  // getCoachingStaff est le seul point d'entree qui refuse le JSON : il lui faut
  // un corps form-encode. Le transformer en parametre d'URL renvoie une liste vide.
  let type = null;
  let charge;
  if (corps != null) {
    if (form) {
      type = "application/x-www-form-urlencoded";
      charge = new URLSearchParams(corps).toString();
    } else {
      type = "application/json";
      charge = JSON.stringify(corps);
    }
  }
  const r = await fetch(API + chemin, {
    method: corps != null ? "POST" : "GET",
    headers: {
      Authorization: "Bearer " + t,
      device_type: "web",
      Origin: "https://lnb.fr",
      Referer: "https://lnb.fr/",
      ...(type ? { "Content-Type": type } : {}),
    },
    body: charge,
  });
  if (!r.ok) throw new Error("LNB " + r.status);
  return r.json();
}

/** Relais LNB, avec un cache court : le classement ne bouge qu'apres un match. */
async function relais(url, request) {
  const cache = caches.default;
  const clef = new Request(url.toString(), { method: "GET" });
  const garde = await cache.match(clef);
  if (garde) return garde;

  let charge;
  try {
    if (url.pathname === "/lnb/standings") {
      const cid = Number(url.searchParams.get("cid"));
      if (!cid) return reponse({ erreur: "cid_absent" }, 400);
      charge = await appelLnb("altrstats/getStandingByCompetition", {
        competition_external_id: cid,
        competition_filter_name: "GENERAL",
        round_numbers: "",
      });
    } else {
      const abbrev = url.searchParams.get("abbrev") || "";
      const div = url.searchParams.get("div") || "";
      const year = url.searchParams.get("year") || "";
      if (!abbrev || !div || !year) return reponse({ erreur: "parametres_absents" }, 400);
      charge = await appelLnb("match/v3/getCalendar", {
        year: String(year), competition_abbrev: abbrev,
        division_external_id: String(div), team_external_id: 0,
        round_number: 0, phase_id: 0, tournament_number: 0,
        direction: "initial", limit: 500,
      });
    }
  } catch (e) {
    return reponse({ erreur: "lnb_injoignable", detail: String(e.message || e) }, 502);
  }

  const res = new Response(JSON.stringify(charge), {
    headers: { ...CORS, "Content-Type": "application/json; charset=utf-8",
               "Cache-Control": "public, max-age=60" },
  });
  await cache.put(clef, res.clone());
  return res;
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,PUT,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type,X-Sync-Key",
  "Access-Control-Max-Age": "86400",
};

function reponse(obj, statut = 200) {
  return new Response(JSON.stringify(obj), {
    status: statut,
    headers: { ...CORS, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });

    const url = new URL(request.url);

    // Relais generique, pour la collecte quotidienne depuis GitHub.
    if (url.pathname === "/lnb/api") {
      if (request.method !== "POST") return reponse({ erreur: "methode_non_supportee" }, 405);
      let corps;
      try {
        corps = await request.json();
      } catch {
        return reponse({ erreur: "json_invalide" }, 400);
      }
      const chemin = String(corps.path || "");
      if (!CHEMINS_LNB.test(chemin)) return reponse({ erreur: "chemin_refuse" }, 403);
      try {
        return reponse(await appelLnb(chemin, corps.body, corps.form === true));
      } catch (e) {
        return reponse({ erreur: "lnb_injoignable", detail: String(e.message || e) }, 502);
      }
    }

    // Relais d'images, strictement limite au serveur d'assets de la LNB.
    if (url.pathname === "/lnb/img") {
      const cible = url.searchParams.get("u") || "";
      if (!cible.startsWith(ASSETS)) return reponse({ erreur: "source_refusee" }, 403);
      const r = await fetch(cible, {
        headers: { "User-Agent": "Mozilla/5.0", Referer: "https://lnb.fr/" },
      });
      if (!r.ok) return reponse({ erreur: "image_indisponible", code: r.status }, 502);
      return new Response(r.body, {
        status: 200,
        headers: {
          ...CORS,
          "Content-Type": r.headers.get("content-type") || "image/png",
          "Cache-Control": "public, max-age=86400",
        },
      });
    }

    // Relais LNB : pas de cle, ces donnees sont publiques.
    if (url.pathname.startsWith("/lnb/")) {
      if (request.method !== "GET") return reponse({ erreur: "methode_non_supportee" }, 405);
      return relais(url, request);
    }

    const cle = request.headers.get("X-Sync-Key") || url.searchParams.get("k") || "";

    // La cle fait office de mot de passe : on impose une longueur serieuse.
    if (!/^[A-Za-z0-9_-]{24,80}$/.test(cle)) {
      return reponse({ erreur: "cle_invalide" }, 400);
    }

    if (request.method === "GET") {
      const ligne = await env.DB.prepare(
        "SELECT rev, updated, device, data FROM etat WHERE cle = ?"
      ).bind(cle).first();
      if (!ligne) return reponse({ rev: 0, data: null });
      return reponse({
        rev: ligne.rev,
        updatedAt: ligne.updated,
        device: ligne.device,
        data: JSON.parse(ligne.data),
      });
    }

    if (request.method === "PUT") {
      let corps;
      try {
        corps = await request.json();
      } catch {
        return reponse({ erreur: "json_invalide" }, 400);
      }
      if (!corps || typeof corps.data !== "object" || corps.data === null) {
        return reponse({ erreur: "donnees_absentes" }, 400);
      }

      const brut = JSON.stringify(corps.data);
      if (brut.length > 2_000_000) return reponse({ erreur: "trop_volumineux" }, 413);

      const actuel = await env.DB.prepare(
        "SELECT rev, updated, device, data FROM etat WHERE cle = ?"
      ).bind(cle).first();
      const revActuelle = actuel ? actuel.rev : 0;

      // L'appareil ecrit a partir d'une revision connue. Si le serveur a bouge
      // entre-temps, c'est que l'autre appareil a modifie : on refuse et on renvoie
      // sa version, a l'utilisateur de trancher.
      if (!corps.force && Number(corps.baseRev || 0) !== revActuelle) {
        return reponse({
          erreur: "conflit",
          rev: revActuelle,
          updatedAt: actuel ? actuel.updated : null,
          device: actuel ? actuel.device : null,
          data: actuel ? JSON.parse(actuel.data) : null,
        }, 409);
      }

      const rev = revActuelle + 1;
      const maintenant = new Date().toISOString();
      await env.DB.prepare(
        `INSERT INTO etat (cle, rev, updated, device, data) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(cle) DO UPDATE SET rev = excluded.rev, updated = excluded.updated,
                                        device = excluded.device, data = excluded.data`
      ).bind(cle, rev, maintenant, String(corps.device || ""), brut).run();

      return reponse({ rev, updatedAt: maintenant });
    }

    return reponse({ erreur: "methode_non_supportee" }, 405);
  },
};
