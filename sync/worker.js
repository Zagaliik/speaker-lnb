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
 * Protocole :
 *   GET  /            -> { rev, updatedAt, device, data }
 *   PUT  /            <- { baseRev, device, data, force? }
 *                     -> 200 { rev, updatedAt }
 *                     -> 409 { erreur:"conflit", rev, updatedAt, device, data }
 * La cle passe dans l'en-tete X-Sync-Key (ou ?k= pour les requetes simples).
 */

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
