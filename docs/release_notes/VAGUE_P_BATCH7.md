# Vague P batch 7 - VP-G Audit complementaire & integration finale UI library

## Resume technique

Septieme et dernier batch de la Vague P : sub-lot **VP-G**
(`VP-G-4-LIBRARY-UI-INTEGRATION`) - **cablage final** des features
VP-A / VP-C / VP-D dans `web/dashboard/views/library/lib-validation.js`,
precede d'un **audit complementaire v5+legacy** (Fix #3 de
`ROADMAP_VAGUE_P.md`). Cet audit a detecte **2 conflits critiques**
silencieux qui auraient casse la vue validation en production : (1)
trois endpoints `field_locks` declares cote frontend mais **absents
backend** (404 systematique), (2) action `Reinitialiser` destructive
**sans confirmation** capable d'effacer des heures de revue manuelle
par clic accidentel. Les deux conflits sont resolus dans ce meme
commit avec **backward compat ABSOLUE** : zero route existante
modifiee, zero comportement legacy casse, `tokens.css` non touche
(tier colors invariantes). VP-G clot la Vague P avec **83/83 tests
VP-C+VP-D+VP-G verts**.

## Changements par item

### VP-G : audit v5+legacy + cablage final UI library + 2 conflits resolus

- **VP-G-4-LIBRARY-UI-INTEGRATION** (`eed664b`) -
  `feat(VP-G-4-LIBRARY-UI-INTEGRATION)` : audit prealable
  documente puis cablage final sans regression.

  **Audit v5+legacy** :
  - `docs/internal/AUDIT_VP_G_LIB_VALIDATION_V5_LEGACY.md`
    (**150 LOC**) inventorie tous les overlays mutuels entre la
    vue legacy (3 colonnes / 9 colonnes, presets, filtres
    confidence/source) et la vue v5 (modale inspecteur waterfall
    VO-C, resolution `rule_id` -> nom via `get_quality_profile`,
    tri-etat accepted/rejected/deferred VP-D).
  - **8 zones overlay analysees** : boutons par ligne, coloration
    ligne, compteurs, payload `save_validation`, bulks "Tout
    rejeter" / "Reinitialiser", field locks UI, inspecteur modale.
  - **6 zones sans conflit** (additif pur, classes nettoyees avant
    ajout, wrappers badge supplementaires).
  - **2 conflits critiques detectes** et resolus dans le meme
    commit (cf ci-dessous).

  **Conflit #1 - endpoints `field_locks` absents cote backend** :
  - `lib-validation.js` exporte `setFieldLock` / `loadFieldLocks`
    qui appelaient `library/set_field_lock`,
    `library/clear_field_lock`, `library/list_field_locks` -
    **404 systematique** : aucune route exposee cote backend.
  - Cote backend, `FieldLocksRepository` existait deja (VP-C) avec
    l'API `set_lock` / `clear_lock` / `list_locks` / `is_locked` /
    `get_lock` / `migrate_locks` (cf
    `cinesort/infra/db/repositories/field_locks.py`), mais aucune
    methode publique de `LibraryFacade` ne routait les appels
    frontend vers ce repository.
  - **Fix** : 3 nouvelles methodes ajoutees sur `LibraryFacade`
    (`set_field_lock(film_id, field_name, locked_value, source)`,
    `clear_field_lock(film_id, field_name)`,
    `list_field_locks(film_id)`) qui delegueent vers 3 nouvelles
    fonctions `library_support.{set,clear,list}_field_lock(s)`.
  - Routes auto-exposees par introspection
    `rest_server._get_api_methods` (pass 2 dispatcher).
  - **Memo `feedback_cinesort_v76_ui` respect** : les endpoints
    vivent dans `library_support.py`, jamais dans un controller.

  **Conflit #2 - action "Reinitialiser" destructive sans
  confirmation** :
  - `libBtnResetDec` (ligne 836 pre-fix) effacait toutes les
    decisions accepted/rejected/deferred en un clic sans modal.
  - **Fix** : nouveau export `confirmResetDecisions` qui appelle
    `dangerConfirmModal` avec consequence explicite ("Toutes les
    decisions accepted/rejected/deferred seront effacees. Le
    brouillon de validation revient a vide.") + **countdown 3s si
    >50 decisions** posees (memo
    `feedback_cinesort_actions_dangereuses`).
  - **No-op silencieux si 0 decision** posee pour eviter un modal
    inutile sur etat vide.

  **Backward compat ABSOLUE** :
  - 20 methodes existantes de `LibraryFacade` preservees (test
    dedie verifie les signatures).
  - Routes existantes (`get_library_filtered`, `save_validation`,
    etc.) inchangees.
  - `web/shared/tokens.css` NON touche : tier colors hex
    INVARIANTES dans toute la Vague P (`--tier-platinum-solid`,
    `--tier-gold-solid`, `--tier-silver-solid`,
    `--tier-bronze-solid`, `--tier-reject-solid`,
    `--tier-unknown-solid`).

  **Surveillance** :
  - `confirmRebuildAll` (L911) deja conforme (countdown 3s si
    >50), reste exporte pour usage futur dans une vue "Edition de
    masse" hors perimetre VP-G (Vague Q+).

## Tests

- `tests/test_vp_g_field_locks_ui_endpoints.py` (**20 nouveaux
  tests**) :
  - Presence des 3 nouvelles routes sur `LibraryFacade`.
  - Delegation correcte vers `library_support.{set,clear,list}_field_lock(s)`.
  - Validation des entrees (film_id / field_name / locked_value /
    source).
  - **Backward compat des 20 methodes pre-VP-G** de
    `LibraryFacade` (signatures inchangees).
  - Resilience store HS (best-effort).
- **Total : 83/83 tests VP-C + VP-D + VP-G verts** (cumul des 3
  derniers sub-lots de la Vague P).

Acceptance criteria (5/5) :

- AC-1 OK : **audit v5+legacy documente** dans
  `AUDIT_VP_G_LIB_VALIDATION_V5_LEGACY.md` (150 LOC, 8 zones, 2
  conflits, strategie legacy-first explicite).
- AC-2 PENDING : scenario E2E green sur biblio reelle (853 films)
  -> a valider en run dedie post-tag.
- AC-3 OK : `node --check web/dashboard/views/library/lib-validation.js`
  PASS + F12 console clean.
- AC-4 OK : **tier colors hex INVARIANTES**
  (`web/shared/tokens.css` non touche dans toute la Vague P).
- AC-5 OK : **zero action destructive UI library sans
  `dangerConfirmModal`** (Reset + RebuildAll + bulk reject tous
  couverts).

## 🎁 Pour toi

VP-G ferme la Vague P avec un travail un peu particulier : avant
d'ecrire du code, on a fait un **audit complet** de la vue
validation (celle ou tu vois la liste de tes films a confirmer
apres un scan). Pourquoi ? Parce que cette vue est devenue
**hybride** : elle melange l'ancien affichage (3 ou 9 colonnes,
filtres, presets) et les nouveautes recentes (modale inspecteur
avec waterfall des scores, bouton "Reporter" en plus de
"Approuver/Rejeter", verrous de champs facon Jellyfin). Le risque,
quand on rajoute du code dans un fichier comme ca, c'est de
**casser silencieusement** une fonctionnalite legacy sans s'en
rendre compte.

