# CineSort Design System v5

**Version** : v5.0 (v7.6.0)
**Date** : 2026-04-23
**Philosophie** : **data-first + 4 ambiances**

---

## 1. Principes

### 1.1 Data-first
Les couleurs metier (tier colors, severities) sont **invariantes** dans tous les themes.
L'UI doit **traduire l'information avant de decorer**. Un film Gold reste vert dans les 4 themes.

### 1.2 Profondeur par couches
3 niveaux de surface + 4 niveaux d'elevation. Pas de flat design mou.

### 1.3 Motion subtil mais present
Chaque interaction a un feedback visuel (hover lift, focus glow, click compress, load stagger). Respect `prefers-reduced-motion`.

### 1.4 Density configurable
L'utilisateur choisit compact / comfortable / spacious via un setting Apparence.

---

## 2. Palette

### 2.1 Tier colors (invariables)

```css
--tier-platinum-solid:  #FFD700;  /* or vif */
--tier-platinum-glow:   rgba(255, 215, 0, 0.25);
--tier-platinum-bg:     rgba(255, 215, 0, 0.08);

--tier-gold-solid:      #22C55E;  /* vert validation */
--tier-gold-glow:       rgba(34, 197, 94, 0.25);
--tier-gold-bg:         rgba(34, 197, 94, 0.08);

--tier-silver-solid:    #3B82F6;  /* bleu neutre positif */
--tier-silver-glow:     rgba(59, 130, 246, 0.25);
--tier-silver-bg:       rgba(59, 130, 246, 0.08);

--tier-bronze-solid:    #F59E0B;  /* orange warning doux */
--tier-bronze-glow:     rgba(245, 158, 11, 0.25);
--tier-bronze-bg:       rgba(245, 158, 11, 0.08);

--tier-reject-solid:    #EF4444;  /* rouge action */
--tier-reject-glow:     rgba(239, 68, 68, 0.25);
--tier-reject-bg:       rgba(239, 68, 68, 0.08);

--tier-unknown-solid:   #6B7280;  /* gris pour rows pre-v7.5 */
--tier-unknown-bg:      rgba(107, 114, 128, 0.08);
```

### 2.2 Severity (warnings, toasts)

```css
--sev-info-solid:     #60A5FA;
--sev-success-solid:  #34D399;
--sev-warning-solid:  #FBBF24;
--sev-danger-solid:   #F87171;
--sev-critical-solid: #DC2626;

(toutes avec variantes -glow 25% et -bg 10%)
```

### 2.3 Themes (4 ambiances, touchent uniquement les surfaces)

#### Theme **Studio** (technique, default)
```css
--bg:         #06090F;
--surface-1:  rgba(255, 255, 255, 0.035);
--surface-2:  rgba(255, 255, 255, 0.055);
--border-1:   rgba(255, 255, 255, 0.08);
--border-2:   rgba(96, 165, 250, 0.25);  /* accent */
--accent:     #60A5FA;
--atmosphere: subtle scan lines (horizontal 1px rgba 0.02)
```

#### Theme **Cinema** (velours rouge/or)
```css
--bg:         #0C0708;
--surface-1:  rgba(255, 214, 170, 0.025);
--surface-2:  rgba(255, 214, 170, 0.05);
--border-1:   rgba(220, 38, 38, 0.10);
--border-2:   rgba(251, 191, 36, 0.20);
--accent:     #DC2626;
--atmosphere: noise texture grain pellicule (opacity 0.015)
```

#### Theme **Luxe** (or mat noir)
```css
--bg:         #0A0806;
--surface-1:  rgba(251, 191, 36, 0.03);
--surface-2:  rgba(251, 191, 36, 0.055);
--border-1:   rgba(251, 191, 36, 0.12);
--border-2:   rgba(251, 191, 36, 0.28);
--accent:     #FBBF24;
--atmosphere: subtle shimmer dore (animation 8s ease-in-out)
```

#### Theme **Neon** (cyber violet/cyan)
```css
--bg:         #050714;
--surface-1:  rgba(168, 85, 247, 0.03);
--surface-2:  rgba(6, 182, 212, 0.05);
--border-1:   rgba(168, 85, 247, 0.15);
--border-2:   rgba(6, 182, 212, 0.30);
--accent:     #A855F7;
--atmosphere: border glow rotation 4s linear infinite (subtil)
```

### 2.4 Texte
```css
--text-primary:    #E8ECF1;
--text-secondary:  #8B97AB;
--text-muted:      #6B7A95;
--text-disabled:   #4B5563;

(theme clair : invert via media prefers-color-scheme si active)
```

---

## 3. Typography

