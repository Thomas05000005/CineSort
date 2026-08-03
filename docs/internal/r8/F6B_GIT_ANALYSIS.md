# F6-b Phase 1 — Analyse git (fuite de poids + audit secrets + état public)

> **LECTURE SEULE.** Aucune réécriture d'historique, aucun push, aucun commit (sauf ce rapport).
> Date : 2026-06-19. Branche `loop/correction-2026-06`. Checkpoint `f493abdc` intact.
> Objectif : donner à Thomas les faits pour décider de la stratégie de nettoyage + push public sûr.
> ⚠️ Aucun secret n'est affiché en clair (fichier + type + commit uniquement).

---

## Résumé exécutif

| Axe | Verdict |
|---|---|
| **Poids** | `.git` pack = **325 Mo** (le vrai coût clone/push), working tree ~1,2 Go. Bloat **multi-source** et **100 % régénérable** : observe (771 Mo tree / ~118 Mo blobs), dist_backup (179 Mo, EXE+DLL), EXE/pkg historiques dist/build (~50 Mo, déjà hors tree), test_library (224 Mo tree / ~11 Mo dédupé). Les plus gros blobs ne sont **pas** observe mais des **EXE/DLL buildés**. |
| **Secrets** | **0 secret réel** exposable par un push. network.json = `{url,status,method,resource_type}` seulement (0 en-tête, 0 token). summary.json « Bearer » = nom de fonction `_safeBearer` dans un log console « token absent ». `settings.json` réel **jamais tracké**. Seul `settings.json.example` contient un `rest_api_token` = **placeholder** (`^[A-Z_]+$`, mots instructionnels). |
| **Public** | remote = **github.com/Thomas05000005/CineSort** (PUBLIC). `loop/correction-2026-06` = **424 commits devant `origin/main`**, **0 derrière**, descente **linéaire** depuis le tip public `f502570` (2026-05-24, ~v1.5.1). Pas de divergence à réconcilier. |
| **.gitignore** | `dist/`, `build/`, `__pycache__/` ignorés ✓ ; **`docs/internal/observe`, `FAIL_*`, `test_library`, `dist_backup_*` NON ignorés** ✗ (prévention à ajouter). |

---

## AXE 1 — La fuite de poids

### 1.1 Contenu de `docs/internal/observe`
- **1608 fichiers trackés** : 1062 `.json`, 516 `.png`, 30 `.txt`. Working tree = **771 Mo**.
- Tous dans des sous-dossiers datés d'instrumentation `observe.py` : `2026-06-08_ITER*`, `2026-06-09_ITER15_*`, `GATE1a`, `FRESHNESS_REMEASURE`… (captures de runs).
- Plus gros sous-dossiers : ITER10_LISIBILITE 69 Mo, ITER3_GATE1a 67 Mo, ITER8B_FINAL 52 Mo, etc.

### 1.2 Ancienneté dans l'historique
- **17 commits** touchent `docs/internal/observe`, sur **2026-06-08 → 2026-06-10** (3 jours de la boucle de correction).
- Donc tout est postérieur au tip public `f502570` (2026-05-24) → **un push exposerait tout ce poids**.

### 1.3 Top 20 des plus gros blobs de l'historique (déduplifiés)
| Taille | Chemin | Tracké ? |
|---|---|---|
| 53,7 Mo | `dist_backup_AVANT_REBUILD_20260605/CineSort.exe` | OUI |
| 19,5 Mo | `dist_backup_…/numpy.libs/libscipy_openblas64_…dll` | OUI |
| 16,0 Mo | `dist_backup_…/onnxruntime/capi/onnxruntime.dll` | OUI |
| 13,4 Mo | `dist/TriFilmsApp.exe` | non (en historique) |
| 13,1 Mo | `build/TriFilmsApp/TriFilmsApp.pkg` | non (en historique) |
| 11,7 Mo ×3 | `build/TriFilmsApp_v6_{2,3,4}/…pkg` | non (en historique) |
| 11,2 Mo ×~12 | `test_library/RootA|RootB/…` (médias synthétiques) | OUI (27 fichiers) |

> **Constat clé** : les plus gros objets ne sont **pas** les artefacts observe (json/png, individuellement petits) mais des **binaires buildés** — l'EXE de sauvegarde 53,7 Mo + DLL numpy/onnxruntime, et les vieux EXE/pkg `TriFilmsApp` (ancien nom du projet) encore dans l'historique bien que retirés du tree.

