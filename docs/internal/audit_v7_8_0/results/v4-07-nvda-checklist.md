# V4-07 — Guide test NVDA + clavier seul

## Pourquoi ?

Tester avec un vrai lecteur d'écran est le seul moyen de valider que l'app est
utilisable par les personnes aveugles ou malvoyantes. C'est aussi un excellent
révélateur de problèmes UX généraux (focus, ordre logique, labels manquants).

## Préparation

### Installer NVDA (gratuit, open-source)

1. Télécharge depuis https://www.nvaccess.org/download/
2. Installe (typique : Suivant × 4)
3. Au démarrage, choisis "Installer NVDA sur cet ordinateur"

### Raccourcis NVDA essentiels

| Raccourci | Action |
|---|---|
| `Ctrl` | Stopper la lecture en cours |
| `Insert + Espace` | Activer/désactiver le mode focus (laisser NVDA gérer le clavier) |
| `Insert + ↓` | Lire à partir d'ici jusqu'à la fin |
| `Tab` / `Shift+Tab` | Naviguer entre éléments interactifs |
| `H` | Élément suivant titre (en mode browse) |
| `B` | Bouton suivant |
| `F` | Champ formulaire suivant |
| `K` | Lien suivant |
| `Insert + N` | Menu NVDA (Quitter via ce menu) |

## Test à faire

Lance CineSort, lance NVDA, **mets un masque sur ton écran** (ou ferme les yeux).
Si tu peux tout faire au son + clavier seul, l'app est accessible.

### Workflow critique 1 : Premier scan

- [ ] Au démarrage, NVDA annonce "CineSort, dashboard distant" (ou équivalent)
- [ ] Tab te ramène sur la sidebar → annoncée comme "Navigation principale"
- [ ] Flèches verticales pour naviguer dans la sidebar (ou Tab pour entrée par entrée)
- [ ] Active "Paramètres" → annoncé "Paramètres, page principale"
- [ ] Tab vers le champ "Dossiers racine" → annoncé "Dossiers racine, champ texte"
- [ ] Saisis un dossier → NVDA confirme la saisie
- [ ] Tab vers "Enregistrer" → annoncé "Enregistrer, bouton"
- [ ] Active → confirmation entendue

### Workflow critique 2 : Validation

- [ ] Aller sur la vue Validation
- [ ] Tab dans la liste de films → chaque ligne annoncée avec titre + score + actions
- [ ] Boutons "Approuver" / "Rejeter" → annoncés clairement
- [ ] Active "Approuver" → confirmation entendue

### Vérifications globales

- [ ] **Skip link** "Aller au contenu principal" présent (Tab depuis le début)
- [ ] Tous les **boutons** ont un label parlant (pas juste "btn1")
- [ ] Tous les **icônes interactifs** ont un `aria-label` (NVDA dit "Bouton recherche", pas "Bouton")
- [ ] Les **icônes décoratives** sont silencieuses (NVDA ne dit pas leur HTML)
- [ ] **Modales** : focus piégé dedans, Escape ferme
- [ ] **Drawer mobile** (V3-06) : annoncé comme "dialog", focus à l'intérieur
- [ ] **Tooltips ⓘ** (V3-03) : focus dessus → texte annoncé
- [ ] **Compteurs sidebar** (V3-04) : "Validation, 3 films en attente" (ou équivalent)
- [ ] **Tableaux** : NVDA annonce les en-têtes de colonne quand tu navigues les cellules

## Reporter les findings

Crée `audit/results/v4-07-nvda-findings.md` avec ce que NVDA n'annonce pas
correctement, ou ce qui est inutilisable au clavier seul.

Format suggéré :

| Vue | Élément | Problème | Sévérité | Fix proposé |
|---|---|---|---|---|
| Validation | Bouton "Approuver" | NVDA dit juste "Bouton" | High | Ajouter aria-label="Approuver ce film" |
| Sidebar | Badges (V3-04) | NVDA ne lit pas les compteurs | Med | Ajouter aria-live="polite" |

## Suivi

- **Critical/High** → fix avant public release (V4 patch)
- **Medium** → roadmap V5
- **Low/cosmetic** → nice-to-have

## Ressources

- [WCAG 2.2 AA quick reference](https://www.w3.org/WAI/WCAG22/quickref/)
- [WebAIM NVDA shortcuts](https://webaim.org/resources/shortcuts/nvda)
- [Inclusive Components](https://inclusive-components.design/)