```css
--font-family: 'Manrope', system-ui, -apple-system, sans-serif;

--fs-2xs: 10px;
--fs-xs:  11px;
--fs-sm:  13px;
--fs-base:14px;
--fs-md:  15px;
--fs-lg:  18px;
--fs-xl:  22px;
--fs-2xl: 28px;
--fs-3xl: 36px;  /* hero scores, titres film */

--fw-regular:  400;
--fw-medium:   500;
--fw-semibold: 600;
--fw-bold:     700;
--fw-black:    800;

--lh-tight:  1.1;   /* titres */
--lh-normal: 1.5;   /* body */
--lh-relax:  1.7;   /* descriptions longues */

--tabular-nums: font-variant-numeric: tabular-nums;  /* scores, timestamps */
```

---

## 4. Spacing (grille 4px)

```css
--sp-0: 0;
--sp-1: 4px;
--sp-2: 8px;
--sp-3: 12px;
--sp-4: 16px;
--sp-5: 20px;
--sp-6: 24px;
--sp-7: 32px;
--sp-8: 40px;
--sp-9: 48px;
--sp-10: 64px;
--sp-11: 96px;
```

---

## 5. Radius

```css
--radius-sm:    4px;
--radius-md:    8px;
--radius-lg:    12px;
--radius-xl:    16px;
--radius-pill:  9999px;
```

---

## 6. Shadows (4 niveaux + tier glows)

```css
--shadow-1: 0 1px 2px rgba(0,0,0,0.20);                       /* subtle card */
--shadow-2: 0 4px 12px rgba(0,0,0,0.25);                      /* hover lift */
--shadow-3: 0 12px 32px rgba(0,0,0,0.35);                     /* modal */
--shadow-4: 0 24px 64px rgba(0,0,0,0.45);                     /* overlay heavy */

--glow-accent:   0 0 16px var(--accent-glow);
--glow-tier:     0 0 12px var(--tier-X-glow);  /* X = tier de la card */

--inset-1: inset 0 1px 0 rgba(255,255,255,0.04);              /* top highlight card */
```

---

## 7. Motion

```css
--ease-out:    cubic-bezier(0.16, 1, 0.3, 1);     /* rebond leger sortie */
--ease-in:     cubic-bezier(0.7, 0, 0.84, 0);
--ease-in-out: cubic-bezier(0.76, 0, 0.24, 1);
--ease-linear: linear;

--dur-quick:   120ms;   /* hovers, buttons */
--dur-base:    240ms;   /* transitions vues, toast */
--dur-smooth:  400ms;   /* accordeon, drawer */
--dur-complex: 600ms;   /* score circle stroke, large layouts */
--dur-slow:    1200ms;  /* score circle drawer complet */

--stagger-base: 60ms;
--stagger-slow: 100ms;

/* Reduced motion fallback */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 8. Composants (specs minimales)

### 8.1 Button
```
Variants : primary | secondary | ghost | danger
Sizes    : sm (28px) | md (36px) | lg (44px)
States   : default | hover (translateY -1px + shadow-2) | active (scale 0.97)
          | focus (2px outline --accent) | disabled (opacity 0.4 cursor not-allowed)

Primary : gradient linear (--accent -> accent-hover) + shadow-1 + border-1
Ghost   : transparent bg + border-1 + hover:surface-1
Danger  : bg --tier-reject + text white
```

### 8.2 Card
```
default : bg surface-1 + border border-1 + radius-lg + inset-1 + shadow-1
hover   : translateY(-2px) + shadow-2 (240ms ease-out)
focus   : border --accent-border (2px)

.card--tier-[X] : border-left 3px var(--tier-X-solid) + tier-X-bg overlay faible
```

### 8.3 Badge
```
Size   : sm (20px) | md (24px)
Tones  : tier-[X] | severity-[X] | neutral
Shape  : pill (radius-pill) | rect (radius-sm)

.badge--tier-[X] : bg tier-X-bg + color tier-X-solid + border 1px tier-X-glow
```

### 8.4 Score Circle
```
Sizes : xs (48px) | sm (80px) | md (120px) | lg (160px) | hero (200px)
Props : score (0-100) | tier | animated (bool, default true)

Center text : score (tabular-nums) + tier label (uppercase, letterspace)
Stroke      : 10px (md+), 8px (sm), 6px (xs), stroke-linecap round
Animation   : stroke-dashoffset 1200ms cubic-bezier(0.16,1,0.3,1)
Glow        : filter drop-shadow(0 0 8px tier-X-glow) si hovered
```

### 8.5 Gauge (jauge horizontale)
```
Layout : [label 120px] [track flex] [value 50px]
Track  : height 10px, bg rgba(255,255,255,0.05), radius-pill
Fill   : gradient linear tier-X-solid -> tier-X (lighter 20%)
Anim   : width 1000ms ease-out, stagger 100ms par gauge
```

### 8.6 Accordion
```
Item   : .card avec header cliquable + body collapsible
Header : padding sp-3, chevron rotate 90deg transition 240ms
Body   : max-height 0 -> 800px transition 400ms ease-in-out
         overflow hidden, padding sp-4 quand expanded
