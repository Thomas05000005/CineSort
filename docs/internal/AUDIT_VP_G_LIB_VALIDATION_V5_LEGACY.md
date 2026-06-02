# VP-G Audit prealable : lib-validation.js v5 + legacy

> **Lot** : VP-G (Vague P) — Item VP-4-LIBRARY-UI-INTEGRATION
> **Fix # cible** : Fix #3 de ROADMAP_VAGUE_P.md (audit v5+legacy avant cablage)
> **Date** : 2026-06-02
> **Statut** : audit termine → fallback strict legacy-first applique
> **Memo** : `feedback_cinesort_v76_ui` (overlays mutuels, coexistence v5+legacy, endpoints dans `*_support.py`)

## 1. Perimetre

Le fichier `web/dashboard/views/library/lib-validation.js` est l'unique vue
"validation" cote frontend. Il sert a la fois :

- **Legacy** : 3 colonnes / 9 colonnes du run actif (tableHtml, presets,
  filtres confidence/source, recherche).
- **v5** : modale inspecteur film avec waterfall scoring (VO-C frontend),
  resolution rule_id -> nom via `get_quality_profile`, et le tri-etat
  accepted/rejected/deferred (VP-D).

## 2. Overlays mutuels detectes

| Zone                          | Legacy                          | v5                                          | Conflit ?      | Strategie                                                              |
|-------------------------------|----------------------------------|---------------------------------------------|----------------|-------------------------------------------------------------------------|
| Bouton "✓/✗" par ligne        | 2 actions (approve/reject)       | 3 actions (approve/defer/reject)            | NON            | v5 ajoute le bouton "⏸" entre les deux, pas de remplacement            |
| Coloration ligne              | `.row-approved` / `.row-rejected`| ajout `.row-deferred`                       | NON            | toggling 3-state, classes nettoyees avant ajout                        |
| Compteurs                     | "X approuve / Y rejete"          | ajout "Y reporte"                            | NON            | wrapper badge supplementaire                                           |
| Payload `save_validation`     | `{ok:bool}`                      | `{ok, decision: accepted/rejected/deferred}`| NON            | helper backend `to_legacy_ok_bool` preserve `{ok:bool}`                |
| Bulk "Tout rejeter"           | `confirm()` natif (avant VP-D)   | `dangerConfirmModal` + countdown 3s si >50  | OUI (resolu)   | VP-D a remplace `confirm()` natif par `dangerConfirmModal` (cf L829)   |
| Bulk "Reinitialiser"          | reset direct sans modal          | reset direct sans modal                     | OUI (a fixer)  | **VP-G** : ajout `dangerConfirmModal` (cf section 4 ci-dessous)        |
| Field locks UI                | inexistant                       | `setFieldLock`, `loadFieldLocks`,           | OUI (a fixer)  | **VP-G** : endpoints backend manquants -> 404 cote frontend            |
|                               |                                  | `fieldLockToggleHtml`, `confirmRebuildAll`  |                | (cf section 3 ci-dessous)                                              |
| Inspecteur modale (waterfall) | non present                      | `_renderScoreWaterfall` + suggestions       | NON            | additif, n'overlay rien                                                |

## 3. Conflit critique #1 : endpoints field_locks absents cote backend

### Constat

Le fichier `lib-validation.js` (lignes 949-997) declare 3 fonctions exportees
qui appellent ces endpoints :

| Endpoint frontend                | Methode CineSortApi (cible) | Etat                                          |
|----------------------------------|-----------------------------|-----------------------------------------------|
| `library/set_field_lock`         | (manquante)                 | **404 actuellement** : aucune route exposee   |
| `library/clear_field_lock`       | (manquante)                 | **404 actuellement** : aucune route exposee   |
| `library/list_field_locks`       | (manquante)                 | **404 actuellement** : aucune route exposee   |

Cote backend, `FieldLocksRepository` existe deja avec l'API
`set_lock` / `clear_lock` / `list_locks` / `is_locked` /
`get_lock` / `migrate_locks` (cf `cinesort/infra/db/repositories/field_locks.py`).

Mais aucune methode publique de `LibraryFacade`, ni aucun `*_impl` sur
`CineSortApi`, ne route les appels frontend vers ce repository.

### Decision (VP-G)

**Cabler** explicitement 3 nouvelles methodes sur `LibraryFacade` qui
delegueent vers `library_support` :

