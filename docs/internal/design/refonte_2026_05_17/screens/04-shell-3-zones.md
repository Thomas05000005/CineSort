# Spec — Shell 3 zones (sidebar + header + inspecteur droit)

Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 4 / N** — fondation de tous les écrans suivants.
Cible : `web/dashboard/` (ESM uniquement, après migration B).

## Pourquoi cette spec

Tous les écrans suivants (Accueil, Modal Film, Bibliothèque, Traitement, etc.) s'inscriront dans cette structure. La spec 12-local-source-of-truth.md de la phase design précédente prônait déjà une structure 3 zones — on l'adapte aux besoins actuels (renommage QIJ, vue Traitement conditionnelle, etc.).

## 1. Layout général

```
┌────┬─────────────────────────────────────────────────────┬─────────────┐
│ 👤 │  CineSort                              [🔍 Cmd+K]    │ ▼ Inspecteur│
│ CS │                                        [🔔 3] [🌗]   │             │
├────┼─────────────────────────────────────────────────────┼─────────────┤
│    │                                                     │             │
│ 🏠 │                                                     │  Contexte   │
│ ▶  │                                                     │  de la vue  │
│ 📚 │                                                     │  active     │
│ ⚡ │           ZONE CENTRALE                              │             │
│ 📊 │           (la vue active)                            │  Détails    │
│    │                                                     │  ligne      │
│ ⚙  │                                                     │  sélectionnée│
│ ?  │                                                     │             │
│    │                                                     │  Suite      │
│    │                                                     │  logique    │
│    │                                                     │             │
└────┴─────────────────────────────────────────────────────┴─────────────┘
  64px ou 220px        flexible (min 800px)                360px (480 max)
```

## 2. Rail gauche (sidebar) — Pattern Linear

### Structure

```
┌────────────────┐
│ 👤 CS  ⌃ Pin   │  ← Brand + bouton Pin (déplié / réduit)
├────────────────┤
│                │
│ 🏠 Accueil     │
│                │
│ ▶  Traitement  │  ← Conditionnel : visible UNIQUEMENT si run actif
│    ● 901 films │
│                │
│ 📚 Bibliothèque│
│                │
│ ⚡ Qualité      │  ← Ex-QIJ/quality (renommé)
│                │
│ 📊 Historique  │  ← Ex-QIJ/journal (renommé)
│                │
├────────────────┤  ← Séparateur
│                │
│ ⚙  Paramètres  │  ← Settings + Intégrations (ex-QIJ/integrations mergé ici)
│                │
│ ?  Aide        │
│                │
└────────────────┘
```

### Comportement (décision Thomas : Réductible avec pin)

| État | Largeur | Comportement |
|---|---|---|
| Pinned déployé | 220px | Toujours visible, icônes + labels |
| Pinned réduit | 64px | Toujours visible, icônes seules, tooltip au hover |
| Non pinned (auto) | 64px | Au hover sur le rail, s'ouvre en overlay 220px sans pousser le centre. Replie quand le curseur quitte. |
| Préférence | Settings | Mémorisée via `localStorage` + sync settings `sidebar_pinned_open: bool` |

### Entrées du sidebar (mapping vers vues)

| Icône | Label | Visible | URL hash | Vue cible |
|---|---|---|---|---|
| 🏠 | Accueil | toujours | `#accueil` | Vue de synthèse (à spec écran 5) |
| ▶ | Traitement | si run actif | `#traitement` | Workflow scan + plan + apply en cours |
| 📚 | Bibliothèque | toujours | `#bibliotheque` | Vue collection complète (films + doublons + stats) |
| ⚡ | Qualité | toujours | `#qualite` | Audit qualité de la bibliothèque |
| 📊 | Historique | toujours | `#historique` | Journal des runs passés |
| ⚙ | Paramètres | toujours | `#parametres` | Settings + Intégrations (TMDb/Jellyfin/Plex/Radarr/OMDb) |
| ? | Aide | toujours | `#aide` | Documentation utilisateur |

### Décision QIJ (validée Thomas)

QIJ est **splittée** en 3 destinations :
- **Quality** → entrée sidebar dédiée `⚡ Qualité`
- **Journal** → entrée sidebar dédiée `📊 Historique`
- **Integrations** → fusionnée dans `⚙ Paramètres > Intégrations` (où elle se trouve déjà partiellement)

**Migration** : le mapping URL `#qij` → 301 vers `#qualite` (compat URL pour les bookmarks).

### Badges et indicateurs

