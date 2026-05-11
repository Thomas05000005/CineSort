# 10 Design System Foundation

Contexte:
- lot 8 de la phase UI/design premium
- `figma` indisponible dans cette session (`Auth required`)
- ce document sert de fondation design system locale et de base directe pour une future bibliotheque Figma
- aucun changement produit dans ce document

## 1. Logique generale

Le design system doit servir un produit:
- desktop-first
- data-dense
- premium sans theatrisation
- lisible sur des sessions longues

Le systeme repose sur 3 couches:
1. tokens primitifs
2. tokens semantiques
3. composants

Regle cle:
- un composant ne consomme pas directement une couleur brute si un token semantique existe deja

## 2. Architecture des tokens

### 2.1 Tokens primitifs

Usage:
- valeurs brutes de couleur, rayon, bordure, ombre, typo, spacing
- servent de base aux couches semantiques

### 2.2 Tokens semantiques

Usage:
- expriment le role dans l'interface
- exemples:
  - `surface/base`
  - `text/primary`
  - `border/subtle`
  - `action/primary/bg`
  - `state/warning/fg`

### 2.3 Tokens de composants

Usage:
- specialisent un composant sans casser la logique globale
- exemples:
  - `button/primary/bg/default`
  - `input/focus/ring`
  - `badge/warning/bg`

## 3. Palette

### 3.1 Couleurs primitives

Neutres:
- `neutral-950` = `#0B1017`
- `neutral-925` = `#0F1622`
- `neutral-900` = `#111826`
- `neutral-850` = `#172132`
- `neutral-800` = `#1D2940`
- `neutral-700` = `#243146`
- `neutral-600` = `#3A4860`
- `neutral-500` = `#5B6880`
- `neutral-400` = `#7C8799`
- `neutral-300` = `#A7B1C2`
- `neutral-200` = `#D6DCE5`
- `neutral-100` = `#F3F5F7`

Accent froid:
- `blue-500` = `#6FA8FF`
- `blue-600` = `#5D94EB`
- `blue-700` = `#4A7FD2`
- `blue-050` = `rgba(111,168,255,.14)`

Accent calme:
- `mint-500` = `#7DD3B0`
- `mint-600` = `#67BB98`
- `mint-050` = `rgba(125,211,176,.14)`

Accent studio limite:
- `gold-500` = `#C9A45D`
- `gold-600` = `#B48E49`
- `gold-050` = `rgba(201,164,93,.14)`

Signals:
- `info-500` = `#5DA8D6`
- `success-500` = `#6FC39A`
- `warning-500` = `#D6A85F`
- `danger-500` = `#D16C6C`
- `info-050` = `rgba(93,168,214,.14)`
- `success-050` = `rgba(111,195,154,.14)`
- `warning-050` = `rgba(214,168,95,.14)`
- `danger-050` = `rgba(209,108,108,.14)`

### 3.2 Tokens semantiques de couleur

Surfaces:
- `surface/base` = `neutral-950`
- `surface/canvas` = `neutral-925`
- `surface/default` = `neutral-900`
- `surface/subtle` = `neutral-850`
- `surface/elevated` = `neutral-800`
- `surface/overlay` = `rgba(11,16,23,.82)`

Texte:
- `text/primary` = `neutral-100`
- `text/secondary` = `neutral-300`
- `text/tertiary` = `neutral-400`
- `text/inverse` = `neutral-950`
- `text/link` = `blue-500`

Bordures:
- `border/subtle` = `rgba(243,245,247,.08)`
- `border/default` = `rgba(243,245,247,.12)`
- `border/strong` = `rgba(243,245,247,.18)`
- `border/focus` = `blue-500`

Actions:
- `action/primary/bg` = `blue-600`
- `action/primary/bg-hover` = `blue-500`
- `action/primary/fg` = `neutral-100`
- `action/secondary/bg` = `rgba(243,245,247,.05)`
- `action/secondary/bg-hover` = `rgba(243,245,247,.08)`
- `action/secondary/fg` = `neutral-100`
- `action/tertiary/fg` = `neutral-300`
- `action/tertiary/fg-hover` = `neutral-100`

States:
- `state/info/bg` = `info-050`
- `state/info/fg` = `info-500`
- `state/success/bg` = `success-050`
- `state/success/fg` = `success-500`
- `state/warning/bg` = `warning-050`
- `state/warning/fg` = `warning-500`
- `state/danger/bg` = `danger-050`
- `state/danger/fg` = `danger-500`

## 4. Typographie

### 4.1 Familles

Familles retenues:
- `font/sans` = `Manrope`
- `font/display` = `Newsreader`
- `font/mono` = `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`

Rationale:
- `Manrope` porte l'UI de travail
- `Newsreader` reste reservee aux titres de synthese et aux moments premium
- la mono reste utilitaire pour run ids, chemins et donnees techniques

### 4.2 Echelle typographique

Display:
- `display/hero` = `42/48`, `700`, `Newsreader`
- `display/page` = `34/40`, `700`, `Newsreader`

Titres:
- `heading/h1` = `28/34`, `750`, `Manrope`
- `heading/h2` = `24/30`, `720`, `Manrope`
- `heading/h3` = `20/26`, `700`, `Manrope`
- `heading/h4` = `18/24`, `680`, `Manrope`

Texte:
- `body/lg` = `16/26`, `560`, `Manrope`
- `body/md` = `15/24`, `540`, `Manrope`
- `body/sm` = `14/22`, `540`, `Manrope`
- `body/xs` = `13/20`, `560`, `Manrope`

Labels:
- `label/lg` = `14/20`, `650`, `Manrope`
- `label/md` = `13/18`, `650`, `Manrope`
- `label/sm` = `12/16`, `680`, `Manrope`

