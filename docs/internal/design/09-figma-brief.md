# 09 Figma Brief

Contexte:
- lot 7 de la phase UI/design premium
- base sur les choix valides par l'utilisateur
- Figma MCP indisponible dans cette session (`Auth required`)
- ce document sert de brief Figma complet et de source de verite locale equivalent
- aucun changement produit dans ce document

## 1. Objectif de l'app

CineSort est une application desktop-first de tri, analyse, verification et preparation d'execution sur une bibliotheque films. Elle doit aider un operateur a:
- comprendre rapidement l'etat d'un run
- verifier la qualite des donnees et du matching
- prendre des decisions ligne par ligne ou en lot
- controler les risques avant execution
- configurer l'environnement local sans ambiguites

Le produit ne doit pas ressembler a une app marketing ou a un media center. Il doit ressembler a un outil de pilotage premium, fiable, precis et mature.

## 2. Public

Public principal:
- operateur avance ou semi-expert
- utilisateur desktop qui travaille longtemps sur de grands volumes
- personne sensible a la fiabilite, a la clarte, aux garde-fous et au controle

Public secondaire:
- utilisateur passionne de cinema qui veut un outil plus haut de gamme qu'un simple utilitaire

## 3. Posture visuelle retenue

Direction validee:
- base `Sobre premium`
- accents limites `Studio / media tool haut de gamme`
- structure d'interface `Workspace a trois zones permanentes`
- famille de composants `Tonal precision`

Traduction:
- coeur de l'application = premium sobre, tres lisible, rigoureux
- ecrans de synthese = legere signature studio/media plus editoriale
- ecrans denses = aucune theatrisation excessive
- l'app doit paraitre plus haut de gamme que l'existant, sans perdre le caractere d'outil operateur

## 4. Palette

Base recommandee:
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
- l'accent studio chaud ne doit pas devenir la couleur dominante de l'app
- les accents forts doivent etre reserves aux CTA, statuts et moments importants
- la differenciation entre fond, surface, sous-surface et carte elevee doit etre nette mais calme

## 5. Navigation

Structure cible:
- rail gauche etroit pour la navigation globale
- centre large pour le travail principal
- panneau droit persistant pour contexte, details, suite logique, aide, signaux et actions secondaires

Regles:
- le rail gauche ne doit plus etre narratif ou massif
- la zone centrale porte la tache active
- le panneau droit ne doit pas devenir un fourre-tout
- la navigation doit rester compatible avec la logique produit actuelle:
  - Accueil
  - Analyse
  - Vue du run
  - Cas a revoir
  - Decisions
  - Execution
  - Qualite
  - Conflits
  - Historique
  - Reglages

Hierarchie:
- Accueil et Vue du run = hubs de synthese
- Decisions, Qualite, Conflits, Execution = vues de travail expertes
- Historique, Reglages = utilitaires premium, pas ecrans secondaires negliges

## 6. Densite

Niveau cible:
- moyenne a moyenne+ globalement
- dense la ou le metier l'exige
- jamais aeree artificiellement

Regles:
- pas de grands vides morts
- pas de murs de texte
- les blocs doivent etre compactes, lisibles et bien etages
- la densite doit varier selon la vue:
  - synthese: plus de respiration
  - travail expert: plus de compaction

## 7. Composants

### Boutons

Objectif:
- hierarchy tres claire entre primaire, secondaire, tertiaire, micro-action

Regles:
- primaire: plein, mat, net, sans glow spectaculaire
- secondaire: surface tonale avec bord discret
- tertiaire: visuel calme, presque textuel
- micro-actions: simples, lisibles, jamais gadget
- eviter la proliferation de boutons qui semblent tous importants

### Checkboxes

Objectif:
- lecture immediate dans les tables et les selections de lot

Regles:
- boite compacte, contour fin
- coche simple et nette
- etat coche accentue, etat non coche sobre
- focus visible, propre, sans halo large

### Inputs

Objectif:
- champs fiables, precis, peu demonstratifs

Regles:
- surface tonale stable
- placeholder faible, valeur plus forte
- bord interne ou lisere fin pour la precision
- focus net, contraste propre, aucune lourdeur

### Selects

Objectif:
- alignement total avec les inputs

Regles:
- meme structure visuelle que les champs texte
- chevron minimal
- liste ouverte lisible, aeree juste ce qu'il faut
- etats hover et selected bien differencies

### Badges

Objectif:
- systeme de statuts clair et premium