- **Compteurs** : `● 901 films` à droite de l'entrée (couleur accent froid)
- **Pastilles santé** : petite dot en bas du picto (vert OK / orange warn / rouge alert) selon `get_global_stats().health_per_section[section_id]`
- **État actif** : surface plus claire + barre verticale gauche en accent froid
- **Hover** : surface intermediate

## 3. Header (barre supérieure persistante)

```
┌────────────────────────────────────────────────────────────────┐
│  CineSort                          [🔍 Rechercher... Ctrl+K]   │
│                                    [🔔 3]  [🌗 Thème]  [👤]    │
└────────────────────────────────────────────────────────────────┘
```

### Éléments

| Élément | Position | Comportement |
|---|---|---|
| Logo + titre | Gauche | Cliquable → retour Accueil |
| Recherche globale | Centre | Placeholder + raccourci Ctrl+K. Au clic ou Ctrl+K → ouvre command palette (films / runs / paramètres) |
| Notifications | Droite | Badge avec compteur unread. Au clic → dropdown notifications center |
| Toggle thème | Droite | Switch clair/sombre. App sombre par défaut (recommandé v5) |
| Avatar | Droite | Profil utilisateur + déconnecter (utile en mode REST distant via QR) |

### Command palette (Ctrl+K)

```
┌────────────────────────────────────────────────────────────────┐
│  🔍 Rechercher...                                              │
│  ────────────────────────────────────────────────────────────  │
│  ▾ Films (1 247 résultats)                                     │
│      Fast & Furious 4 (2009)              ⌘+1                  │
│      Captain America Civil War (2016)     ⌘+2                  │
│      ...                                                       │
│  ▾ Actions                                                     │
│      Lancer un scan                       ⌃+S                  │
│      Aller à Paramètres                   ⌃+,                  │
│  ▾ Aide                                                        │
│      Documentation                                             │
└────────────────────────────────────────────────────────────────┘
```

Source : `library/get_library_filtered` pour films + liste statique pour actions.

## 4. Panneau droit (inspecteur persistant)

```
┌──────────────────────────┐
│  ▼ Inspecteur            │  ← Header replieable
├──────────────────────────┤
│                          │
│  Contexte de la vue      │
│  (statut run, filtres    │
│  appliqués, etc.)        │
│                          │
│  ────────────────        │
│                          │
│  Détails ligne           │
│  sélectionnée            │
│  (si applicable)         │
│                          │
│  ────────────────        │
│                          │
│  Suite logique           │
│  • Vers Doublons         │
│  • Vers Apply            │
│                          │
└──────────────────────────┘
```

### Comportement (décision Thomas : adaptatif)

| Vue | Inspecteur par défaut | Pourquoi |
|---|---|---|
| Accueil | replié | Vue de synthèse, pas besoin d'inspecteur |
| Traitement | visible | Workflow expert, inspecteur montre étape suivante |
| Bibliothèque | visible | Vue experte, inspecteur montre détails film sélectionné |
| Qualité | visible | Audit, inspecteur montre détails ligne sélectionnée |
| Historique | visible | Journal, inspecteur montre détails run sélectionné |
| Paramètres | replié | Config, pas de notion de "ligne sélectionnée" |
| Aide | replié | Doc, plein écran centre |

### Largeur et resize

- **Largeur défaut** : 360px
- **Min** : 280px (pour rester lisible)
- **Max** : 480px (drag handle sur le bord gauche)
- **État replié** : 0px (juste un bouton ▶ en bord droit pour ouvrir)

### Slot mechanism

Chaque vue déclare le contenu de son inspecteur via un slot. Pattern recommandé :

```javascript
// web/dashboard/views/library.js
export function getRightPanelContent(viewState) {
  return {
    sections: [
      { title: "Contexte", html: renderContextHtml(viewState) },
      { title: "Détails du film", html: renderFilmDetailsHtml(viewState.selectedFilm) },
      { title: "Suite logique", html: renderNextStepsHtml(viewState) },
    ],
  };
}
```

Le composant `<RightPanel>` consomme cette structure et affiche les sections.

## 5. Comportements transverses

### Raccourcis clavier

