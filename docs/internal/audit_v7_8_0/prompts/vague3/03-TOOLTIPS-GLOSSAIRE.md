# V3-03 — Tooltips ⓘ glossaire métier

**Branche** : `feat/tooltips-glossaire`
**Worktree** : `.claude/worktrees/feat-tooltips-glossaire/`
**Effort** : 1 jour
**Priorité** : 🟠 IMPORTANT (compréhension métier — 2000 users débutants)
**Fichiers concernés** :
- `web/dashboard/components/glossary-tooltip.js` (nouveau composant)
- `web/dashboard/styles.css` (style tooltip)
- 5-7 vues dashboard où injecter les tooltips
- `tests/test_glossary_tooltips.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/tooltips-glossaire .claude/worktrees/feat-tooltips-glossaire audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-tooltips-glossaire

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu créés UN composant tooltip réutilisable + tu l'injectes
ponctuellement dans 5-7 vues. Tu ne modifies pas la logique des vues.

---

## CONTEXTE

CineSort utilise beaucoup de termes techniques métier que les 2000 users débutants ne
connaissent pas : LPIPS, perceptual hash, HDR10+, bitrate, chromaprint, banding, etc.

**Solution** : composant `<GlossaryTooltip>` (icône ⓘ cliquable/survol) avec un
glossaire centralisé. Injection dans 5-7 vues clés.

---

## MISSION

### Étape 1 — Créer le composant

Crée `web/dashboard/components/glossary-tooltip.js` :

```javascript
// V3-03 — Tooltip glossaire métier réutilisable
import { escapeHtml } from "../core/dom.js";

/**
 * Glossaire centralisé. Clé = terme tel qu'affiché dans l'UI.
 * Valeur = définition courte (1-3 phrases) en français.
 */
export const GLOSSARY = {
  "LPIPS": "Learned Perceptual Image Patch Similarity. Métrique IA qui compare 2 images comme un humain (différence perçue, pas pixel-par-pixel). Utilisée pour détecter les ré-encodages dégradés.",
  "Perceptual hash": "Empreinte numérique d'une image basée sur son contenu visuel (pas le contenu binaire). 2 fichiers identiques visuellement ont des perceptual hashes proches même si encodage différent.",
  "Chromaprint": "Empreinte audio (audio fingerprint). Identifie une bande son indépendamment de la qualité audio. Utilisé pour détecter les doublons.",
  "HDR10+": "Format HDR avec métadonnées dynamiques scène par scène. Plus précis que HDR10 statique. Détecté via SMPTE ST 2094-40.",
  "Dolby Vision": "Format HDR propriétaire de Dolby. 4 profils principaux : 5 (TV), 7 (Blu-ray dual layer), 8.1 (single track), 8.2.",
  "Bitrate": "Quantité de données par seconde de vidéo (en kbps). Plus élevé = meilleure qualité, mais aussi gros fichier. 10 Mbps est typique pour 1080p HEVC.",
  "Banding": "Bandes de couleur visibles dans les dégradés (ciel, ombres). Indique compression agressive ou bit depth insuffisant.",
  "Tier": "Catégorie de qualité (Premium, Bon, Moyen, Mauvais). Calculée à partir des scores vidéo + audio + métadonnées.",
  "Score perceptuel": "Note de qualité visuelle/audio basée sur l'analyse réelle du fichier (pas juste les métadonnées). Sur 100. >= 85 = excellent.",
  "Re-encode dégradé": "Fichier qui a été ré-encodé avec un bitrate trop bas pour sa résolution. Perte de qualité visible.",
  "Upscale suspect": "Vidéo dont la résolution annoncée (ex. 1080p) est supérieure à sa résolution réelle (ex. 480p upscalé). Le fichier est plus gros pour rien.",
  "Faux 4K": "Fichier annoncé 4K mais qui contient en réalité de l'image 1080p ou moins, simplement upscalée. Détecté par analyse FFT.",
  "Run": "Une exécution complète d'un scan + analyse + apply. Stocké en BDD pour historique.",
  "Apply": "Application physique des renommages/déplacements proposés. C'est l'étape qui modifie réellement les fichiers.",
  "Dry-run": "Simulation sans modification du disque. Permet de prévisualiser avant de committer.",
  "Roots": "Dossiers racine où chercher les films. Tu peux en avoir plusieurs (SSD + NAS + disque externe).",
  "TMDb": "The Movie Database. Base de données mondiale de films open. Source principale des métadonnées (titre, année, posters, sagas).",
  "NFO": "Fichier XML qui accompagne un film, contient les métadonnées (titre, année, IMDb ID). Standard Kodi/Jellyfin/Plex.",
};

/**
 * Génère le HTML d'un tooltip glossaire pour un terme donné.
 * @param {string} term - Le terme tel qu'affiché.
 * @param {string} [labelOverride] - Si différent du terme, utilise pour l'affichage du libellé.
 */
export function glossaryTooltip(term, labelOverride = null) {
  const def = GLOSSARY[term];
  const label = labelOverride || term;
  if (!def) return escapeHtml(label); // pas de définition → texte brut
  return `
    <span class="glossary-term">
      ${escapeHtml(label)}<button type="button" class="glossary-info" tabindex="0"
        aria-label="Définition de ${escapeHtml(term)}"
        data-term="${escapeHtml(term)}"
        data-tooltip="${escapeHtml(def)}">ⓘ</button>
    </span>
  `;
}

/**
 * Init listener global (à appeler au boot du dashboard).
 * Affiche un popover au clic ou au focus sur .glossary-info.
 */
