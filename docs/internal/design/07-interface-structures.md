# 07 Interface Structures

Contexte:
- lot 5 de la phase UI/design premium
- base sur l'interface reelle observee via preview local
- Figma MCP indisponible dans cette session (`Auth required`)
- objectif: proposer des structures d'interface compatibles avec le produit actuel
- aucun changement produit dans ce document

Contraintes:
- garder la logique metier actuelle
- rester desktop-first
- ne pas casser les vues clefs: home, dashboard, qualite, decisions, execution, reglages
- limiter les ruptures de navigation pour l'operateur existant

## Structure A - Evolution premium du shell actuel

Schema general:
- sidebar gauche conservee comme navigation primaire
- zone centrale = contenu principal empile par sections
- panneau droit contextuel uniquement sur les vues qui le justifient
- top bar reste legere: contexte de run, actions globales, aide

Ce qui change:
- sidebar plus compacte et plus nette
- header de page mieux segmente: titre, resume, contexte, actions
- panneau droit reserve a la "suite logique", au risque et aux actions secondaires
- vues denses organisees en 3 strates: contexte, filtres/actions, table principale

Ce qui ne change pas:
- groupes de navigation actuels
- vocabulaire principal des ecrans
- logique de parcours Accueil -> Analyse -> Vue du run -> Decisions -> Execution
- principe des modules separes pour Qualite, Conflits, Reglages

Avantages:
- le plus compatible avec le produit actuel
- implementation incremental simple a planifier
- apprentissage quasi nul pour les utilisateurs existants
- bon levier de montee en gamme sans risque majeur

Risques:
- peut rester trop proche de l'existant si la hierarchie n'est pas vraiment durcie
- sidebar encore visuellement lourde si elle n'est pas simplifiee

Difficulte d'implementation:
- moyenne

Impact ergonomique:
- bon gain de clarte
- baisse de la fatigue sur les vues denses
- progression du parcours sans rupture d'habitudes

## Structure B - Workspace a trois zones permanentes

Schema general:
- rail gauche plus etroit pour la navigation globale
- grande zone centrale pour le travail principal
- panneau droit persistant pour contexte, details ligne, aide, actions de lot
- header de page plus sobre; une partie du contexte descend dans le panneau droit

Ce qui change:
- la sidebar devient un rail plus fonctionnel que narratif
- le panneau droit devient une vraie colonne produit, pas un bloc occasionnel
- les vues `Decisions`, `Qualite`, `Conflits` et `Execution` gagnent un inspecteur stable
- les details de ligne, warnings et next steps sortent du flux central

Ce qui ne change pas:
- architecture fonctionnelle des ecrans
- logique des donnees et des modules
- tables et formulaires comme coeur du travail metier

Avantages:
- excellente structure pour desktop-first
- clarifie mieux la separation entre "travail", "contexte" et "action"
- rend le produit plus premium et plus professionnel
- tres bonne base pour les ecrans data-dense

Risques:
- peut faire perdre de la largeur utile si le panneau droit est mal gere
- home et reglages doivent etre adaptes pour ne pas paraitre trop vides
- demande une discipline forte sur ce qui merite vraiment d'aller a droite

Difficulte d'implementation:
- moyenne a elevee

Impact ergonomique:
- tres bon sur les ecrans experts
- gain net en scannabilite et en lecture des consequences
- leger cout d'adaptation initial

## Structure C - Poste de pilotage modulaire

Schema general:
- navigation primaire a gauche
- centre organise par "workspace" principal
- bandeau superieur workflow plus present: run actif, niveau de risque, etape suivante
- panneaux secondaires modulaires selon la vue: tiroir droit, barre de lot, sous-navigation locale

Ce qui change:
- chaque grand ecran adopte une composition plus specialisee
- `Accueil` et `Vue du run` deviennent de vrais hubs de pilotage
- `Decisions` et `Qualite` gagnent une sous-structure locale par mode ou sous-tache
- `Reglages` passe vers une navigation locale plus progressive par sections

Ce qui ne change pas:
- liste des ecrans et leur role metier
- ordre global du workflow
- separation entre vues operationnelles et vues utilitaires

Avantages:
- structure la plus ambitieuse sans sortir du produit actuel
- meilleur potentiel premium global
- permet de traiter differemment les vues calmes et les vues tres denses
- donne un vrai sentiment de systeme produit mature

Risques:
- le plus facile a surdesigner ou surcomplexifier
- demande une excellente coherence entre ecrans
- implementation plus longue, avec plus de decisions de detail

Difficulte d'implementation:
- elevee

Impact ergonomique:
- potentiellement excellent si bien execute
- meilleure adequation vue par vue
- risque de variabilite excessive si la grammaire commune n'est pas stricte

## Recommandations

Structure recommandee:
- Structure B
- rationale: meilleur equilibre entre clarte desktop, compatibilite produit et montee en gamme reelle
- cible ideale pour `Decisions`, `Qualite`, `Conflits`, `Execution`

Structure la plus ambitieuse raisonnable:
- Structure C
- rationale: c'est celle qui peut produire le meilleur resultat final, mais seulement si les fondations de shell, hierarchie et composants sont deja solides

Note de cadrage:
- si l'objectif est de reduire le risque d'implementation, commencer par A
- si l'objectif est de viser une vraie refonte premium credible, B est le meilleur point d'atterrissage
- si l'objectif est le top niveau produit, viser C par etapes, en passant d'abord par une base A/B
