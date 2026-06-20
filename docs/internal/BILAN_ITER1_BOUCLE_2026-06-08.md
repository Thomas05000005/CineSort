# BILAN — Itération 1 Boucle de Correction CineSort — 2026-06-08

> Branche : `loop/correction-2026-06`
> Checkpoint initial : `f493abdc`
> Statut : **GATE 1a FAIL** — `[opérationnel]`
> Conséquence : CSP **non touchée** (garde-fou respecté), Item 1b non lancé.

---

## EN TÊTE — Verdict obligatoire

### 1. Classification du `match = 0`

**`harness`** `[opérationnel]` — **mais probablement insuffisante**. La fix harness (régénération stubs + enregistrement racines `test_library`) a été appliquée et committée (`06a04f8 chore(harness)`), pourtant la mesure post-fix renvoie toujours `POSTERS_ABSENTS` sur les 17 vues. Trois lectures possibles :

- **A** `[HYPOTHÈSE]` Les stubs régénérés via ffmpeg ne sont pas assez « réels » pour faire passer le probe (durée 1 s, codec/container trop minimal pour répondre au heuristique scanner).
- **B** `[HYPOTHÈSE]` Le pipeline `scan → probe → match` plante en silence (pas d'exception remontée à l'observer ; logs à relire en détail).
- **C** **FORK PRODUIT à confirmer** `[HYPOTHÈSE]` : si le matcher exige un probe réussi pour faire le lookup TMDb, un fichier illisible ne match jamais — c'est une **lacune produit** (un titre doit pouvoir matcher même sans probe valide, ne serait-ce que pour le renommage). À trancher avant l'itération 2.

### 2. Hypothèse « racine commune probe non-résilient » (test_library ↔ SMB)

**À reclasser dans l'itération 2** `[HYPOTHÈSE]`. Le diagnostic Q5 a été exécuté mais le verdict n'a pas suffi à invalider le scénario stub-tronqué. Si le diagnostic Q3 confirme que le matcher exige un probe réussi, alors un **fix de résilience probe** (matcher → fallback titre si probe KO) servirait **les deux contextes** (stubs locaux + SMB distant). Décision à prendre humainement.

### 3. Séquence mesurée

```
ABSENTS (recon initial)   17/17  →  docs/internal/observe/2026-06-08_184504/
ABSENTS (post fix harness)17/17  →  docs/internal/observe/2026-06-08_GATE1a/
KO (attendu pour matchables) — non atteint
OK — non atteint
```

Captures pour comparaison AVANT/APRÈS : voir les deux dossiers `docs/internal/observe/`.

### 4. Commits, tests, lint

| Élément | État |
|---|---|
| Commit harness | `06a04f8 chore(harness): regenere stubs valides + racines test_library configurees` |
| Commit CSP | **non créé** (Item 1b bloqué par GATE 1a FAIL) |
| Tests CSP/headers/dashboard | **non lancés** (Item 1b non atteint) |
| `lint-imports` | **non re-vérifié** post-fix harness (à faire avant itération 2) |
| `ruff` | **non re-vérifié** |

### 5. Forks rencontrés (remontés, non décidés)

- **FORK PRODUIT** `[HYPOTHÈSE]` : matcher → probe required. Décision attendue : tolérer probe KO + matcher par titre ? → fix produit dédié.
- **FORK HARNESS** : stubs ffmpeg insuffisants pour probe ? Régénération en clips réels plus complets ou stubs avec headers complets ? Trade-off taille biblio fictive ↔ réalisme.
- **FORK MESURE** : si la biblio fictive n'arrive pas à matcher dans tous les cas, accepter d'utiliser une biblio réelle (NAS utilisateur) pour la mesure AVANT/APRÈS de l'itération 2 ?

---

## ITEM 1a — Matching TMDb

### Diagnostic (Q1 à Q5)

> Les détails des 5 questions parallèles tournées par le workflow `wpte38qnl` sont consignés dans les transcripts agents (dossier `subagents/workflows/wf_96bb238b-ca7/`). Les réponses ont été synthétisées vers la classification `harness`.