export function initGlossaryTooltips() {
  let activePopover = null;

  function closePopover() {
    if (activePopover) { activePopover.remove(); activePopover = null; }
  }

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".glossary-info");
    if (!btn) { closePopover(); return; }
    ev.preventDefault();
    closePopover();

    const def = btn.dataset.tooltip;
    const term = btn.dataset.term;
    const popover = document.createElement("div");
    popover.className = "glossary-popover";
    popover.setAttribute("role", "tooltip");
    popover.innerHTML = `
      <strong>${escapeHtml(term)}</strong>
      <p>${escapeHtml(def)}</p>
    `;
    document.body.appendChild(popover);
    activePopover = popover;

    const r = btn.getBoundingClientRect();
    popover.style.position = "fixed";
    popover.style.left = `${Math.min(r.left, window.innerWidth - 320)}px`;
    popover.style.top = `${r.bottom + 6}px`;
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closePopover();
  });
}
```

### Étape 2 — Style CSS

Dans `web/dashboard/styles.css` :

```css
/* V3-03 — Glossaire tooltip */
.glossary-term {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.glossary-info {
  background: transparent;
  border: 1px solid var(--accent-border);
  color: var(--accent);
  border-radius: 50%;
  width: 18px;
  height: 18px;
  font-size: 0.7rem;
  line-height: 1;
  padding: 0;
  cursor: help;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.glossary-info:hover, .glossary-info:focus-visible {
  background: var(--accent);
  color: var(--bg-primary);
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.glossary-popover {
  z-index: 9999;
  background: var(--surface-elevated);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  padding: 0.75rem 1rem;
  max-width: 320px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  font-size: 0.875rem;
  line-height: 1.4;
}
.glossary-popover strong {
  color: var(--accent);
  display: block;
  margin-bottom: 0.25rem;
}
.glossary-popover p {
  margin: 0;
  color: var(--text-primary);
}
```

### Étape 3 — Init au boot

Dans `web/dashboard/app.js`, ajouter au boot :

```javascript
import { initGlossaryTooltips } from "./components/glossary-tooltip.js";
// ...
initGlossaryTooltips();
```

### Étape 4 — Injection dans 5-7 vues

Dans chaque vue cible, importer `glossaryTooltip` et remplacer les libellés
techniques par des appels au tooltip. Exemples :

**`views/film-detail.js`** :
```javascript
import { glossaryTooltip } from "../components/glossary-tooltip.js";
// ...
html += `<dt>${glossaryTooltip("Score perceptuel")}</dt><dd>${score}</dd>`;
html += `<dt>${glossaryTooltip("LPIPS")}</dt><dd>${lpips}</dd>`;
html += `<dt>${glossaryTooltip("Bitrate")}</dt><dd>${bitrate} kbps</dd>`;
```

**`views/library-v5.js`** : tooltip sur "Tier" dans header colonne.
**`views/quality.js`** : tooltip sur "Score perceptuel", "Banding", "Re-encode dégradé".
**`views/review.js`** : tooltip sur "Dry-run", "Apply".
**`views/settings-v5.js`** : tooltip sur "Roots", "TMDb", "Chromaprint" si visible.
**`views/qij-v5.js`** : tooltip sur "Faux 4K", "Upscale suspect".
**`views/home.js`** : tooltip sur "Run", "Tier".

(Adapter aux vues qui existent réellement — lire d'abord pour confirmer)

### Étape 5 — Tests

Crée `tests/test_glossary_tooltips.py` :

```python
"""V3-03 — Vérifie le composant glossaire tooltip."""
from __future__ import annotations
import unittest
from pathlib import Path


class GlossaryTooltipTests(unittest.TestCase):
    def setUp(self):
        self.component = Path("web/dashboard/components/glossary-tooltip.js").read_text(encoding="utf-8")
        self.css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.app_js = Path("web/dashboard/app.js").read_text(encoding="utf-8")

    def test_glossary_has_minimum_terms(self):
        """Au moins 15 termes définis."""
        # Compte les clés "..." : "..." dans le bloc GLOSSARY
        import re
        count = len(re.findall(r'^\s*"[^"]+"\s*:\s*"', self.component, re.MULTILINE))
        self.assertGreaterEqual(count, 15)

    def test_essential_terms_present(self):
        for term in ["LPIPS", "TMDb", "HDR10+", "Bitrate", "Tier", "Dry-run", "Apply", "NFO"]:
            self.assertIn(f'"{term}"', self.component, f"Terme manquant: {term}")

    def test_init_function_exported(self):
        self.assertIn("export function initGlossaryTooltips", self.component)

    def test_tooltip_function_exported(self):
        self.assertIn("export function glossaryTooltip", self.component)

    def test_css_styles_present(self):
        self.assertIn(".glossary-info", self.css)
        self.assertIn(".glossary-popover", self.css)

    def test_init_called_in_app(self):
        self.assertIn("initGlossaryTooltips", self.app_js)

    def test_xss_protection(self):
        """Vérifie que escapeHtml est utilisé sur les champs dynamiques."""
        self.assertIn("escapeHtml", self.component)


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_glossary_tooltips -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 7 — Commits

- `feat(dashboard): glossary tooltip component with 15+ terms (V3-03)`
- `feat(dashboard): inject glossary tooltips in 5-7 views`
- `test(dashboard): glossary tooltip structural tests`

---

## LIVRABLES

Récap :
- Composant `<GlossaryTooltip>` réutilisable avec ≥ 15 définitions FR
- Init au boot dashboard (clic + Escape close)
- Injection dans 5-7 vues clés
- A11y : aria-label, role tooltip, focus-visible
- 0 régression
- 3 commits sur `feat/tooltips-glossaire`