- `library_facade.set_field_lock(film_id, field_name, locked_value, source)`
- `library_facade.clear_field_lock(film_id, field_name)`
- `library_facade.list_field_locks(film_id)`

L'introspection de `rest_server._get_api_methods` les enregistrera
automatiquement sous `/api/library/set_field_lock`, etc. (cf pass 2 du
dispatcher).

**Backward compat ABSOLUE** : aucune route existante n'est modifiee. Les
3 endpoints sont AJOUTES, jamais ALTER.

**Memo `feedback_cinesort_v76_ui` respect** : les endpoints vivent dans
`library_support.py` (pas dans un controller), avec la facade comme
unique point d'entree UI.

## 4. Conflit critique #2 : action "Reinitialiser" destructive sans confirmation

### Constat

Ligne 836 de `lib-validation.js` :

```js
$("libBtnResetDec")?.addEventListener("click", () => {
  _state.decisions = new Map();
  _renderTable();
  _updateCounters();
});
```

Cette action efface **toutes** les decisions accepted/rejected/deferred
sans confirmation. Cliquer accidentellement perd potentiellement des
heures de revue manuelle.

### Decision (VP-G)

Ajouter une **modale `dangerConfirmModal`** systematique avant le reset,
avec :

- Liste : aucune (l'action concerne tout l'etat _state.decisions, pas
  une liste d'items).
- Consequence : "Toutes les decisions accepted/rejected/deferred seront
  effacees. Le brouillon de validation revient a vide."
- Countdown 3s **si plus de 50 decisions** posees (memo
  `feedback_cinesort_actions_dangereuses`).
- Si zero decision posee : pas de modal (no-op deguise).

## 5. Conflit a surveiller : "Tout reconstruire" / mode field_lock

`confirmRebuildAll` (L911) existe deja avec countdown 3s si >50, OK
selon AC-5 VP-G.

Pas d'action a prendre, mais `confirmRebuildAll` doit etre branche sur
un bouton UI reel (il est exporte mais aucun bouton `data-action=
"rebuild-all"` ne le declenche actuellement dans `lib-validation.js`).

**Decision (VP-G)** : laisser exporte pour usage futur dans une vue
"Edition de masse" (hors perimetre de VP-G qui se limite a la table
validation actuelle). L'export reste en place pour la coexistence avec
les futurs ecrans Vague Q+.

## 6. Synthese

| Conflit                                | Action VP-G                                                            |
|----------------------------------------|------------------------------------------------------------------------|
| #1 endpoints field_locks manquants     | AJOUTER `library/set_field_lock` + `library/clear_field_lock` + `library/list_field_locks` |
| #2 reset destructif sans modal         | AJOUTER `dangerConfirmModal` sur `libBtnResetDec`                      |
| Autres overlays                        | Aucun conflit, coexistence v5+legacy OK                                |

**Strategie globale** : **legacy-first** (memo `feedback_cinesort_v76_ui`)
respecte. Aucune signature existante n'est cassee. Les nouveautes
VP-A/C/D sont des ajouts purs.

## 7. Tier colors INVARIANTES

Verification effectuee : `web/shared/tokens.css` non modifie. Les nouveaux
composants (badges deferred, score-waterfall) reutilisent les tokens
existants `--sev-warning-bg` / `--sev-success-bg` / `--sev-danger-bg`.

Tokens `--tier-platinum-solid` (#FFD700), `--tier-gold-solid` (#22C55E),
`--tier-silver-solid` (#3B82F6), `--tier-bronze-solid` (#F59E0B),
`--tier-reject-solid` (#EF4444), `--tier-unknown-solid` (#6B7280) :
**inchanges** dans toute la Vague P.

## 8. Acceptance VP-G

| AC   | Critere                                                     | Statut post-fix     |
|------|-------------------------------------------------------------|---------------------|
| AC-1 | Audit v5+legacy documente avant cablage                     | OK (ce document)    |
| AC-2 | Scenario E2E green sur biblio reelle (853 films)            | A valider en run    |
| AC-3 | `node --check lib-validation.js` + F12 console verifiees    | OK (cf commit)      |
| AC-4 | Tier colors hex INVARIANTES (regression visuelle verifiee)  | OK (tokens.css non touche) |
| AC-5 | Zero action destructive UI library sans `dangerConfirmModal`| OK apres fix #2     |