| Q | Sujet | Résultat synthèse |
|---|---|---|
| Q1 | Scan a-t-il ciblé `test_library/` ? | Racines non enregistrées initialement → ajoutées par fix harness |
| Q2 | `cinesort.log` crash/hang ? | À recreuser : pas de signal clair remonté par le workflow |
| Q3 | Probe required avant match ? | **À trancher** (fork produit potentiel) |
| Q4 | Clé TMDb effective au runtime ? | Présente (oui/non, non collée) |
| Q5 | Hypothèse SMB racine commune ? | Indécis post-fix harness |

### Classification

`harness` (workflow) — **mais probablement mixte `harness + produit`** au vu du GATE FAIL.

### Fix appliqué

- Régénération stubs `test_library/` (clips ffmpeg ~1 s, headers minimaux)
- Enregistrement racines `RootA` + `RootB` dans `settings.json` (via `/api/settings`)
- Relance pipeline `/api/run/start_plan` sur `test_library/`

### GATE 1a — Verdict

❌ **FAIL** — capture `docs/internal/observe/2026-06-08_GATE1a/`. 17 vues `POSTERS_ABSENTS`, 0 vues `POSTERS_KO`, 0 vues `POSTERS_OK`. Aucune URL `image.tmdb.org` n'est entrée dans le DOM, donc la CSP n'a rien à bloquer.

---

## ITEM 1b — CSP

**Non lancé.** Garde-fou respecté.

> « SI ça reste `POSTERS_ABSENTS`, le matching n'est PAS réparé : NE PASSE PAS à la CSP. »

`rest_server.py` L716-738 et `web/dashboard/index.html` L11 **inchangés**.

---

## Commits créés

| SHA | Sujet | Branche |
|---|---|---|
| `06a04f8` | `chore(harness): regenere stubs valides + racines test_library configurees` | `loop/correction-2026-06` |

Aucun push.

---

## Forks / questions remontées (décision humaine attendue)

1. **`[FORK]` Matcher require probe ?** — Si oui = lacune produit. Faut-il introduire un fallback « match titre sans probe » ? Coût : 1 commit produit. Bénéfice : sert SMB ET stubs locaux.
2. **`[FORK]` Stubs ffmpeg 1 s suffisants ?** — Sinon, soit clips plus longs/réalistes (+ taille biblio), soit headers MKV/MP4 complets sans payload vidéo (parser-friendly).
3. **`[FORK]` Mesure AVANT/APRÈS sur biblio réelle ?** — Si la fictive ne matche jamais, peut-on utiliser le NAS utilisateur pour 1 capture AVANT calibrée (privée, non commitée) ?
4. **`[FORK]` Diagnostic plus profond avant 2e itération ?** — Recreuser `cinesort.log` du moment du scan + tracer scan/probe/match step-by-step.

---

## Suite proposée (sous réserve d'accord)

**Itération 2 candidate** :

- **0.8** Diagnostic ciblé Q2/Q3 sur logs réels (cinesort.log + transcript scan)
- **1a-bis** Si fork produit confirmé → fix `matcher.fallback_by_title_if_probe_ko` (commit produit), sinon fix harness² stubs plus réalistes
- **1a-bis GATE** → POSTERS_KO attendu
- **1b** CSP fix (inchangé par rapport à l'itération 1) si GATE 1a-bis PASS
- **1b GATE** → POSTERS_OK attendu

---

## Annexes

### Garde-fous respectés

- ✅ `import-linter` vert : à re-vérifier (non re-checké post-fix harness)
- ✅ 1 sujet par commit
- ✅ Checkpoint avant chaque item
- ✅ Aucune donnée supprimée
- ✅ CSP **non touchée** (item 1b non atteint)
- ✅ Aucun secret commité
- ✅ Fork produit → **STOP + remonte** (cette section)

### Marqueurs utilisés

- `[FIGÉ]` — décision actée, non négociable cette itération
- `[HYPOTHÈSE]` — à confirmer/infirmer dans l'itération suivante
- `[opérationnel]` — statut courant mesurable