Focus  : visible, keyboard accessible (Enter/Space)
```

### 8.7 Table
```
Header : sticky top, bg surface-2, border-bottom border-1, font-semibold
Rows   : height 48px default, 40px compact, 56px spacious
         hover: bg surface-1 (120ms) + border-left 3px --accent
         stripe: nth-child even bg rgba(255,255,255,0.012)
Cell   : padding sp-2 sp-3, border-bottom border-1 faint
Actions: hidden by default, visible on hover (fade 120ms)
Sort   : chevron up/down dans header cliquable
```

### 8.8 Modal
```
Overlay : bg rgba(0,0,0,0.65) + backdrop-filter blur(8px) + fade 240ms
Card    : surface-1 + radius-xl + shadow-4 + max-width selon size (sm=400, md=600, lg=800, xl=1000)
Entry   : scale(0.96) + opacity 0 -> scale(1) + opacity 1, 240ms ease-out
Close   : Escape, click overlay, button top-right
Focus   : trap dans la modale, return focus on close
```

### 8.9 Toast
```
Position : top-right (desktop), top-full-width (mobile)
Width    : 360px fixe desktop
Entry    : translateX(110%) -> 0, 300ms ease-out
Exit     : opacity 1 -> 0 + translateY(-4px), 200ms
Duration : 4s default, 0 si user-dismissible
Stack    : max 3 visible, queue les suivants
Severity : border-left 4px severity-X-solid, icon severity-X
```

### 8.10 Sidebar (navigation)
```
Width    : 240px default, 64px collapsed
Bg       : surface-1 + backdrop-filter blur + border-right border-1
Items    : 44px height, radius-md, icon 20px + label
         hover: bg surface-2
         active: bg accent-soft + border-left 2px accent + accent color
Collapse : toggle button bottom, transition 240ms
Mobile   : off-canvas drawer < 768px, bottom-tabs alternative
```

### 8.11 Command Palette
```
Modal-like plein ecran (backdrop-filter blur(16px))
Search input : 48px height, radius-pill, autofocus
Results : virtualised list, max 8 per category, categories stacked
         row: icon + label + subtitle + shortcut hint + category tag
         selected: bg accent-soft + arrow right visible
Entry  : translateY(-10px) + opacity 0 -> 0 + 1, 200ms
```

---

## 9. Icons

**Systeme** : Lucide (inline SVG stroke-width 1.75), deja partiel dans v7.5.
**Taille** : 16px (inline), 20px (buttons), 24px (navigation), 32px (hero), 48px (empty state).
**Stroke color** : currentColor (heritage).

---

## 10. Exemples d'applications

### 10.1 Badge tier
```html
<span class="badge badge--tier-platinum">Platinum</span>
```
```css
.badge { padding: 2px 10px; radius: pill; font: 600 11px 'Manrope'; letter-spacing: 0.04em; }
.badge--tier-platinum {
  background: var(--tier-platinum-bg);
  color: var(--tier-platinum-solid);
  border: 1px solid var(--tier-platinum-glow);
}
```

### 10.2 Card film (Biblio table row)
```css
tr.row-film {
  background: var(--surface-1);
  border-left: 3px solid var(--tier-X-solid);  /* X dynamic */
  transition: all var(--dur-quick) var(--ease-out);
}
tr.row-film:hover {
  transform: translateY(-1px);
  background: var(--surface-2);
  box-shadow: var(--shadow-2);
}
```

### 10.3 KPI card avec stagger
```css
.kpi-grid { gap: var(--sp-4); }
.kpi-card {
  background: var(--surface-1);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
  opacity: 0;
  animation: kpiFadeIn var(--dur-base) var(--ease-out) forwards;
  animation-delay: calc(var(--order) * var(--stagger-base));
}
@keyframes kpiFadeIn {
  to { opacity: 1; transform: translateY(0); }
  from { opacity: 0; transform: translateY(8px); }
}
```

---

## 11. Refactor strategy

**Fichiers v5 a creer** :
```
web/shared/tokens.css          <- palette + typography + spacing + radius + motion
web/shared/themes.css          <- les 4 themes (Studio/Cinema/Luxe/Neon)
web/shared/components.css      <- specs buttons, cards, badges, tables, modals
web/shared/utilities.css       <- layout, text, spacing utilities
web/shared/animations.css      <- @keyframes, transition presets
```

**A migrer progressivement** :
- `web/styles.css` (2098L) + `web/themes.css` (953L) -> split en shared/ + desktop-specific
- `web/dashboard/styles.css` (1733L) -> consomme shared/, ajoute overrides responsive

**Compatibility layer** :
- Conserver les anciennes classes pendant la transition (ex: `.badge--perceptual-premium` -> alias de `.badge--tier-unknown`)
- Supprimer apres validation visuelle