L'audit a trouve **2 bugs critiques** qu'on a fixes dans le meme
commit :

1. **Les verrous de champs etaient cables a moitie**. Cote
   frontend (le bouton cadenas dans la modale inspecteur film),
   les appels existaient deja. Cote backend, la base de donnees
   etait prete (la table `field_locks` avait ete creee dans le
   batch precedent VP-C). **Mais entre les deux, il manquait
   3 endpoints** : si tu avais clique sur le cadenas pour
   verrouiller un champ, l'app aurait repondu **404 Not Found**
   sans rien sauvegarder. Maintenant, les 3 endpoints existent
   (`set_field_lock`, `clear_field_lock`, `list_field_locks`) et
   le verrouillage marche reellement de bout en bout.

2. **Le bouton "Reinitialiser" du brouillon de validation etait
   une bombe**. Dans la vue validation, en haut, il y avait un
   bouton "Reinitialiser" qui effacait d'un coup **toutes** tes
   decisions accepted / rejected / deferred sans confirmation.
   Clic accidentel = des heures de revue manuelle perdues. On a
   ajoute une **modale de confirmation** (la meme que pour les
   autres actions dangereuses), avec un **countdown de 3
   secondes** si tu as deja pose plus de 50 decisions (pour te
   forcer a relire ce que tu vas effacer). Si tu n'as encore rien
   decide, pas de modal (no-op silencieux : on n'allait pas te
   spammer pour effacer du vide).

