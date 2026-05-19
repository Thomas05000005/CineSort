# Refonte UI — 2026-05-17

Spec écran par écran validée avec Thomas après test de l'EXE v1.2.0-beta.
Pas de code avant que toutes les specs critiques soient validées.

## Contexte

- L'app a évolué depuis la phase de design initiale (`docs/internal/design/01-14*.md`)
- La direction visuelle de `12-local-source-of-truth.md` reste inspirante mais n'est pas la cible définitive (l'app a maintenant : OMDb, perceptuel riche, dashboard remote, QR, intégrations Jellyfin/Plex/Radarr, etc.)
- Trois retours utilisateur critiques motivent cette refonte :
  1. **Doublons** : liste plate "Doublon détecté" sans données pour décider
  2. **Analyse perceptuelle** : modal affiche "non calculée" alors que le backend a entropy/SSIM/chromaprint/grain/HDR
  3. **OMDb** : implémenté côté Python (DPAPI + endpoint test_omdb_connection + cross_check_rows_with_omdb) mais aucune UI

Cf [[feedback-cinesort-ui-pacotille]] dans la mémoire perso de Thomas.

## Méthodologie

Pour chaque écran :
1. **Inventaire de l'existant** : code actuel + screenshots + endpoint backend
2. **Données backend disponibles** : ce qu'on peut afficher sans nouveau code
3. **Besoin utilisateur** : à quoi ça sert, qui clique, quand, pourquoi
4. **Spec cible** : layout (mockup ASCII), données, actions, interactions
5. **Écart backend** : ce qu'il faut ajouter côté Python
6. **Estimation** : effort en jours

## Écrans spec'és (validés)

- ✅ [01-doublons.md](./screens/01-doublons.md) — Vue Doublons + Inspecteur droit + Comparateur (6.9 j)
- ✅ [02-modal-perceptuelle.md](./screens/02-modal-perceptuelle.md) — Modal Analyse Perceptuelle, dual-mode inspecteur élargi/overlay (3.6 j, 0 backend)
- ✅ [03-settings-omdb.md](./screens/03-settings-omdb.md) — Paramètres > Intégrations > OMDb (0.2 j marginal — **Option B retenue**)
- ✅ [04-shell-3-zones.md](./screens/04-shell-3-zones.md) — Shell 3 zones : sidebar + header + inspecteur (5 j, fondations transverses)
- ✅ [05-accueil.md](./screens/05-accueil.md) — Accueil refondu (6 sections au lieu de 18) (5.2 j)
- ✅ [06-modal-film.md](./screens/06-modal-film.md) — Détail Film tri-mode (inspecteur/standalone/modal) (6.1 j)
- ✅ [07-bibliotheque.md](./screens/07-bibliotheque.md) — Vue Bibliothèque grille posters + scroll infini + bulk actions (7 j)
- ✅ [08-traitement.md](./screens/08-traitement.md) — Vue Traitement workflow 5 étapes + nav libre + apply confirmation (7.3 j)
- ✅ [09-historique.md](./screens/09-historique.md) — Vue Historique timeline + onglets inspecteur + rétention 90j (3.7 j)
- ✅ [10-qualite.md](./screens/10-qualite.md) — Vue Qualité audit transverse 6 sections + filtres globaux (5.2 j)
- ✅ [11-parametres.md](./screens/11-parametres.md) — Paramètres 10 catégories + mode expert + profils qualité (5.9 j)
- ✅ [12-aide.md](./screens/12-aide.md) — Vue Aide doc + raccourcis + diagnostic + nouveau guide utilisateur à rédiger (5.2 j)

## Principes transverses (ajoutés au fil de la spec)

- **Actions dangereuses** : toute action destructive (marquage suppression, reset, etc.) déclenche une modale de confirmation supplémentaire. Format standard : titre clair + liste éléments concernés + conséquence + bouton danger rouge + délai 3s si bulk > 50. Cf [[feedback-cinesort-actions-dangereuses]].

## Décisions stratégiques validées

- **Frontend cible** = `web/dashboard/` (ESM moderne, design tokens v5). Pas de double cible.
- **Migration legacy → ESM** : action dédiée (~3-5 j) qui fera pywebview charger `web/dashboard/index.html` au lieu de `web/index.html`. Suppression de `web/views/` + `web/components/` + `web/index.html` + `web/styles.css` + `web/themes.css` (~5 645 lignes de CSS + 26 composants legacy).
- **OMDb sera dispo dans l'app native automatiquement** après migration (la section frontend existe déjà dans `web/dashboard/views/settings.js`).
- **Pas de port OMDb dans le legacy** (évite 0.5 j de travail jeté).
- **Specs des écrans 4+ rédigées uniquement pour le dashboard ESM.**

## Écrans à spec (par ordre de priorité)

- ⏳ 04-accueil.md — Refonte page d'accueil (15+ widgets actuels → hub editorial)
- ⏳ 05-modal-film.md — Modal Détail Film (poster + alertes humanisées + perceptuel inline)
- ⏳ 06-settings-overview.md — Vue d'ensemble Paramètres
- ⏳ 07-bibliotheque.md — Vue Bibliothèque (grille de posters)
- ⏳ 08-traitement.md — Vue Traitement (scan en cours)
- ⏳ 09-historique.md — Vue Historique / Runs
- ⏳ 10-qij.md — Vue QIJ (à clarifier : c'est quoi exactement)
- ⏳ 11-aide.md — Vue Aide
- ⏳ Modals : annulation, undo, command palette, notifications

## Patterns transverses (à factoriser dans les specs)

- **Structure 3 zones** (rail + centre + panneau droit persistant) selon `12-local-source-of-truth.md`
- **Theming unifié** : `web/shared/tokens.css` (v5) seul, suppression `themes.css` legacy (975L)
- **Codes alertes humanisés** : `subtitle_missing_fr` → "Sous-titres FR manquants" (mapping à créer)
- **Endpoints REST** : tous sous `/api/<facade>/<method>` (legacy `/api/<method>` interdit après #233)
- **Bucket review** : `<root>/_review/_*` avec préfixe `_` pour tri alphabétique (existant)
- **Job runner** pour analyses longues : pas synchrone bloquant l'UI

## Implémentation (après spec complète)

Suivre `docs/internal/design/14-design-to-code-implementation-plan.md` adapté :
- Lot B : Tokens visuels unifiés
- Lot C : Primitives globales
- Lot D : Shell global desktop-first
- Lot E : Tables premium
- Lot F : Formulaires et filtres
- Lot G : Écrans clés (un par sous-lot, dans l'ordre de cette spec)
- Lot H : États secondaires et feedback
- Lot I : QA visuelle et polish
