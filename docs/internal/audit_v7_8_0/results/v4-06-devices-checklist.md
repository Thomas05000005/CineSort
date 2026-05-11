# V4-06 — Checklist test devices physiques

## Préparation

L'instance Playwright a généré 60 screenshots dans `audit/results/v4-06-screenshots/<viewport>/`.
Avant de tester sur appareils physiques, **passe rapidement en revue les screenshots**
pour repérer les évidents :

- [ ] Aucune zone clippée / texte coupé
- [ ] Sidebar visible/lisible sur mobile
- [ ] Pas de débordement horizontal (cf `audit/results/v4-06-overflow.md` s'il existe)

## Tests humains à faire

Pour ces tests, l'humain doit utiliser des appareils réels (Playwright simule mais
ne reproduit pas le DPI Windows, le scaling natif, ni les browsers mobiles réels).

### A. Windows 10 (laptop ou desktop)

- [ ] Lance l'app, scan ~50 films de test
- [ ] Vérifie : fenêtre s'ouvre sans clip, fonts lisibles
- [ ] Teste les 6 vues principales (Accueil, Bibliothèque, Validation, Apply, Qualité, Paramètres)
- [ ] Note tout glitch visuel ou lag dans `audit/results/v4-06-tests-humains.md`

### B. Windows 11 (4K avec scaling 150-200%)

- [ ] Lance l'app sur écran 4K
- [ ] Vérifie : DPI awareness (pas de blur), fonts proportionnelles
- [ ] Teste un scan + apply
- [ ] Vérifie que le splash s'affiche correctement

### C. Petit écran (1366×768, courant en entrée de gamme)

- [ ] Lance l'app
- [ ] Vérifie que toutes les actions principales sont accessibles sans scroll horizontal
- [ ] Vérifie le drawer mobile inspector (V3-06) sur la vue Validation

### D. Mobile (téléphone Android ou iOS via dashboard distant)

Prérequis : dashboard activé, token configuré, IP du PC connue.

- [ ] Sur ton téléphone, ouvre `http://<ip-pc>:8642/dashboard/`
- [ ] Login avec le token
- [ ] Teste navigation sidebar bottom-tab
- [ ] Sur la vue Validation, **clique le bouton "Inspecter"** (V3-06) → drawer s'ouvre depuis la droite
- [ ] Tooltips ⓘ glossaire (V3-03) → tap fonctionne sur mobile
- [ ] Boutons assez gros pour tap (≥ 44px) → vérifier sur les actions critiques

### E. Tablette (iPad ou Android tablet)

- [ ] Mêmes tests que mobile
- [ ] Vérifie que le layout intermédiaire (768-1023px) ne clippe pas

## Reporter les bugs

Pour chaque bug trouvé :
- Capture l'écran (téléphone) ou Win+Shift+S (desktop)
- Note dans `audit/results/v4-06-tests-humains.md` :
  - Device + version OS
  - Vue concernée
  - Description courte
  - Capture
  - Niveau (bloquant / important / cosmétique)

Les bloquants doivent être fixés AVANT le public release. Les cosmétiques peuvent être
listés dans la roadmap V5+.
