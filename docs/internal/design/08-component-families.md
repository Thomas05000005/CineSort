# 08 Component Families

Contexte:
- lot 6 de la phase UI/design premium
- base sur l'interface reelle observee via preview local, surtout `Decisions` et `Reglages`
- Figma MCP indisponible dans cette session (`Auth required`)
- aucun changement produit dans ce document

Objectif:
- proposer 3 familles premium pour les composants clefs
- couvrir: boutons, checkboxes, inputs, selects, badges, alertes, cartes
- privilegier des primitives adaptables a une app desktop-first dense et utilisee longtemps

## Famille A - Tonal precision

Esprit:
- premium sobre, technique, calme
- sensation de materiau ton sur ton tres maitrise
- qualite percue par la precision, pas par l'effet

Niveau de contraste:
- moyen a eleve sur les etats utiles
- faible a moyen sur les bordures et separations secondaires

Niveau de rondeur:
- modere
- rayons de 10 a 14 px sur les surfaces
- primitives petites entre 8 et 10 px

Densite:
- moyenne a moyenne+
- assez compacte pour les ecrans denses, sans agressivite

Style des checkboxes:
- petite boite tonale avec contour fin
- coche simple, claire, accent colore reserve a l'etat coche
- focus visible par halo fin externe, pas par glow large

Style des boutons:
- primaire plein mais mat, avec leger relief tonal
- secondaires en surface surteinte avec bord tres discret
- tertiaires quasi inline, tres silencieux

Style des inputs:
- champs pleins, peu contrastes, avec bord interne subtil
- placeholder tres discret, valeur plus lumineuse
- focus par lisere net et propre, sans halo spectaculaire

Style des selects:
- alignes sur les inputs
- chevron minimal, surface tonale continue
- etat ouvert privilegie la lisibilite de la liste plutot que l'effet

Style des badges:
- badges plats ou semi-tonaux
- code couleur controle, texte fort, fond peu sature
- tres bons pour `Haute`, `Moyenne`, `Prudent`, `Actif`

Style des alertes:
- bandeau ou carte basse hauteur
- accent lateral fin ou entete colorise
- messages graves plus denses que demonstratifs

Style des cartes:
- cartes avec profondeur legere par contraste local
- headers mieux signes que le corps
- tres peu d'ombre, beaucoup de rigueur

Avantages:
- excellent pour un usage long
- tres bonne compatibilite avec les vues metier denses
- premium sans surjouer
- robuste pour un systeme large de composants

Risques:
- peut paraitre trop prudent si la typo et la composition ne montent pas en gamme
- peut manquer de memorabilite immediate

Cas ou ce style est moins bon:
- ecrans vitrine ou moments marketing
- home si on veut une personnalite marque tres forte

## Famille B - Editorial studio

Esprit:
- premium plus statutaire, plus signe, plus "outil studio"
- melange de sobriete sombre et de details editoriaux plus nobles
- la forme participe davantage a la valeur percue

Niveau de contraste:
- moyen
- plus de contraste de matiere que de contraste brutal

Niveau de rondeur:
- modere a marque
- rayons de 12 a 16 px sur surfaces et actions principales

Densite:
- moyenne
- plus aerienne que la famille A

Style des checkboxes:
- petite piece graphique plus fine
- contour et remplissage plus luxueux, parfois accent chaud
- coche plus dessinee, plus signee

Style des boutons:
- primaires plus denses, plus "panneau premium"
- secondaires a liseres elegants
- micro-actions plus chic que fonctionnelles

Style des inputs:
- champs plus editoriaux, avec structure plus visible
- contrastes internes plus doux
- curseur, focus et aide plus raffines

Style des selects:
- selects plus statutaire, parfois avec surface legerement relevee
- ouvre sur des listes plus aeriennes, mieux spatiees

Style des badges:
- badges plus signes, parfois capsule
- palette plus noble, notamment or/ambre/desature
- bons pour les statuts de synthese et la qualite percue

Style des alertes:
- alertes plus scenarisees
- couleur mieux integree dans la surface
- plus memorables mais aussi plus visibles

Style des cartes:
- cartes plus nobles, parfois avec gradient tres subtil
- sentiment de panneau premium ou d'instrument de controle haut de gamme

Avantages:
- identite immediate plus forte
- qualite percue plus haute sur les captures et ecrans de synthese
- bon fit avec l'univers film/media

Risques:
- execution plus delicate
- danger de surstylisation sur des vues comme `Decisions` ou `Reglages`
- plus difficile a maintenir coherent partout

Cas ou ce style est moins bon:
- tables tres denses
- workflows longs ou repetitifs si l'ambiance devient trop presente

## Famille C - Crisp operator

Esprit:
- outil operateur moderne, net, sans ambiguite
- premium par la clarte, la maitrise et la regularite
- langage plus sec mais potentiellement tres fort si parfaitement execute

Niveau de contraste:
- eleve sur les zones interactives
- moyen sur les surfaces de second plan

Niveau de rondeur:
- faible a modere
- angles plus fermes, rayons de 8 a 12 px

Densite:
- moyenne+ a dense
- la plus productive des trois

Style des checkboxes:
- tres nettes, plus geometriques
- coche contrastee, lecture immediate
- parfaites pour les tables et selections de lot

Style des boutons:
- primaires francs, lisibles, tres stables
- secondaires plus "outil" que "boutique"
- micro-actions tres claires, moins decoratives

Style des inputs:
- champs precis, bordure lisible, contraste un peu plus ferme
- focus fort et utile
- excellente clarte sur les formulaires longs

Style des selects:
- selects plus techniques, moins luxueux
- priorite au scan et a la comprehensibilite des options

Style des badges:
- badges compacts, tres lisibles, codes couleur plus francs
- ideaux pour tableaux, risques, niveaux de confiance

Style des alertes:
- alertes tres explicites
- bon usage des icones, des titres et des niveaux de severite
- excellentes pour les flux a risque

Style des cartes:
- cartes plus structurelles que decoratives
- segmentation tres claire entre entete, contenu, actions

Avantages:
- meilleure lisibilite pour les usages experts
- parfait pour `Decisions`, `Qualite`, `Conflits`, `Reglages`
- systeme tres efficace sur le long terme

Risques:
- peut perdre du prestige si la finition est trop utilitaire
- moins de chaleur et moins de singularite immediate

Cas ou ce style est moins bon:
- ecrans d'accueil ou de synthese si on veut un effet premium emotionnel
- zones ou la marque doit s'exprimer plus fort

## Recommandation

Meilleure famille pour une app pro/premium lisible longtemps:
- Famille A - Tonal precision

Rationale:
- c'est la meilleure combinaison entre endurance visuelle, niveau de gamme, compatibilite avec la densite metier et faisabilite d'implementation
- elle laisse aussi de la place pour injecter quelques accents de la famille B sur les ecrans de synthese, sans affaiblir les vues operateur

Recommendation secondaire:
- Famille C - Crisp operator
- a retenir si la priorite absolue devient le rendement operateur sur les ecrans les plus denses
