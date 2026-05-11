# 11 Key Screen Mockups

Contexte:
- lot 9 de la phase UI/design premium
- `figma` indisponible dans cette session (`Auth required`)
- base sur l'interface reelle observee sur les vues Accueil, Conflits, Execution et Reglages, et sur les audits precedents de Decisions
- aucun changement produit dans ce document

Direction appliquee:
- posture visuelle = base sobre premium + accents studio limites
- structure = workspace a trois zones permanentes
- composants = tonal precision

Cadre commun a toutes les maquettes:
- rail gauche plus etroit et plus net
- header de page plus editorial mais plus court
- centre = zone de travail
- panneau droit persistant = contexte, details, suite logique, aide, signaux
- densite moyenne+ sauf ecrans de synthese plus respirants

## 1. Synthese / Accueil

### Variante A - Hub editorial de pilotage

Intention:
- faire d'Accueil une vraie vue premium de reprise de contexte
- donner une meilleure qualite percue sans perdre la logique operateur

Structure:
- header large avec titre display, resume operateur court et badge de statut run
- centre en deux bandes:
  - bande 1: cartes de synthese
  - bande 2: actions et alertes prioritaires
- panneau droit persistant:
  - suite logique
  - run actif
  - 3 rappels operateur courts

Centre:
- ligne 1:
  - carte `Etat de l'environnement`
  - carte `Dernier run utile`
  - carte `Sante recente`
- ligne 2:
  - bloc `Actions recommandees maintenant`
  - bloc `Points a retenir`
- ligne 3 optionnelle:
  - mini historique recent

Hierarchie:
- le vrai hero devient le run actif et son niveau de confiance
- les actions rapides passent d'une grappe de boutons a une selection plus serree de 3 actions prioritaires + 2 secondaires discretes
- l'accent studio se limite au titre, a quelques separateurs et a une carte de synthese haute

Qualite percue:
- plus premium
- plus mature
- moins dashboard utilitaire

### Variante B - Tableau de bord compact operateur

Intention:
- garder Accueil tres productif
- limiter la part editoriale

Structure:
- header plus court
- centre majoritairement en grille de cartes compactes
- panneau droit plus utilitaire

Centre:
- grille 2x3 de cartes de statut
- bloc `Actions rapides`
- bloc `Anomalies et priorites`

Hierarchie:
- plus froide
- plus directe
- moins haut de gamme que la variante A

Recommendation:
- retenir Variante A

## 2. Decisions

### Variante A - Table centrale + inspecteur droit

Intention:
- faire de Decisions la vue experte de reference
- clarifier le travail sans casser la densite metier

Structure:
- bande de contexte en haut:
  - run actif
  - film actif
  - mode avance
- centre:
  - colonne principale large avec filtres, actions de table, tableau
- panneau droit:
  - details de la ligne selectionnee
  - pourquoi ce choix
  - signaux de risque
  - next step vers Conflits

Centre:
- bloc 1: filtres principaux, recherche, raccourcis
- bloc 2: actions globales et stats visibles
- bloc 3: table de decision

Panneau droit:
- si aucune ligne selectionnee:
  - message de guidage sobre
  - rappel des criteres de relecture
- si ligne selectionnee:
  - resume
  - source retenue
  - analyse
  - options/propositions
  - alertes eventuelles

Hierarchie:
- la table reste le coeur
- tout ce qui est explicatif quitte la zone centrale
- les actions de lot sont plus proches de la table, moins eparpillees

Qualite percue:
- beaucoup plus premium
- beaucoup plus maitrisee
- meilleure lecture de cause -> decision -> consequence

### Variante B - Decisions ultra-dense

Intention:
- pousser au maximum la productivite

Structure:
- filtres tres compacts
- table plus haute a l'ecran
- panneau droit reductible ou plus mince

Effet:
- meilleure densite brute
- moins de respiration
- rendu plus expert, moins premium

Recommendation:
- retenir Variante A

## 3. Conflits

### Variante A - Gate de validation avant execution

Intention:
- transformer Conflits en ecran de gate premium
- rendre la vue credible meme quand il n'y a aucun blocage

Structure:
- header avec ton de verification, pas de dramatisation
- centre:
  - bande de statut global
  - liste/table des conflits ou etat vide premium
- panneau droit:
  - consequence du blocage
  - action recommandee
  - lien vers Decisions / Execution

Centre:
- bloc 1:
  - carte `Statut des collisions`
  - stats `lignes controlees / blocages / deja present / doublons de cible`
