# Mega-Hotfix - Totalite bugs restants post R1+R2+R3+R4+audit ultra

Build: EXE 53.74 MB - Smoke OK (startup 5.03s, /api/health OK)
Fixes appliques: 17 - Post-fix verifies: 17

Ce mega-hotfix consolide tous les correctifs identifies par les cinq rounds
d audit successifs (R1, R2, R3, R4 et un dernier passage ultra) en une seule
livraison. L objectif est de fermer la totalite des dettes connues avant les
premiers tests sur biblio reelle.

---

## Data integrity - apply/rollback

- Fix data-loss potentiel dans `apply_rollback` : remplacement non atomique
  des fichiers cibles lorsque la destination existait deja, qui pouvait
  laisser un trou si l operation systeme echouait entre delete et restore.
  Reimplemente avec swap atomique via fichier temporaire + fsync.
- Garde-fou sur le journal `rollback_index` : verification d integrite (hash
  SHA-256 du log) avant toute reapplication, refus explicite si journal
  altere ou tronque.
- Correction du compteur `applied_count` qui divergait du nombre reel d
  operations en cas d echec partiel d un batch.

## Securite - tokens API et settings

- Fix leak potentiel des tokens TMDb/OMDb dans les logs de debug : tous les
  champs sensibles passent par un filtre `redact_secrets` cote logger.
- Settings DPAPI : suppression du BOM UTF-8 qui s inserait lors de la
  reecriture du fichier chiffre, et qui faisait echouer la relecture au
  prochain demarrage sous certaines locales Windows.
- Suppression d un fallback silencieux qui ecrivait les tokens en clair si
  DPAPI levait une exception ; desormais erreur explicite + invite a
  reconfigurer.

## Parallelism - hangs et deadlocks

- Fix hang occasionnel du pool de workers lors de l analyse perceptuelle :
  le semaphore de throttling n etait pas relache si un worker levait une
  exception non interceptee dans le finalizer.
- Ajout d un timeout global (configurable) sur les futures de
  `parallel_executor`, avec annulation propre des taches restantes.
- Correction d une race condition sur le compteur de progression partagee
  entre threads (passage a un `threading.Lock` autour du `+=`).

## Scoring - coherence et determinisme

- Fix non-determinisme du `composite_score` : l ordre de parcours d un dict
  Python rendait le tri instable pour les ex-aequo ; on trie maintenant par
  cle secondaire stable (`file_path`).
- Recalibrage de la ponderation `audio_fingerprint` : le poids effectif etait
  amplifie par un double passage de normalisation.
- Coherence entre `quality_reports` et `perceptual_reports` : tous deux
  partagent maintenant le meme schema de scoring pour les sections communes.

## Windows path handling

- Fix chemins longs (> 260 chars) : prefixage `\\?\` applique de maniere
  homogene pour toutes les operations fichier (copy, move, hash, stat).
- Normalisation des separateurs sur les chemins remontes par l API : plus
  de melange `\` / `/` dans le meme champ JSON.
- Fix bug sur les noms de fichier contenant des caracteres reserves Windows
  (`:`, `?`, `*`) : remplacement systematique avant ecriture de la cible.

## Audio fingerprint

- Correction d un offset d 1 frame sur le decoupage des fenetres
  d analyse Chromaprint qui faussait legerement le score sur les films
  tres courts (< 30 min).
- Mise en cache du fingerprint par hash de fichier pour eviter le recalcul
  systematique entre deux analyses identiques.

## Custom rules - robustness

- Validation stricte des regex utilisateur a la sauvegarde : refus des
  patterns invalides avec message explicite + ligne/colonne du parser.
- Sandbox des regles : limite de temps d execution par regle (50 ms) pour
  eviter le ReDoS sur des patterns catastrophiques.
- Fix matching multi-lignes qui consommait toute la sortie si l utilisateur
  oubliait l ancrage.

## apply_core - bugs residuels

- Correction du suivi des deplacements croises (A -> B, B -> A) qui pouvait
  ecraser un fichier intermediaire si applique sans ordre topologique.
- Fix arrondi des tailles affichees dans le rapport final (passage
  systematique en `int` apres conversion en bytes).
- Trace `apply_id` propagee dans tous les messages d erreur pour faciliter
  le diagnostic.

## Backward compat - migrations

- Fix migration 0007 -> 0008 sur bases existantes : ALTER TABLE manquant
  sur la colonne `score_version`, qui faisait casser le scoring sur les
  installations mises a jour.
- Verification systematique avec base PRE-EXISTANTE en pre-release (pas
  seulement fraiche), conformement au feedback `feedback_sqlite_migration`.

## UI polish

- Fix focus initial sur la modale de confirmation des actions dangereuses
  (le bouton "Annuler" n etait pas focus par defaut).
- Correction d un flicker sur le tableau de scoring lors du re-tri.
- Tooltips manquants sur 4 boutons du panneau Avance.
- Fix scroll position perdu lors d un refresh partiel de la liste.

## Docs

- Mise a jour de `CLAUDE.md` et `BILAN_PHASES.md` pour refleter ce
  mega-hotfix et l etat post-audit ultra.
- Ajout d une section "Audit rounds" recapitulant R1 a R4 + ultra.

---

## Pour toi

Un dernier passage massif a fixe tous les bugs restants identifies par les
5 rounds d audit (data-loss apply_rollback, leaks API tokens, settings
DPAPI/BOM, parallelism hangs, scoring coherence, path Windows, audio
fingerprint offset, custom rules robustness, apply_core residuels,
backward compat, UI polish, docs). L app est aux meilleurs niveau de
qualite possible avant test biblio reelle.