| Raccourci | Effet |
|---|---|
| Ctrl+K | Ouvrir command palette |
| Ctrl+B | Toggle sidebar pinned/non-pinned |
| Ctrl+I | Toggle inspecteur droit |
| Esc | Fermer modal ou command palette |
| Ctrl+, | Aller à Paramètres |
| Ctrl+S | Lancer un nouveau scan (depuis n'importe quelle vue) |
| Ctrl+Z | Undo (depuis vue Traitement après Apply) |
| ? | Ouvrir l'aide contextuelle |

### Responsive desktop

| Largeur fenêtre | Comportement |
|---|---|
| ≥ 1600px | Tout dépliable (sidebar 220 + centre flexible + inspecteur 480 max) |
| 1280-1600px | Sidebar réduit à 64 si inspecteur visible, centre prend l'espace |
| 1024-1280px | Inspecteur masqué par défaut, sidebar réduit |
| < 1024px | Inspecteur fermé, sidebar pliable. Min app = 800px (desktop-first) |

### États transverses

| État | Affichage |
|---|---|
| Chargement initial app | Splash screen avec logo + barre de progression (~3s) |
| Backend déconnecté | Bannière en haut "Connexion perdue. Reconnexion auto..." |
| Run actif en background | Indicateur dans sidebar entry Traitement (`● 23% in progress`) |
| Notification critique | Badge rouge sur 🔔 + toast popup en bas à droite (autoclose 5s) |

## 6. Source backend par zone

| Zone | Endpoint |
|---|---|
| Compteurs sidebar | `get_sidebar_counters()` (existant) |
| Indicateurs santé | `get_global_stats().health_per_section` (À CRÉER si manquant — 0.2 j) |
| Notifications | `get_notifications_unread_count()` + `list_notifications()` (existant) |
| Films pour palette | `library/get_library_filtered({limit: 50, query: $search})` |
| Inspecteur contenu | Chaque vue : `getRightPanelContent(viewState)` côté frontend |

## 7. Effort estimé

| Tâche | Effort |
|---|---|
| HTML/CSS shell 3 zones (`web/dashboard/index.html` + `styles.css`) | 1 j |
| Composant `<Sidebar>` ESM (rail + dépliable + pin + badges) | 1 j |
| Composant `<Header>` (titre + recherche + notifs + thème) | 0.5 j |
| Composant `<CommandPalette>` Ctrl+K | 0.5 j |
| Composant `<RightPanel>` slot-based avec adaptation par vue | 0.8 j |
| Raccourcis clavier transverses | 0.3 j |
| Backend `get_global_stats().health_per_section` si manquant | 0.2 j |
| Splash screen + states (déconnecté, run actif) | 0.3 j |
| Tests E2E navigation et raccourcis | 0.4 j |
| **Total shell + composants base** | **~5 jours** |

(N'inclut PAS la migration des vues individuelles — comptée dans chaque spec d'écran.)

## 8. Améliorations rétro APPLIQUÉES aux specs précédentes (2026-05-17)

Suite à la spec du shell 3 zones, les specs 01 et 02 ont été mises à jour pour intégrer l'inspecteur droit :

### ✅ Spec 01 Doublons (mise à jour le 2026-05-17)
- **Nouvelle section 2** : Inspecteur droit avec poster TMDb grand format + alertes humanisées + candidats TMDb + synopsis
- Distinction clic carte (= sélection + inspecteur) vs clic "Comparer en détail" (= modal)
- Navigation clavier ↑↓ pour parcourir les groupes sans modal
- Nouveau fichier `web/dashboard/core/alert-labels.js` pour humaniser les codes
- **Effort total Doublons** : passé de 5.5 j → **6.9 j** (+1.3 j inspecteur)

### ✅ Spec 02 Modal Perceptuelle (mise à jour le 2026-05-17)
- **Nouvelle section 0** : Dual-mode adaptatif
  - Mode A (inspecteur élargi 360→600px) sur vues expertes Bibliothèque/Doublons/Qualité/Historique
  - Mode B (overlay modal classique) sur Accueil/Paramètres/Aide
- Layout interne identique dans les 2 modes, seul le conteneur change
- **Effort total Perceptuelle** : passé de 3 j → **3.6 j** (+0.5 j dual-mode + 0.2 j resize handler)

### ✅ Spec 03 OMDb
- Pas d'amélioration. Déjà OK pour la structure 3 zones (paramètres = centre plein écran).

## 9. Hors scope shell v1

- ❌ Drag-and-drop pour réordonner les entrées sidebar
- ❌ Personnalisation des badges/couleurs par utilisateur
- ❌ Mode mobile/tablette (desktop-first uniquement)
- ❌ Multi-fenêtres
- ❌ Sidebar à droite (LTR-only pour v1)
- ❌ Mode focus ("hide chrome" pour cinéma)