A part ca, l'audit a verifie que **rien d'autre n'avait change** :
les 20 methodes du backend `LibraryFacade` ont toutes leurs
signatures preservees (un test dedie le verifie), les couleurs de
tiers (or, platine, bronze...) sont **strictement identiques**
dans toute la Vague P, et les routes existantes
(`get_library_filtered`, `save_validation`, etc.) n'ont pas bouge
d'un octet. On a aussi laisse en place le bouton
`confirmRebuildAll` pour une future vue "Edition de masse"
(prevue pour la Vague Q+), meme s'il n'est pas branche pour
l'instant - ca evite de devoir re-importer plus tard.

Le tout est valide par **83 tests verts** (cumul des 3 derniers
sub-lots VP-C + VP-D + VP-G). Reste a faire un run E2E sur ta
biblio reelle de 853 films pour cocher le dernier AC (AC-2), mais
le code est sain et la Vague P est officiellement complete cote
backend + UI.

## Notes

- Pas de bump VERSION (decision differee, coherent avec les
  batches Vague N/O/P-1/P-2/P-3/P-4/P-5/P-6).
- Tag local uniquement : `vague-p-batch7` (pas de push remote).
- Commits inclus : `eed664b`.
- **Backward compat ABSOLUE** : 20 methodes pre-VP-G de
  `LibraryFacade` preservees (signatures verifiees par
  `test_vp_g_field_locks_ui_endpoints.py`). Routes existantes
  inchangees. `tokens.css` non touche.
- **Audit prealable** : `docs/internal/AUDIT_VP_G_LIB_VALIDATION_V5_LEGACY.md`
  (150 LOC) documente la strategie legacy-first et detaille les 8
  zones overlay analysees.
- **Conflit #1 resolu** : 3 endpoints `field_locks` AJOUTES (aucun
  ALTER), routes auto-exposees par introspection
  `rest_server._get_api_methods`.
- **Conflit #2 resolu** : `dangerConfirmModal` systematique sur
  `libBtnResetDec` avec countdown 3s si >50 decisions et no-op
  silencieux si 0 decision.
- **AC-2 PENDING** : scenario E2E sur biblio reelle (853 films) a
  valider en run dedie post-tag (hors perimetre du commit).
- **Cloture Vague P** : VP-G est le dernier sub-lot. La Vague P
  apporte au total 7 batches (VP-A apply atomique, VP-B hierarchie
  qualite, VP-C field locks, VP-D tri-etat decisions, VP-E decoupe
  plan_support, VP-F profils qualite Recyclarr/TRaSH, VP-G
  integration finale UI library).
- Suite : Vague Q a definir (candidats : run E2E AC-2, vue
  "Edition de masse" branchee sur `confirmRebuildAll`, suppression
  des `_XxxMixin` legacy issue #85).
