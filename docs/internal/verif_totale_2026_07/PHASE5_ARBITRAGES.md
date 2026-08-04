# PHASE 5 — Arbitrages produit — 2026-07-09 (tranchés 2026-07-10)

> La purge de code mort (Phase 5) a supprimé le franchement mort. Restent des
> zones qui demandent une **décision produit** (câbler / assumer / élaguer) plutôt
> qu'une suppression mécanique — la règle de backward-compat interdit de retirer
> des clés settings ou API sans arbitrage. Ce document les liste pour trancher.

## ✅ DÉCISIONS TRANCHÉES (Thomas, 2026-07-10)
1. **i18n → FR-only (partiel).** Élagage des 3 familles 100 % orphelines
   (legacy+plex+radarr = 120 clés) + retrait du sélecteur de langue. Le reste
   (~400 clés) est verrouillé par 6 fichiers de tests de structure → décision
   séparée. ✅ FAIT (commit i18n). Détail §1.
2. **Auto-approbation → IMPLÉMENTÉE** (seed READ-TIME de la Validation, jamais
   persisté, apply intact). ✅ FAIT (commit auto-approve). Détail §2.
3. **Méthodes façade orphelines → GARDER** (backward-compat), câblage à la demande.
   Rien supprimé. Détail §3.
4. **R8-079 (pack TV NxNN « Show.101 ») → ABANDONNÉ.** Après 2 passes de revue
   adversaire (4 bugs de mutilation de titre / perte de données : « Fahrenheit 451 »
   éditions collisionnées en S04E51, « MCU 101 Iron Man » collection transformée en
   série, film isolé mutilé dans un dossier TV, épisode nu droppé si son code = token
   technique), la détection de nombres à 3 chiffres NUS s'est révélée **non
   fiabilisable** dans la zone titre seed-critique (règle inviolable « ne jamais
   mutiler un titre »). Code retiré. **Limite documentée** : les packs TV doivent
   être nommés en `S01E01` ou `1x01` (formats non ambigus, déjà détectés). Détail §4.

Statut d'implémentation : commits du cycle 2026-07-10 (branche arbitrages/produit).

## 1. i18n — le dashboard est majoritairement FR-only

**Constat (matrice M6, confirmé après purge)** : les 9 vues vivantes (accueil,
bibliothèque, traitement, qualité, doublons, historique, paramètres, aide,
film-detail) font **zéro appel `t()`** — leurs libellés sont en français en dur.
Après la purge des 6 vues mortes (qui portaient l'essentiel des `t()`), il reste
**~519 clés locales orphelines** (fr.json/en.json, ex. `settings.*` 185, `qij.*` 144,
`help.* / glossary.*`, `common.*`, `errors.*`). La famille `qij.*` (vue supprimée en
R8) a d'abord été retirée puis **RESTAURÉE** : un cluster de tests i18n délibérés
(V6-02, `test_i18n_extraction_frontend`) la verrouille — la retirer = churn de tests
pour un gain marginal. Le retrait en masse est donc bien une **décision produit**
(pas une purge mécanique), à trancher globalement.

**Décision à prendre** :
- (a) **Câbler l'i18n** dans les vues vivantes (gros chantier, ~plusieurs jours ;
  l'anglais deviendrait réellement disponible), OU
- (b) **Assumer FR-only** et élaguer les familles orphelines (réduit le poids,
  supprime la dette, mais ferme la porte à l'EN sans re-travail).

Ni l'une ni l'autre n'est faite (décision produit). Le contrat CI
`test_contract_i18n` garantit seulement que toute clé RÉFÉRENCÉE existe dans les 2
locales (pas de régression), pas que tout soit traduit.

## 2. Settings « fantômes » / write-only (matrice M3)

Clés persistées mais sans effet backend prouvé (à câbler ou retirer — retrait =
décision produit car un settings.json existant peut les porter) :
- **`auto_approve_enabled` / `auto_approve_threshold`** : affichés dans l'UI
  (« Approbation automatique ») mais **aucun code ne les lit** → la feature n'existe
  pas. Décider : implémenter l'auto-approbation OU retirer les champs UI.
- **`auto_quarantine_corrupted`** : défaut + save + reset, mais 0 consommateur et
  0 champ UI (feature M-2 jamais câblée).
- **`onboarding_completed`, `notifications_enabled`** : write-only (le vrai gate
  desktop lit `desktop_notifications_enabled`).
- **`cleanup_orphans`, `retention_days`, `cleanup_empty_folders`,
  `excluded_patterns`, `{sep}` presets naming** : les 5 arbitrages déjà signalés
  en R8 (R8_CORRECTIONS.md:948-960) — cleanup destructif à gouverner, prune jamais
  planifié, `{sep}` = risque seeding torrent (opt-in réversible obligatoire).
- **6 flags `_has_*secret*`** générés par `_mask_secrets` mais jamais affichés :
  l'UI ne peut pas indiquer si un secret est déjà enregistré (sauf TMDb).
- **17 clés `perceptual_*`** : lues par le backend mais **aucun champ UI** →
  réglables uniquement en éditant settings.json à la main.

## 3. Méthodes de façade orphelines (matrice M2 + purge)

**52 → maintenant ~60 méthodes de façade sans consommateur web** (les 8 nouvelles
révélées par la purge des vues mortes sont dans `KNOWN_ORPHAN_METHODS` :
`get_jellyfin_sync_report`, `get_plex_sync_report`, `request_radarr_upgrade`,
`get_library_podiums`, `get_library_timeline`, `export_run_report`,
`export_run_nfo`, `get_log_paths`). Familles concernées : field locks complet,
undo granulaire, quarantaine (purge bucket), watchlist, éditeur de profils qualité,
rapports de sync intégrations, exports de run.

**Décision** : pour chacune, câbler dans une vue vivante (parametres.js pour les
intégrations, bibliothèque pour field locks…) OU l'élaguer du backend. En l'état,
c'est de la surface API maintenue sans UI (~30 % des 172 méthodes).

## 4. Autres différés documentés
- **R8-079** (pack TV `Show.101` planifié en films) : convention NxNN à activer en
  opt-in ? Décision produit.
- **Faux-positif dédup « Word AAAA (AAAA) »** : accepté (report-only, rarissime, cf
  SYNTHESE_LOT_D_FIX.md).
- **#5 résidu résolution `.1080`/`.720`** sans « p » (LOW, zone seed).
- **Sécurité** : `SECURITE_POUR_OPUS.md` (traitée par Opus).
- **Release/tag R8** : aucun tag sur origin/main 650d162 (décision Thomas).