### 1.4 Régénérable vs unique — **tout est régénérable**
| Catégorie | Poids | Statut | Régénérable ? |
|---|---|---|---|
| `docs/internal/observe/*` | 771 Mo tree / ~118 Mo blobs (476 uniques) | tracké | **OUI** — captures `observe.py`, recréables à la demande |
| `dist_backup_AVANT_REBUILD_20260605/*` | 179 Mo (252 fichiers) | tracké | **OUI** — sauvegarde d'un build EXE (rebuild via PyInstaller) |
| `dist/`, `build/` EXE/pkg historiques | ~50 Mo | hors tree, **en historique** | **OUI** — artefacts PyInstaller |
| `test_library/*` | 224 Mo tree / ~11 Mo dédupé | tracké (27 fichiers) | **OUI** — médias de test synthétiques (1 vidéo 11,2 Mo copiée) |

**Aucune donnée unique** : pas de source, pas de DB de prod, pas de média réel. 0 perte si purgé.
⚠️ `dist_backup_AVANT_REBUILD` a été introduit par le commit **`f493abd`** — c.-à-d. **le checkpoint `f493abdc` lui-même** (« checkpoint: working tree avant boucle correction 2026-06-08 »).

---

## AXE 2 — Audit secrets de l'historique (les 424 commits qu'un push exposerait)

> ⚠️ Aucune valeur de secret affichée ci-dessous. Fichier + type + verdict seulement.

### 2.1 Artefacts observe — la crainte « network.json = Authorization: Bearer » est **RÉFUTÉE**
- **0** fichier observe contient `Authorization`. **0** network.json contient `token` (0/510) ou `headers`.
- Échantillon network.json : capture seulement `{ "url", "status", "method", "resource_type" }`. **Aucun en-tête de requête, aucun token.**
- Les 19 fichiers observe avec « Bearer » sont tous des `summary.json` où « Bearer » = nom de fonction `_safeBearer` dans un **log console capturé** : `[dash-api] _safeBearer: token absent ou vide` → les runs observe tournaient **sans token** (état non authentifié).

