# CineSort — Format d'export portable (RGPD Art. 20)

Spec du fichier JSON produit par `export_full_library()` (endpoint REST :
`POST /api/export_full_library`, ou bouton **Settings → Avancé → Exporter mes
données**).

## Pourquoi ?

RGPD Art. 20 garantit le droit à la portabilité : l'utilisateur doit pouvoir
récupérer ses données dans un format **structuré, couramment utilisé, lisible
par machine**, et les transmettre à un autre outil sans empêchement.

Cet export est le format CineSort. Il est conçu pour être lisible par n'importe
quel parseur JSON, sans dépendance à l'app.

## Structure (v1.0)

```json
{
  "ok": true,
  "version": "1.0",
  "exported_at": "2026-05-14T15:30:00Z",
  "app_version": "7.8.0",
  "last_done_run_id": "20260514_143000_001",
  "settings": { ... },
  "runs": [ ... ],
  "films": [ ... ],
  "film_count": 5234
}
```

### Champs racine

| Champ | Type | Description |
|-------|------|-------------|
| `ok` | bool | Toujours `true` sur export réussi |
| `version` | string | Version du format d'export (semver). Cette doc décrit v1.0 |
| `exported_at` | string | Timestamp ISO 8601 UTC de la génération |
| `app_version` | string | Version CineSort qui a produit l'export |
| `last_done_run_id` | string\|null | run_id du dernier scan complet (DONE) — la `films` list correspond à ce run |
| `settings` | object | Préférences utilisateur (cf section suivante) |
| `runs` | array | Liste des derniers 100 runs avec metadata |
| `films` | array | Films du `last_done_run_id` avec décisions + scores |
| `film_count` | int | Cardinality de `films` (pour vérif rapide) |

### `settings` — préférences sanitisées

Les réglages sensibles sont remplacés par `"***REDACTED***"` si la valeur était
présente, ou `""` si elle était vide. Le champ reste donc visible — vous savez
qu'une clé était configurée — mais sa valeur ne quitte jamais la machine.

Le critère est le **nom du réglage**, et non une liste à tenir à jour. Est
masqué tout réglage dont le nom se termine par `_api_key`, `_apikey`,
`_api-key`, `_token`, `_password` ou `_secret`, ainsi que ces mêmes mots
employés nus (`api_key`, `token`, `password`, `secret`...). C'est la règle
qu'applique déjà le nettoyage des journaux (`cinesort/infra/log_scrubber.py`) :
un suffixe est une propriété du nom, une liste est un inventaire à maintenir.

Sont donc masqués, entre autres : `tmdb_api_key`, `omdb_api_key`,
`jellyfin_api_key`, `radarr_api_key`, `plex_token`, `rest_api_token`,
`rest_api_token_secret` (l'enveloppe chiffrée, exclue même chiffrée) et
`email_smtp_password`.

Un nom qui *ressemble* à un secret sans en être un reste en clair, et c'est
voulu — sinon la ré-importation, objet même de l'export, serait cassée :
`rest_api_key_path` est un chemin de fichier, `email_smtp_user` une adresse,
`tmdb_key_protection` un indicateur d'état.

Tous les autres champs (URLs, chemins, toggles, seuils, profils qualité) sont
exportés tels quels. À la ré-import dans un autre outil, l'utilisateur devra
re-saisir manuellement ses clés API.

> **Corrigé le 2026-09-27.** Cette section décrivait une liste fermée de neuf
> clés. Elle nommait `smtp_password` — un réglage qu'aucun code du dépôt ne lit
> — et omettait `email_smtp_password`, le nom réel du mot de passe SMTP, qui
> sortait donc en clair. Le code a été corrigé le 2026-08-31 (masquage par
> suffixe, PR #1187) ; cette page ne l'avait pas suivi. Elle mentionnait aussi
> `ntfy_topic_secret` et `osdb_api_key`, deux réglages qui n'existent pas dans
> le produit.

### `runs` — historique des scans

Chaque entrée :

```json
{
  "run_id": "20260514_143000_001",
  "status": "DONE",         // DONE | FAILED | CANCELLED | RUNNING (rare)
  "start_ts": 1715690400.0, // Unix epoch en secondes
  "duration_s": 47.3,
  "total_rows": 5234
}
```

Pas de logs détaillés (gardés en local dans `state_dir/runs/<id>/`). L'export
sert la portabilité, pas l'archivage forensique.

### `films` — films du dernier run DONE

Chaque entrée :

```json
{
  "row_id": "uuid-...",
  "title": "Inception",
  "year": 2010,
  "folder": "C:\\Films\\Inception (2010)",
  "video": "Inception.2010.1080p.BluRay.x264.mkv",
  "kind": "single",            // single | collection | tv_episode
  "confidence": 92,
  "confidence_label": "high",
  "tmdb_collection_name": null, // ou "Saga ..."
  "edition": null,              // ou "Director's Cut", "Extended", ...
  "decision": {
    "ok": true,
    "title": "Inception",
    "year": 2010
  },
  "quality_score": 89,          // 0-100, null si pas encore scoré
  "quality_tier": "premium"     // premium | good | medium | bad | null
}
```

Le champ `decision` peut être `null` si l'utilisateur n'a pas encore validé.

## Comment ré-utiliser l'export

### Lire avec Python

```python
import json

with open("cinesort_export_20260514.json", encoding="utf-8") as f:
    data = json.load(f)

print(f"Export CineSort v{data['version']} du {data['exported_at']}")
print(f"{data['film_count']} films au total")
for film in data["films"]:
    if film["quality_tier"] == "premium":
        print(f"  * {film['title']} ({film['year']}) — score {film['quality_score']}")
```

### Migrer vers un autre outil

Le format est volontairement plat et explicite (un film = un objet). Pour
importer dans :

- **Jellyfin** : utiliser `folder` comme path source, ajouter `.nfo`
  manuellement à partir de `title`/`year`/`tmdb_collection_name`.
- **Radarr** : utiliser `title`+`year` comme clé de matching, le scan
  Radarr re-découvrira via TMDb.
- **Backup** : conserver le JSON complet (mediums : NAS, cloud) pour
  pouvoir restaurer dans CineSort plus tard.

### Re-import dans CineSort (non implémenté en v1.0)

L'import depuis ce format n'est pas encore implémenté côté CineSort. La
v1.0 du format est conçue pour permettre cette feature ultérieurement —
les champs nécessaires (titres, années, decisions, paths) sont tous présents.

## Privacy & RGPD

- L'export ne contient **aucune donnée tierce** : que les fichiers de
  l'utilisateur et ses préférences.
- Les **secrets** (API keys, tokens, passwords) ne sont **jamais** dans
  l'export, même chiffrés.
- L'export reste local à la machine — CineSort ne l'envoie nulle part.

## Versioning

Le format suit semver :
- **v1.x** : ajouts rétro-compatibles (nouveaux champs optionnels).
- **v2.x** : breaking changes (nouvelle structure racine).

Le champ `version` permet aux parseurs de gérer plusieurs versions.

## Limitations connues (v1.0)

- Seul le **dernier run DONE** a ses `films` exportés. Les runs précédents
  n'ont que leurs métadonnées dans `runs[]`. Pour exporter tous les runs,
  une v2 du format serait nécessaire.
- Les **rapports perceptuels** détaillés (doublons identifiés, scores LPIPS)
  ne sont pas inclus — uniquement le `quality_score` global par film.
- Les **logs** détaillés et l'audit JSONL sont gardés en local.

Cf issue #95 (GitHub) pour le scope complet et les évolutions prévues.