Regles:
- badges plats ou semi-tonaux
- faible saturation du fond, texte plus fort
- usage central pour:
  - confiance
  - severite
  - prudence
  - etat de run
  - etat d'outils

### Alertes

Objectif:
- signaux graves, lisibles, non theatrals

Regles:
- preferer des bandeaux ou cartes basses
- accent lateral fin ou entete colore
- severite lisible immediatement
- ne pas transformer chaque message en bloc dramatique

### Cartes

Objectif:
- systeme de cartes mature, avec niveaux de profondeur differencies

Regles:
- 3 niveaux maximum: surface simple, carte standard, carte elevee
- peu d'ombre, beaucoup de contraste local
- headers mieux signes que le corps
- cartes de synthese plus editoriales sur Accueil et Vue du run

## 8. Tableaux

Objectif:
- faire des tableaux le coeur premium du produit, pas une zone neutre ou pauvre

Regles:
- lignes legerement plus hautes que l'actuel
- alignements numeriques propres
- colonnes stables
- actions de ligne visibles mais pas bruyantes
- zebra tres subtil ou separation locale tres fine
- badges et checkboxes parfaitement integres
- edition inline fiable et lisible

Pour `Decisions`, `Qualite`, `Conflits`:
- la table doit rester la vraie zone de travail
- les details lourds ou explicatifs doivent plutot vivre a droite que casser le flux central

## 9. Formulaires

Objectif:
- rendre `Reglages` et les zones de filtres expertes plus solides et plus faciles a parcourir

Regles:
- grouper par intention, pas seulement par type de champ
- labels courts, aides courtes
- sections essentielles avant sections techniques
- sticky action bar conservee si elle existe, mais plus premium
- eviter les longues colonnes sans respiration logique

## 10. Etats vides

Objectif:
- ne plus donner une impression de vide pauvre ou de prototype

Regles:
- chaque empty state doit indiquer:
  - ce qu'il manque
  - pourquoi c'est vide
  - quoi faire ensuite
- ton calme, adulte, non infantilisant
- sur les vues premium, une composition vide doit rester credible visuellement

## 11. Etats d'erreur et warning

Objectif:
- rassurer par la clarte, pas par la dramatisation

Regles:
- distinguer nettement info, warning, danger
- toujours formuler:
  - le probleme
  - l'impact
  - l'action recommandee
- l'etat visuel doit signaler la gravite sans saturer l'ecran

## 12. Ton du wording

Ton cible:
- operateur, clair, adulte, fiable

Regles:
- phrases courtes
- vocabulaire precis
- moins de texte pedagogique visible par defaut
- plus d'indications actionnables
- eviter le jargon technique inutile si le contexte peut le simplifier
- garder les termes metier necessaires, mais mieux les hierarchiser

Le produit doit parler comme un outil serieux:
- pas froid
- pas marketing
- pas bavard
- pas paternaliste

## 13. Regles desktop-first

Contraintes cibles:
- optimisation explicite pour `1250px+`
- largeur exploitee pour separer action, contexte et donnees
- scroll horizontal reserve aux tables si necessaire, pas aux pages entieres
- dense mais respirable sur desktop standard

Regles:
- toujours penser en largeur utile
- les panneaux secondaires ne doivent pas casser la tache centrale
- les blocs de synthese doivent rester visibles au-dessus de la ligne de flottaison
- la priorite va a la comprehension rapide du run et des decisions a prendre

## 14. Ecrans a maquetter en priorite

Lot 1:
- Accueil
- Vue du run
- Decisions
- Qualite

Lot 2:
- Conflits
- Execution
- Reglages

Lot 3:
- Historique
- Cas a revoir
- Duplicates / vues annexes si elles restent dans le flux

## 15. Composants a normaliser en premier

Ordre recommande:
1. shell global: rail gauche, header de page, panneau droit
2. boutons
3. checkboxes
4. inputs et selects
5. badges
6. cartes
7. alertes
8. tableaux et actions de ligne

## 16. Points de validation attendus

Validation attendue sur:
- niveau exact de presence des accents studio sur les ecrans de synthese
- agressivite ou sobriete du panneau droit persistant
- densite cible de `Decisions` et `Qualite`
- niveau de contraste des badges et alertes
- degre de raffinement des cartes de synthese sur Accueil et Vue du run

Decision deja stabilisee:
- pas de refonte flashy
- pas de style gamer/cinema app
- pas de composants trop mous ou trop ronds
- pas de theme dark monotone sans hierarchie
