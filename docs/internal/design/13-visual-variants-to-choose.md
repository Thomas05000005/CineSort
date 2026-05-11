# 13 Visual Variants To Choose

Contexte:
- Figma est indisponible pour cette phase
- ce document prepare les choix visuels restants sans dependance externe
- il ne remplace pas la source canonique
- la source canonique reste [12-local-source-of-truth.md](./12-local-source-of-truth.md)

Usage:
- comparer les variantes ci-dessous
- choisir explicitement une option par famille
- une fois les choix valides, mettre a jour la source canonique puis seulement implementer

Validation utilisateur recue:
- `Palette = A`
- `Composants = B`
- `Structure = B`
- `Densite = A`

## 1. Variante palette

### Option A - Neutral premium

Idee:
- palette plus neutre, plus froide, plus mature
- l'accent studio reste rare et discret

Ce qui change reellement:
- fonds moins bleutes
- cartes et surfaces plus separees par valeur que par couleur
- accent principal plus sobre
- l'app parait plus adulte et moins "tool dark bleu"

Avantages:
- plus durable
- moins fatigant sur usage long
- meilleur fond de scene pour des tableaux denses
- plus simple a deployer proprement sur tout le produit

Inconvenients:
- moins demonstratif
- moins "wow" sur Accueil et Historique

Recommandation:
- oui, c'est ma recommandation principale

Choix explicite:
- `Palette = A`

### Option B - Premium studio accentue

Idee:
- garder la base sombre premium, mais donner plus de presence aux accents chauds studio/media

Ce qui change reellement:
- cartes de synthese plus statutaires
- moments clefs plus cinematographiques
- plus de contraste identitaire entre vues de synthese et vues metier

Avantages:
- perception haut de gamme immediate
- captures plus memorables
- meilleur effet premium sur Accueil et Vue du run

Inconvenients:
- execution plus delicate
- plus facile a surjouer
- risque de desequilibre avec les vues denses

Recommandation:
- non, seulement en accent limite

Choix explicite:
- `Palette = B`

## 2. Variante composants

### Option A - Tonal precision strict

Idee:
- composants mats, precis, tonaux, sans effet superflu

Ce qui change reellement:
- boutons plus calmes
- badges plus integres
- inputs et selects plus nobles
- checkboxes plus fines
- alertes moins brutales et mieux structurees

Avantages:
- meilleure endurance visuelle
- plus premium sur usage long
- tres bon fit avec Decisions, Qualite, Reglages

Inconvenients:
- moins demonstratif en premiere impression

Recommandation:
- oui, c'est la recommandation principale

Choix explicite:
- `Composants = A`

### Option B - Tonal precision avec accents editoriaux

Idee:
- base identique a A, mais avec plus de signature sur certains composants visibles

Ce qui change reellement:
- boutons primaires plus signes
- cartes de synthese plus nobles
- badges premium plus expresifs
- titres et headers un peu plus editoriaux

Avantages:
- meilleur niveau de gamme percu
- plus de personnalite
- bon compromis si on veut un peu plus de caractere sans changer tout le systeme

Inconvenients:
- risque de casser l'unite si les accents debordent sur les vues techniques
- demande plus de discipline d'application

Recommandation:
- oui, comme variante secondaire si tu veux plus de presence visuelle

Choix explicite:
- `Composants = B`

## 3. Variante structure

### Option A - Trois zones equilibrees

Idee:
- rail gauche discret, centre dominant, panneau droit utile mais secondaire

Ce qui change reellement:
- la droite reste visible sans voler trop de largeur
- les ecrans denses gardent une grande table centrale
- le shell parait plus calme et plus maitrise

Avantages:
- meilleur equilibre global
- plus robuste pour tout le produit
- moins de risque sur Decisions et Qualite

Inconvenients:
- un peu moins spectaculaire
- le panneau droit est moins "presence produit"

Recommandation:
- oui, c'est ma recommandation principale

Choix explicite:
- `Structure = A`

### Option B - Trois zones avec inspecteur affirme

Idee:
- meme architecture, mais panneau droit plus assume et plus actif dans la lecture de l'ecran

Ce qui change reellement:
- inspecteur plus large
- plus de contexte et de guidance a droite
- meilleure sensation de poste de pilotage desktop

Avantages:
- plus premium
- meilleur pour Decisions, Conflits et Execution
- donne une vraie signature desktop-first

Inconvenients:
- plus exigeant en composition
- peut reduire trop la largeur utile si mal calibre

Recommandation:
- oui si tu veux pousser davantage la promesse premium desktop

Choix explicite:
- `Structure = B`

## 4. Variante densite

### Option A - Densite controlee

Idee:
- donner plus d'air a l'app sans la rendre molle

Ce qui change reellement:
- lignes de table un peu plus hautes
- plus de respiration entre sections
- cartes et formulaires plus confortables
- lecture plus sereine

Avantages:
- meilleure qualite percue immediate
- moins de fatigue
- meilleur pour Accueil, Conflits, Reglages, Execution

Inconvenients:
- moins de donnees visibles simultanement
- peut sembler un peu plus lent pour les operateurs experts

Recommandation:
- oui, pour l'ensemble du produit avec exceptions localisees

Choix explicite:
- `Densite = A`

### Option B - Densite experte

Idee:
- garder une UI premium mais plus compacte sur les vues de production

Ce qui change reellement:
- plus d'informations visibles
- tables plus serrees
- forms et panneaux plus compacts
- l'outil parait plus expert et plus direct

Avantages:
- meilleur rendement operateur
- tres bon pour Decisions et Qualite
- meilleure exploitation de la largeur desktop

Inconvenients:
- perception premium plus fragile
- risque de retomber vers un outil interne optimize

Recommandation:
- non en global, oui seulement localement sur les vues les plus denses

Choix explicite:
- `Densite = B`

## 5. Combo recommande

Recommandation principale:
- `Palette = A`
- `Composants = A`
- `Structure = A`
- `Densite = A`

Variante premium plus ambitieuse:
- `Palette = A`
- `Composants = B`
- `Structure = B`
- `Densite = A`

Variante expert plus dense:
- `Palette = A`
- `Composants = A`
- `Structure = A`
- `Densite = B`

## 6. Reponse attendue

Repondre avec:

```text
Palette = A ou B
Composants = A ou B
Structure = A ou B
Densite = A ou B
```
