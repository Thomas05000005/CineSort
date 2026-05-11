# 12 Local Source Of Truth

Contexte:
- Figma est indisponible ou insuffisamment exploitable dans cette session
- ce document devient la source de verite locale canonique pour la phase UI/design premium
- il remplace le role de reference centrale que jouerait un fichier Figma pendant cette phase
- aucun changement produit dans ce document

Usage:
- pour implementer la refonte, partir de ce document en premier
- utiliser les documents annexes seulement pour le niveau de detail supplementaire
- ne pas introduire de nouvelles directions visuelles sans mettre a jour ce document

Documents annexes de detail:
- [09-figma-brief.md](./09-figma-brief.md)
- [10-design-system-foundation.md](./10-design-system-foundation.md)
- [11-key-screen-mockups.md](./11-key-screen-mockups.md)

## 1. Positionnement retenu

Produit:
- outil desktop-first de tri, analyse, verification et preparation d'execution sur bibliotheque films

Public:
- operateur avance ou semi-expert
- usage long
- recherche de controle, de clarte et de fiabilite

Direction finale retenue:
- base visuelle: sobre premium
- accents limites: studio / media haut de gamme
- structure d'interface: workspace a trois zones permanentes
- composants: tonal precision

Variantes validees:
- palette: `A - Neutral premium`
- composants: `B - Tonal precision avec accents editoriaux`
- structure: `B - Trois zones avec inspecteur affirme`
- densite: `A - Densite controlee`

Ce que l'app doit evoquer:
- outil de pilotage premium
- produit mature
- confiance operateur

Ce qu'elle ne doit pas evoquer:
- dashboard SaaS generique
- app cinema flashy
- interface gamer
- outil interne brouillon

## 2. Structure des ecrans

Structure cible globale:
- rail gauche etroit pour la navigation
- grande zone centrale pour le travail actif
- panneau droit persistant pour contexte, suite logique, details, aide et signaux

Hierarchie des vues:
- vues de synthese:
  - Accueil
  - Vue du run
- vues de travail expertes:
  - Decisions
  - Qualite
  - Conflits
  - Execution
- vues utilitaires premium:
  - Reglages
  - Historique

Regles:
- le centre porte toujours la tache active
- le panneau droit ne remplace pas la tache, il l'eclaire
- la navigation reste compatible avec le produit actuel
- le panneau droit est un vrai inspecteur desktop-first, plus affirme que dans la variante equilibree

## 3. Ecrans cles retenus

### Accueil

Version retenue:
- `Variante A - Hub editorial de pilotage`

But:
- reprise de contexte premium
- tri clair des priorites
- meilleure qualite percue des le premier ecran

Composition:
- header editorial
- cartes de synthese hautes
- actions recommandees
- points a retenir
- panneau droit avec suite logique et rappels operateur

### Decisions

Version retenue:
- `Variante A - Table centrale + inspecteur droit`

But:
- faire de Decisions la vraie vue experte de reference

Composition:
- bande de contexte
- centre = filtres + actions + table
- droite = details ligne, signaux, justification, suite logique

### Conflits

Version retenue:
- `Variante A - Gate de validation avant execution`

But:
- transformer un ecran parfois pauvre en gate de verification credible et premium

Composition:
- statut global
- table ou empty state premium
- droite = consequences et action recommandee

### Execution

Version retenue:
- `Variante B - Safety-first`

But:
- prioriser clairement les garde-fous
- rassurer avant l'action irreversible

Composition:
- contexte et cadre d'execution
- gros bloc de prudence en haut
- resultat ensuite
- nettoyage / annulation apres
- droite = rappels et consequences

### Reglages

Version retenue:
- `Variante A - Configuration guidee a paliers`

But:
- rendre Reglages lisible, serein et plus premium

Composition:
- statut global de configuration
- paliers:
  - essentiel
  - hygiene et nettoyage
  - avance / technique
- droite = diagnostic et aide resumee

## 4. Palette

Palette canonique:
- fond principal: `#0B1017`
- fond secondaire: `#0F1622`
- surface 1: `#111826`
- surface 2: `#172132`
- surface elevee: `#1D2940`
- separation fine: `#243146`
- texte fort: `#F3F5F7`
- texte normal: `#D6DCE5`
- texte secondaire: `#A7B1C2`
- texte faible: `#7C8799`

Accents:
- accent principal froid: `#6FA8FF`
- accent secondaire calme: `#7DD3B0`
- accent studio limite: `#C9A45D`

Signals:
- info: `#5DA8D6`
- success: `#6FC39A`
- warning: `#D6A85F`
- danger: `#D16C6C`

Regles:
- l'accent studio reste limite aux moments de synthese
- le bleu froid porte les actions primaires
- le contraste entre fond, sous-surface et carte elevee doit etre visible sans agressivite
- la palette reste d'abord neutre; les accents chauds ne doivent jamais prendre le dessus sur les vues expertes

## 5. Typographie

