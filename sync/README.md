# Service de synchronisation

Petit service Cloudflare qui transporte **ta préparation** (compositions,
annuaires, prononciations) entre ton Mac et ton iPad. Les données LNB, elles,
ne passent pas par là : elles sont mises à jour par l'action GitHub quotidienne.

## Pourquoi D1 et pas KV

Cloudflare KV est à cohérence différée : une écriture peut mettre jusqu'à une
minute à se propager. Incompatible avec une synchronisation qu'on veut
instantanée. D1 est cohérent immédiatement.

## Installation depuis le tableau de bord

Node n'étant pas installé, on passe par l'interface web plutôt que par
`wrangler`. Compte cinq minutes.

**1. La base de données**

Tableau de bord Cloudflare → *Storage & Databases* → *D1* → *Create database*
→ nom : `speaker-lnb` → *Create*.

Ouvre-la, onglet *Console*, colle ceci et exécute :

```sql
CREATE TABLE IF NOT EXISTS etat (
  cle     TEXT PRIMARY KEY,
  rev     INTEGER NOT NULL,
  updated TEXT    NOT NULL,
  device  TEXT,
  data    TEXT    NOT NULL
);
```

**2. Le service**

*Workers & Pages* → *Create* → *Start with Hello World* → nom :
`speaker-lnb-sync` → *Deploy*.

Puis *Edit code* : remplace tout le contenu par celui de `worker.js`
(dans ce dossier) → *Deploy*.

**3. Le raccordement**

Dans le Worker → *Settings* → *Bindings* → *Add binding* → *D1 database* :

| Champ | Valeur |
|---|---|
| Variable name | `DB` |
| D1 database | `speaker-lnb` |

*Save and deploy*.

**4. Dans l'application**

Note l'adresse du Worker (`https://speaker-lnb-sync.….workers.dev`), puis dans
l'application : onglet *Données* → *Synchronisation* → *Configurer*.

- Colle l'adresse
- *Générer une clé*, puis **note-la** : il faut la même sur l'iPad
- *Activer*

Répète sur l'iPad avec la **même adresse et la même clé**.

## Comment ça se comporte

| Situation | Ce qui se passe |
|---|---|
| Modification sur un appareil | Envoyée après une seconde, reçue par l'autre en trois secondes au plus |
| Coupure réseau | L'appareil continue seul ; l'envoi se fait au retour de la connexion |
| Les deux modifiés hors ligne | Une fenêtre demande laquelle garder — **jamais de fusion silencieuse** |
| Réveil de l'application | Récupération immédiate au retour sur l'onglet |

## Sécurité

La clé est le seul secret : qui la possède accède à ta préparation. Elle fait
32 caractères aléatoires. Le service ne stocke rien d'autre que le document
associé à cette clé. Pour en changer, génère une nouvelle clé sur les deux
appareils — l'ancien document devient inaccessible et pourra être supprimé
depuis la console D1.
