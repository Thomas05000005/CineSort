# 06 UI Directions

Contexte:
- lot 4 de la phase UI/design premium
- base sur l'interface reelle observee via preview local, Playwright et capture desktop
- Figma MCP indisponible dans cette session (`Auth required`)
- aucun changement produit dans ce document

Objectif:
- proposer 3 directions UI completes avant implementation
- garder un positionnement desktop-first explicite
- viser une app de tri, analyse et decision sur bibliotheque films

## Option A - Sobre premium

Esprit general:
- outil operateur premium, calme, maitrise, durable
- interface sombre neutre, moins bleue, plus editoriale que dashboard SaaS
- priorite a la clarte, avec quelques accents nobles et rares

Palette:
- fond principal: `#0B1017`
- surface 1: `#111826`
- surface 2: `#172132`
- surface elevee: `#1D2940`
- texte fort: `#F3F5F7`
- texte secondaire: `#A7B1C2`
- accent principal: `#6FA8FF`
- accent secondaire: `#7DD3B0`
- signal warning: `#D6A85F`
- signal danger: `#D16C6C`

Style des surfaces/cartes:
- cartes denses, bords fins, rayons moderes, tres peu de glow
- separation par profondeur et contraste local, pas par effets
- headers de cartes plus editoriaux, metadata plus fines

Style des boutons:
- primaire plein, net, leger relief sans halo
- secondaire en surface tonale avec bordure discrete
- tertiaire quasi textuel, reserve aux micro-actions

Style des checkboxes:
- formes compactes, angles legerement arrondis
- contour fin, remplissage accent maitrise, animation courte
- coche simple, nette, pas decorative

Style des tableaux:
- lignes un peu plus hautes que l'actuel
- colonnes mieux espacees, zebra tres subtil
- actions de ligne silencieuses par defaut, plus visibles au hover

Densite globale:
- moyenne a moyenne+ ; compacte sans effet tunnel

Avantages:
- credible pour un produit serieux
- bon fit avec les usages longs et repetes
- faible risque de lassitude visuelle
- facilite une montee en gamme sans casser les habitudes

Inconvenients:
- moins memorable qu'une direction plus identitaire
- peut rester trop sage si la typo et les details ne suivent pas

Risques:
- tomber dans un dark mode generique si l'accent est trop timide
- ne pas assez differencier les vues critiques si tout reste trop sobre

Meilleure pour:
- usage quotidien long
- operateur qui enchaine analyse, verification et execution
- environnement bureau ou la fiabilite percue compte plus que l'effet wow

## Option B - Studio / media tool haut de gamme

Esprit general:
- outil de catalogue et d'analyse cinema assume
- ambiance plus statutaire, plus memorisable, avec references discretement editoriales
- sensation de salle d'etalonnage ou d'outil studio, sans tomber dans le gadget

Palette:
- fond principal: `#090B10`
- surface 1: `#11141C`
- surface 2: `#181D28`
- surface elevee: `#232A37`
- texte fort: `#F6F1E8`
- texte secondaire: `#B7B0A4`
- accent principal: `#C9A45D`
- accent secondaire: `#5D8CC9`
- signal warning: `#D48B52`
- signal danger: `#BF6666`

Style des surfaces/cartes:
- cartes plus theatrales, contrastes plus marques, legers reflets ou gradients tres subtils
- headers forts, usage plus noble des espaces vides
- blocs cles traites comme des panneaux de controle premium

Style des boutons:
- primaire plus dense, presque "console premium", accent or/desature
- secondaire sombre avec liseres elegants
- micro-actions stylisees mais retenues

Style des checkboxes:
- plus fines, plus graphiques, avec accent chaud
- details visuels plus travailles que dans l'option A

Style des tableaux:
- tables plus editoriales, titres de colonnes mieux signes
- lignes plus aeriennes, metadata mieux hierarchisee
- selection et hover tres soignes

Densite globale:
- moyenne ; un peu moins compacte pour laisser vivre l'ambiance

Avantages:
- forte identite produit
- meilleure qualite percue immediate
- colle bien a l'univers film/media sans refaire l'UX

Inconvenients:
- plus dur a executer proprement
- peut paraitre trop "mise en scene" sur des ecrans tres techniques

Risques:
- basculer vers une app "cinema stylisee" plutot qu'un outil d'operateur
- fatiguer si les contrastes chauds ou les effets sont trop presents
- complexifier inutilement les composants data-dense

Meilleure pour:
- ecrans de synthese, home, dashboard, historique
- produit qui veut degager une identite marque plus forte
- demos, captures, perception haut de gamme immediate

## Option C - Operateur moderne tres lisible

Esprit general:
- poste de pilotage clair, methodique, net
- priorite maximale au scan, a la confiance et a la vitesse de decision
- sophistication surtout dans la structure et la lisibilite, pas dans l'effet

Palette:
- fond principal: `#0E141B`
- surface 1: `#151E28`
- surface 2: `#1B2633`
- surface elevee: `#223144`
- texte fort: `#F4F7FA`
- texte secondaire: `#9AA8B8`
- accent principal: `#58A6FF`
- accent secondaire: `#4FD1B5`
- signal warning: `#E2B55C`
- signal danger: `#E07A7A`

Style des surfaces/cartes:
- cartes plus utilitaires, tres propres, mieux segmentees par fonction
- separation forte entre zone de pilotage, zone de donnees et zone d'action
- peu d'effet decoratif, beaucoup de rigueur de grille

Style des boutons:
- primaire tres lisible, plus fonctionnel qu'editorial
- secondaires discrets mais clairs
- actions de tableau mieux cadrees, sans ambiguite

Style des checkboxes:
- tres nettes, contraste eleve, interaction evidente
- logique de controle d'outil pro avant tout

Style des tableaux:
- vrai travail sur la scannabilite
- colonnes, alignements numeriques et etats mieux calibres
- meilleur usage de la largeur desktop pour filtrer et comparer

Densite globale:
- moyenne+ a dense ; la plus productive des trois

Avantages:
- meilleure ergonomie sur les ecrans les plus charges
- bon alignement avec les besoins d'un operateur expert
- refonte plus rentable pour `Qualite`, `Decisions`, `Conflits`, `Reglages`

Inconvenients:
- moins emotionnelle
- premium percu depend beaucoup de la finition des details

Risques:
- devenir trop "outil interne optimise"
- manquer de statut visuel si les surfaces restent trop austeres

Meilleure pour:
- usage intensif de tri, verification, comparaison, batch
- ecrans data-dense et tables complexes
- equipe qui privilegie clarte et throughput

## Recommandations

Recommandation principale:
- Option A avec structure de l'Option C
- cible: "operateur premium"
- rationale: meilleur equilibre entre qualite percue, endurance visuelle et faisabilite

Recommandation secondaire:
- Option C
- cible: si la priorite absolue est la lisibilite et le rendement operateur

Choix top du top:
- une base Option A, poussee avec 15 a 20 pour cent des codes Option B sur les ecrans de synthese
- concretement: structure et densite A/C, accentuation editoriale B uniquement sur home, dashboard, historique et quelques moments de statut
- objectif: le meilleur niveau de gamme sans sacrifier la clarte du coeur operateur