- bloc 2:
  - table de conflits
  - ou empty state haut de gamme si aucun conflit

Etat vide cible:
- `Aucun blocage detecte`
- phrase d'impact
- action principale `Poursuivre vers Execution`
- action secondaire `Revenir a Decisions`

Hierarchie:
- quand il n'y a pas de conflit, la vue doit quand meme paraitre terminee et serieuse
- quand il y a conflit, le centre montre le probleme, la droite montre la marche a suivre

Recommendation:
- une seule variante suffit ici

## 4. Execution

### Variante A - Result-first

Intention:
- faire d'Execution un ecran oriente resultat, pas un ecran oriente vide ou precaution diffuse

Structure:
- bande de contexte en haut:
  - run actif
  - cadre d'execution
- centre:
  - colonne principale centree sur le resultat
- panneau droit:
  - garde-fous
  - reperes
  - undo / consequences

Centre:
- bloc 1:
  - `Executer les decisions validees`
  - CTA principal
  - controles mode test / review
- bloc 2:
  - `Resultat d'execution`
  - journal, status, resume
- bloc 3:
  - `Nettoyage residuel`
  - seulement apres le resultat
- bloc 4:
  - `Annulation`
  - preview avant action reelle

Hierarchie:
- le resultat passe au-dessus du nettoyage et de l'undo
- la gauche du flux raconte ce qui s'est passe
- la droite rappelle ce qu'il faut verifier

Qualite percue:
- plus claire
- plus adulte
- plus premium que l'existant

### Variante B - Safety-first

Intention:
- prioriser les garde-fous avant tout

Structure:
- gros bloc de prudence en haut
- resultat plus bas

Effet:
- plus rassurant pour un premier usage
- moins dynamique
- peut paraitre trop prudent, trop verbeux

Recommendation:
- retenir Variante A

## 5. Reglages

### Variante A - Configuration guidee a paliers

Intention:
- rendre Reglages beaucoup plus lisible sans perdre sa profondeur

Structure:
- header court + statut global de configuration
- centre organise en paliers:
  - palier 1 = essentiel
  - palier 2 = hygiene et nettoyage
  - palier 3 = avance / technique
- panneau droit:
  - diagnostic operateur
  - statut systeme
  - aide resumee

Centre:
- bloc hero:
  - `Etat de configuration`
  - progression de preparation
- section 1:
  - bibliotheque et stockage
  - TMDb
  - outils video
  - rappel avant run
- section 2:
  - dossiers vides
  - nettoyage residuel
- section 3:
  - scan / matching
  - technique

Interaction:
- barre d'enregistrement sticky conservee
- aide locale simplifiee
- labels plus courts
- zones techniques toujours presentes mais moins envahissantes

Hierarchie:
- le diagnostic quitte le centre principal et vit surtout a droite
- la section `Essentiel` doit tenir le plus possible au-dessus de la ligne de flottaison

Recommendation:
- une seule variante suffit ici

## 6. Arbitrages deja faits

Decides dans ce lot:
- base visuelle sobre premium
- accents studio limites aux moments de synthese
- rail gauche aminci
- panneau droit persistant sur les vues clefs
- tables gardees comme coeur de travail
- Decisions et Execution traites avec une variante recommandee claire
- validation utilisateur recue:
  - `Accueil = Variante A`
  - `Decisions = Variante A`
  - `Execution = Variante B`

Recommandations de variantes:
- Accueil = Variante A
- Decisions = Variante A
- Conflits = Variante A
- Execution = Variante A
- Reglages = Variante A

## 7. Arbitrages a faire choisir

Choix utilisateur encore utiles:
- Conflits:
  - confirmer qu'une seule variante suffit
- Reglages:
  - confirmer qu'une seule variante suffit

Tous les autres arbitrages peuvent rester implicites pour l'instant sans perdre de clarte produit.

## 8. Figma framing recommande

Frames a creer ensuite dans Figma:
1. `Accueil / Variante A`
2. `Accueil / Variante B`
3. `Decisions / Variante A`
4. `Decisions / Variante B`
5. `Conflits / Variante A`
6. `Execution / Variante A`
7. `Execution / Variante B`
8. `Reglages / Variante A`

Ordre de maquettage recommande:
1. Accueil A
2. Decisions A
3. Execution A
4. Reglages A
5. Conflits A
6. variantes B restantes si besoin de comparaison