Code:
- `code/md` = `13/19`, `560`, `Mono`
- `code/sm` = `12/16`, `560`, `Mono`

Rules:
- `Newsreader` seulement sur:
  - Accueil
  - Vue du run
  - historiques ou cartes de synthese majeures
- pas de `Newsreader` dans les tables, filtres, formulaires ou dialogues techniques

## 5. Echelle d'espacement

Base:
- systeme base 4

Scale:
- `space-1` = `4`
- `space-2` = `8`
- `space-3` = `12`
- `space-4` = `16`
- `space-5` = `20`
- `space-6` = `24`
- `space-7` = `28`
- `space-8` = `32`
- `space-10` = `40`
- `space-12` = `48`
- `space-16` = `64`

Usage:
- composants compacts: `8` a `16`
- cartes standard: `20` a `24`
- separations majeures: `32` a `48`

Regle:
- pas de spacing arbitraire hors echelle sauf necessite de calage 1 px / 2 px

## 6. Surfaces et elevation

Niveaux:
- `surface/base`
- `surface/default`
- `surface/subtle`
- `surface/elevated`
- `surface/overlay`

Elevation:
- `elevation/none` = `none`
- `elevation/soft` = `0 12px 32px rgba(0,0,0,.18)`
- `elevation/medium` = `0 18px 40px rgba(0,0,0,.22)`
- `elevation/overlay` = `0 24px 56px rgba(0,0,0,.28)`

Regles:
- utiliser surtout le contraste de surface
- utiliser les ombres avec parcimonie
- aucune carte standard ne doit ressembler a un floating card marketing

## 7. Rayons

Scale:
- `radius-xs` = `8`
- `radius-sm` = `10`
- `radius-md` = `12`
- `radius-lg` = `14`
- `radius-xl` = `18`
- `radius-pill` = `999`

Usage:
- checkboxes, petits badges: `8`
- boutons, inputs, selects: `10` ou `12`
- cartes standard: `14`
- cartes majeures de synthese: `18`

Regle:
- eviter les rayons trop mous

## 8. Bordures

Widths:
- `border-width/hairline` = `1`
- `border-width/strong` = `1.5`

Styles:
- `border/subtle`
- `border/default`
- `border/strong`

Regles:
- la majorite des composants restent en `1 px`
- monter en `1.5 px` seulement pour focus ou etat fort

## 9. Styles d'etat

Interaction:
- `state/hover/fill-weak` = `+3 a +4 points de luminance`
- `state/hover/fill-strong` = `+5 a +7 points de luminance`
- `state/pressed` = `-4 a -6 points de luminance`
- `state/focus/ring` = `0 0 0 2px rgba(111,168,255,.42)`
- `state/disabled/opacity` = `.46`
- `state/disabled/fg` = `neutral-500`

Selection:
- `state/selected/bg` = `blue-050`
- `state/selected/border` = `rgba(111,168,255,.30)`

Validation:
- info / success / warning / danger utilisent toujours:
  - une couleur de fond faible
  - une couleur de texte plus saturee
  - jamais un aplat brutal sur de grandes surfaces

## 10. Composants de base

### 10.1 Button

Variants:
- primary
- secondary
- tertiary
- danger
- quiet

Sizes:
- sm
- md
- lg

Rules:
- primary = accent froid, mat, dense
- secondary = ton sur ton, bord discret
- tertiary = sans surface lourde
- danger = reserve aux actions irreversibles

### 10.2 Checkbox

States:
- unchecked
- checked
- indeterminate
- disabled
- focus

Rules:
- toujours compacte
- coche simple
- utilisable en table sans bruit visuel

### 10.3 Input

Variants:
- default
- success
- warning
- danger
- disabled

Elements:
- label
- help
- placeholder
- value
- validation text

### 10.4 Select

Rules:
- meme shell que l'input
- menu de liste ton sur ton
- selected item visible sans saturation excessive

### 10.5 Badge

Variants:
- neutral
- info
- success
- warning
- danger
- confidence/high
- confidence/medium
- confidence/low

Sizes:
- sm
- md

### 10.6 Alert

Variants:
- info
- success
- warning
- danger

Structure:
- accent edge
- title
- body
- optional action

### 10.7 Card

Variants:
- section
- summary
- elevated
- compact

Slots:
- eyebrow
- title
- body
- actions
- footer

### 10.8 Page header

Structure:
- eyebrow optional
- title
- summary
- contextual metrics optional
- actions

### 10.9 Sidebar rail

Structure:
- brand block
- primary nav
- module nav
- utility nav
- utility actions

### 10.10 Right panel

Structure:
- context summary
- next steps
- detail blocks
- low-frequency actions

### 10.11 Data table shell

Elements:
- toolbar
- stats strip
- header row
- body rows
- inline edit cells
- row actions

## 11. Figma mapping recommandee

Pages Figma cibles:
1. Foundations
2. Components
3. Patterns
4. Screens

Dans `Foundations`:
- color styles / variables
- text styles
- spacing scale
- radii
- border styles
- elevation styles

Dans `Components`:
- button
- checkbox
- input
- select
- badge
- alert
- card
- page header
- sidebar rail
- right panel
- data table shell

## 12. Points encore a arbitrer

Arbitrages ouverts:
- poids exact des titres `Manrope` dans les vues denses
- niveau de presence de `Newsreader` sur `Historique`
- largeur cible du panneau droit persistant
- seuil de contraste des badges warning et danger
- niveau exact de compaction des lignes de table

Decisions deja fixees:
- pas de systeme flashy
- pas de gros glow
- pas de rayons trop mous
- pas de contraste brutal de type dashboard gamer