### 2.2 Secrets dans l'historique
- `settings.json` (le vrai, qui stocke le `rest_api_token` en clair d'après la mémoire projet) : **jamais tracké** — 0 occurrence dans tout l'historique (`git log --all`).
- Seuls blobs `settings*.json` en historique = **`settings.json.example`** (template, dé-ignoré exprès via `!settings.json.example`). Son `rest_api_token` = **PLACEHOLDER** : valeur `^[A-Z_]+$` (majuscules+underscores) avec mots instructionnels (GENER…) → instruction « génère ton token », **pas un secret**.
- Patterns génériques (`api_key`, `password`, `secret`, `rest_api_token`) trouvés dans 12–65 fichiers : ce sont des **noms de clés/variables dans le CODE** et des exemples docs, **pas des valeurs**. `BEGIN … PRIVATE KEY` : **0**.

**Verdict Axe 2 : 0 secret réel exposable par un push.** (Le token REST réel n'a jamais quitté `settings.json`, non tracké.)

### 2.3 État `.gitignore` (prévention)
| Motif | Ignoré ? |
|---|---|
| `__pycache__/`, `dist/`, `build/` | ✓ OUI |
| `settings.json` (via pattern + `!settings.json.example`) | ✓ OUI (le vrai est ignoré, l'exemple dé-ignoré) |
| `docs/internal/observe` | ✗ **NON** |
| `FAIL_*` (captures Playwright d'échec) | ✗ **NON** |
| `test_library` | ✗ **NON** |
| `dist_backup_*` | ✗ **NON** (≠ `dist/`) |

---

## AXE 3 — État du dépôt vs public

- **Remote** : `origin = https://github.com/Thomas05000005/CineSort.git` — dépôt **PUBLIC**. `origin/HEAD → origin/main`.
- **Écart** : `loop/correction-2026-06` = **424 commits devant `origin/main`**, **0 derrière**.
- **Tip public connu** : `f502570` « fix(v151): splash message honnete… (#402) », **2026-05-24** (~v1.5.1 ; dernier fetch 2026-05-25). Les refs locales peuvent être légèrement périmées (pas de fetch fait ici, lecture seule).
- **Topologie** : `merge-base(HEAD, origin/main) = f502570` = **le tip public lui-même** → `loop/correction-2026-06` est une **continuation LINÉAIRE** de `origin/main` (aucune divergence). `main` local == `origin/main`. Les 424 commits = boucle d'audit + R6 + R7 + R8 (F2→F6), tous postérieurs au 2026-05-24, et **contiennent le bloat** (observe + dist_backup du 2026-06-08).
- Autres branches locales nombreuses (work-current, master, main-public, fix/*, feat/*) — non analysées (hors périmètre ; le push concerne loop→main).

---

## OPTIONS DE NETTOYAGE (exposées, aucune exécutée)

> Rappel : `f493abdc` (le checkpoint) **introduit lui-même** `dist_backup`. Toute purge de ce blob de l'historique **réécrit** `f493abdc` → incompatible avec « checkpoint intact ». À arbitrer.

### (a) `git rm --cached` + `.gitignore` (sortir du suivi FUTUR)
- **Règle** : retire observe/dist_backup/test_library du tracking + les gitignore. Les nouveaux commits n'ont plus ces fichiers.
- **Ne règle PAS** : l'historique garde tout le poids (325 Mo) → un clone/push reste lourd.
- **Risque** : faible. **Réversible** (un `git rm --cached` est un commit normal). Checkpoint intact.
- **Quand** : si on accepte un dépôt public lourd mais qui n'empire plus. Étape minimale de prévention, à faire dans tous les cas.

### (b) Réécriture d'historique (`git filter-repo` / BFG) — purge réelle des gros blobs
- **Règle** : supprime observe + dist_backup + EXE/pkg historiques de **tous** les commits → pack ~325 Mo → estimé **~50–80 Mo**.
- **Risque** : **ÉLEVÉ**. Réécrit **tous** les SHA (dont `f493abdc` et les 424 commits) → **force-push obligatoire** → **IRRÉVERSIBLE** sur un dépôt public ; casse tout clone/fork/PR existant ; invalide les tags. **Incompatible avec « checkpoint f493abdc intact »** tant qu'on n'a pas redéfini ce qu'« intact » signifie après réécriture.
- **Réversibilité** : nulle une fois force-pushé (sauf backup du `.git` avant — **à faire impérativement**).
- **Quand** : si un dépôt public léger est requis ET Thomas accepte la réécriture + le force-push + un backup préalable.

### (c) Nouveau départ propre (squash / nouveau dépôt)
- **Règle** : créer une nouvelle branche/dépôt avec un seul commit (ou quelques-uns) = état actuel **sans** les artefacts, repartant de `f502570`. Pousser ça comme nouvelle base.
- **Risque** : MOYEN. On **perd l'historique détaillé** des 424 commits (différentiels R8, messages) — or cet historique est une valeur (traçabilité des fixes). Pas de force-push si nouvelle branche, mais l'historique public diverge.
- **Réversibilité** : l'ancien historique reste en local/backup. **Quand** : si l'historique granulaire n'a pas de valeur publique.

### (d) Garder l'historique en privé + publier un état propre ailleurs
- **Règle** : laisser `loop/correction-2026-06` (avec son historique + bloat) en **local/privé** ; publier sur le dépôt public un **export propre** (option c) ou une branche release nettoyée. Le public ne voit jamais le bloat ni l'historique brut.
- **Risque** : FAIBLE. Aucune réécriture du local, aucun force-push. **Réversible** (le local reste maître).
- **Quand** : recommandable si l'objectif est « publier proprement v1.x » sans imposer une réécriture risquée au dépôt existant. Combinable avec (a) pour la prévention locale.

### Recommandation neutre (décision = Thomas)
- **(a)** est à faire **dans tous les cas** (prévention : gitignore observe/dist_backup/test_library/FAIL_*).
- Pour le poids public : **(d)** ou **(c)** évitent le force-push risqué de **(b)**. **(b)** n'est justifié que si le dépôt public **existant** doit absolument devenir léger ET avec backup `.git` préalable + acceptation de l'irréversibilité.
- Le push lui-même est **sûr côté secrets** (Axe 2 = 0 fuite) — le seul enjeu est le **poids**, pas la confidentialité.

---

## Clôture
Analyse terminée, **lecture seule, aucune réécriture**. Décision de stratégie en attente de Thomas.
