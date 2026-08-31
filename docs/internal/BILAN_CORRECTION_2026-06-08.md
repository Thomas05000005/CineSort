# BILAN CORRECTION 2026-06-08 (branche loop/correction-2026-06)

Bilan de la boucle de correction post-iter3. Ecriture au fur et a mesure (anti-interruption).
Marqueurs: FIGE / HYPOTHESE / OPERATIONNEL.

---

## 1. Etape 1a — Verification fraicheur du build EXE vs commit fix ii.b [OPERATIONNEL]

### Hypothese investiguee
H1: L'EXE dist/CineSort.exe est anterieur au commit fix ii.b (7df3af3e) et donc ne contient PAS la correction "restaurer enrichissement TMDb dans start_plan".

### Mesures (FIGE)

| Element | Valeur |
|---|---|
| Chemin EXE | `C:\Users\<utilisateur>\projects\CineSort\dist\CineSort.exe` |
| EXE LastWriteTime | **2026-06-08 11:56:47** (heure locale, TZ +0200) |
| Taille EXE | 59 613 955 octets (~56,9 MiB) |
| Commit fix ii.b | `7df3af3e3c384bb82233b43b2242af37e3298d36` |
| Message commit | `fix(plan): ii.b - restaurer enrichissement TMDb dans start_plan` |
| Date commit (author/committer) | **2026-06-08 23:22:52 +0200** |

Commandes utilisees:
- `ls -la C:/Users/<utilisateur>/projects/CineSort/dist/CineSort.exe`
- `git log --format="%ai %H %s" -1 7df3af3e`

### Comparaison et calcul d'ecart

- Commit fix ii.b: `2026-06-08 23:22:52 +0200`
- Build EXE:      `2026-06-08 11:56:47 +0200` (LastWriteTime, meme TZ presumee)
- Ecart: 23:22:52 - 11:56:47 = **11 h 26 min 5 s** = environ **686 minutes**
- L'EXE precede le commit de fix de ~11h26 le meme jour.

### Conclusion (FIGE)

- **H1 CONFIRMEE**: L'EXE actuel est anterieur de ~686 minutes au commit 7df3af3e (fix ii.b).
- L'EXE ne peut donc PAS contenir le fix de restauration de l'enrichissement TMDb dans `start_plan`.
- Tout test runtime via `dist/CineSort.exe` reflete l'etat PRE-fix ii.b et ne valide pas la correction iter3 sur l'enrichissement TMDb.

### Implications operationnelles (OPERATIONNEL)

1. Rebuilder `dist/CineSort.exe` depuis `loop/correction-2026-06` (HEAD inclut 7df3af3e) avant tout smoke runtime devant valider ii.b.
2. Toute observation actuelle de non-enrichissement TMDb via l'EXE existant doit etre re-qualifiee: probable EXE-perime, pas regression code.
3. Conformement aux memoires: AUCUN FIX SOURCE PRODUIT - HARNESS/OUTILLAGE SEUL. Le rebuild EXE est de la mise a niveau outillage / artefact de test, pas un changement source.

### Lien transverse

- BILAN_ITER3_2026-06-08.md L482-483 mentionnait deja explicitement que l'EXE de 11:56:47 etait PRE-fix iter3 — cette section 1a le confirme formellement et chiffre l'ecart.

---

## 1b. Etape 1b — Mode de lancement par observe.py [OPERATIONNEL]

### Hypothese investiguee
Si `scripts/observe.py` lance prioritairement `dist/CineSort.exe`, l'observation tourne sur le binaire PERIME (cf. section 1a) -> court-circuit du fix ii.b confirme (H1 confirme aussi cote outillage). Si elle lance `python app.py`, le source courant (HEAD = fix ii.b) est utilise direct -> H1 elimine cote outillage.

### Mesures (FIGE) — extraits observe.py

| Element | Valeur (chemin/ligne) |
|---|---|
| Cible EXE constante | `DIST_EXE = PROJECT_ROOT / "dist" / "CineSort.exe"` (L53) |
| Cible source constante | `APP_PY = PROJECT_ROOT / "app.py"` (L54) |
| Choix runtime | `_detect_app_command(prefer_exe)` (L128-135) |
| Branche EXE | `if prefer_exe and DIST_EXE.is_file(): return ([str(DIST_EXE)], "exe")` (L133-134) |
| Branche dev (fallback) | `return ([sys.executable, str(APP_PY), "--dev"], "dev")` (L135) |
| Defaut CLI | `prefer_exe=not args.prefer_dev` (L789) -> `prefer_exe=True` par defaut |
| Flag override | `--prefer-dev` (L735-738) force le mode `dev` meme si EXE present |
| Env injecte | `CINESORT_E2E=1`, `CINESORT_CDP_PORT=<port>`, `LOCALAPPDATA=<out_dir/_state>` (L197-201) |
| Args specifiques | aucun arg supplementaire vers l'EXE; `--dev` ajoute uniquement pour `app.py` |
| cwd subprocess | `cwd=str(PROJECT_ROOT)` (L248) |

Snippet `_detect_app_command` (L128-135) :
```
def _detect_app_command(prefer_exe: bool = True) -> tuple[list[str], str]:
    if prefer_exe and DIST_EXE.is_file():
        return ([str(DIST_EXE)], "exe")
    return ([sys.executable, str(APP_PY), "--dev"], "dev")
```

### Etat reel sur disque (FIGE)

- `dist/CineSort.exe` PRESENT (cf. section 1a, 2026-06-08 11:56:47, 59,6 MB).
- `app.py` PRESENT a la racine projet.
- Donc dans l'invocation par defaut `python scripts/observe.py --library test_library --modes dashboard`, la branche EXE est prise -> `mode_label == "exe"`, subprocess lance `C:\Users\<utilisateur>\projects\CineSort\dist\CineSort.exe`.

### Conclusion (FIGE)

- **H1 CONFIRMEE aussi cote outillage `observe.py`** : par defaut, observe.py lance `dist/CineSort.exe` (PERIME selon section 1a). L'observation reflete donc l'etat PRE-fix ii.b, pas le HEAD courant.
- Une override existe : `--prefer-dev` -> bascule sur `python app.py --dev` (source courant, post-fix ii.b). Sans ce flag, l'observation ne valide PAS la correction iter3.

### Implications operationnelles (OPERATIONNEL)

1. Pour valider le fix ii.b par observe.py sans rebuild, ajouter `--prefer-dev` -> exerce le source courant a HEAD `loop/correction-2026-06`.
2. Sinon, rebuilder `dist/CineSort.exe` (cf. recommandation section 1a) puis relancer observe.py sans flag.
3. Toute campagne observe en cours sans `--prefer-dev` ET avec EXE date d'avant 2026-06-08 23:22:52 +0200 est a re-qualifier (probable EXE-perime, pas regression code). Conforme memoires : AUCUN FIX SOURCE PRODUIT — HARNESS/OUTILLAGE SEUL.

### Lien transverse

- Section 1a confirme l'EXE perime (~686 min avant fix ii.b).
- Cette section 1b confirme que observe.py utilise par defaut cet EXE perime -> double court-circuit du fix ii.b dans le pipeline d'observation.

---