Familles:
- sans: `Manrope`
- display: `Newsreader`
- mono: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`

Usage:
- `Manrope` = toute l'interface de travail
- `Newsreader` = titres de synthese et moments premium choisis
- `Mono` = ids, chemins, valeurs techniques

Regles:
- pas de `Newsreader` dans tables, filtres, formulaires ou ecrans techniques denses
- les titres de travail restent dans `Manrope`

## 6. Echelle d'espacement

Systeme:
- base 4

Echelle:
- `4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 64`

Regles:
- composants compacts: `8` a `16`
- cartes standard: `20` a `24`
- separations majeures: `32` a `48`
- pas de valeurs arbitraires hors echelle sauf ajustement fin 1 px / 2 px

## 7. Surfaces, rayons, bordures

Surfaces:
- `surface/base`
- `surface/default`
- `surface/subtle`
- `surface/elevated`
- `surface/overlay`

Rayons:
- petits composants: `8`
- boutons / inputs / selects: `10` ou `12`
- cartes standard: `14`
- cartes majeures: `18`

Bordures:
- standard: `1 px`
- fortes / focus: `1.5 px`

Regles:
- ombres legeres, rares
- contraste de surface prioritaire
- pas de rayons mous

## 8. Niveau de contraste

Principe:
- contraste fonctionnel eleve
- contraste emotionnel maitrise

Regles:
- texte primaire tres lisible
- surfaces suffisamment etagees
- badges et alertes colores sur fond faible
- pas de saturation excessive sur les grands blocs

Interaction:
- hover discret mais net
- focus visible et propre
- disabled lisible sans devenir fantome

## 9. Composants de base

Composants definis:
- Button
- Checkbox
- Input
- Select
- Badge
- Alert
- Card
- Page header
- Sidebar rail
- Right panel
- Data table shell

Orientation visuelle des composants:
- base `Tonal precision`
- accents editoriaux visibles surtout sur:
  - boutons primaires
  - cartes de synthese
  - badges premium choisis
  - headers de vues de synthese
- aucune sur-signature sur tableaux, filtres denses ou formulaires techniques

## 10. Boutons

Hierarchie:
- primaire
- secondaire
- tertiaire
- micro-action
- danger

Regles:
- primaire: plein, mat, net, accent froid
- secondaire: ton sur ton, bord discret
- tertiaire: calme, presque textuel
- micro-actions: lisibles, simples, jamais gadget
- danger: reserve aux actions irreversibles

## 11. Checkboxes

Regles:
- compactes
- contour fin
- coche simple
- etat coche clairement accentue
- focus visible sans glow large

But:
- excellente lecture en tableau et en lot

## 12. Formulaires

Champs:
- inputs et selects alignes visuellement
- surfaces tonales
- placeholders discrets
- focus net

Organisation:
- regrouper par intention
- labels courts
- aides courtes
- sections essentielles avant sections techniques

## 13. Tableaux

Principe:
- la table est une zone premium, pas un sous-produit

Regles:
- lignes legerement plus hautes que l'existant
- alignements numeriques propres
- actions visibles mais silencieuses
- zebra tres subtil ou separations fines
- badges, checkboxes et edition inline parfaitement integres
- densite controlee par defaut, sans compaction agressive

Role par ecran:
- Decisions = coeur du travail
- Qualite = audit detaille
- Conflits = verification avant action

## 14. Etats vides et erreurs

Empty states:
- dire ce qui manque
- dire pourquoi c'est vide
- dire quoi faire ensuite
- rester credibles visuellement

Errors and warnings:
- distinguer info, warning, danger
- expliciter:
  - probleme
  - impact
  - action recommandee
- ne jamais saturer l'ecran inutilement

## 15. Regles de hierarchie

Toujours montrer:
1. contexte
2. tache active
3. resultat ou consequence
4. suite logique

Regles:
- une page ne doit pas avoir 5 zones de meme poids
- le centre porte la preuve et l'action
- la droite porte le contexte et l'aide
- le haut de page doit expliquer l'ecran en une respiration
- la droite peut prendre plus de presence sur les vues expertes, mais le centre reste souverain

## 16. Ton visuel

Ton retenu:
- premium
- calme
- adulte
- precis
- dense mais pas etouffant

Interdits:
- glow massif
- contrastes gamer
- look flat pauvre
- look cinema demonstratif

## 17. Ton wording

Ton retenu:
- operateur
- clair
- fiable
- peu bavard

Regles:
- phrases courtes
- vocabulaire precis
- moins de pedagogie visible par defaut
- plus d'indications actionnables
- pas de marketing
- pas de paternalisme

## 18. Mise en oeuvre sans Figma

Ordre de mise en oeuvre:
1. appliquer la structure globale de shell retenue
2. poser les tokens visuels du design system
3. normaliser les primitives:
   - buttons
   - checkboxes
   - inputs
   - selects
   - badges
   - alerts
   - cards
4. refaire les ecrans cles selon les maquettes retenues:
   - Accueil A
   - Decisions A
   - Conflits A
   - Execution B
   - Reglages A
5. verifier via preview local, Playwright et screenshots

Regle d'implementation:
- si une ambiguite apparait, on met a jour ce document d'abord
- ensuite seulement on modifie le produit
