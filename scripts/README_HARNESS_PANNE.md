# Harness panne synthetique CineSort (ITER13)

> Outillage `scripts/` pour reproduire 4 scenarios de panne SMB/probe SANS vrai NAS.
> **NE MODIFIE PAS** le code produit (`cinesort/`).
> Branche : `loop/correction-2026-06`.

## LIMITE HONNETE

Ce harness simule les SYMPTOMES (probe lent, fichier injoignable, panne
intermittente, gros 4K). Il ne reproduit pas la cause physique (latence
reseau SMB, kerberos, block size, etc.). La **validation B humaine sur vrai
partage SMB instable reste a faire** avant de declarer la resilience prouvee
en production.

Critere d'acceptation ITER13 :
- casse prouvee AVANT le fix (sur ces 4 scenarios),
- resilience prouvee APRES le fix (memes 4 scenarios),
- non-regression scan sain (vrais clips CC probes normalement, pas ralentis).

## Vue d'ensemble des 4 scenarios

| Scenario | Outil | Defaillance simulee | Comportement attendu produit |
|---|---|---|---|
| (a) Probe LENT | `fake_probes/slow_ffprobe.py`, `fake_probes/slow_mediainfo.py` | Dort 35s puis stdout vide | Timeout cote CineSort + qualite marquee "indisponible" visiblement, pas score invente |
| (b) Chemin INJOIGNABLE | `make_unreachable_files.py` | UNC fictif ou fichier 0 byte | Identification (TMDb/filename) preservee, probe en erreur visible, scan non bloque |
| (c) Panne INTERMITTENTE | `fake_probes/flaky_ffprobe.py` | Echec N premiers essais, succes ensuite | Retry+backoff, succes final logge, pas de degradation silencieuse |
| (d) Gros 4K H265 | `make_synthetic_4k.py` | Probe lent mais aboutit | Timeout adaptatif (size-aware) doit reussir la ou un timeout brut couperait |

## Activation

### Shims probe (a, c)

Les shims sont des scripts Python. Pour les injecter sous Windows on les place
dans un dossier prioritaire sur `PATH` avec un wrapper `ffprobe.cmd` :

```powershell
# 1. Creer le wrapper Windows (a faire une fois cote test)
$shimDir = "$env:TEMP\cinesort_shims"
New-Item -ItemType Directory -Force $shimDir | Out-Null

# Mode "slow"
@"
@echo off
python "$PWD\scripts\fake_probes\slow_ffprobe.py" %*
"@ | Set-Content -Encoding ASCII "$shimDir\ffprobe.cmd"

@"
@echo off
python "$PWD\scripts\fake_probes\slow_mediainfo.py" %*
"@ | Set-Content -Encoding ASCII "$shimDir\mediainfo.cmd"

# Mode "flaky" (alternative)
@"
@echo off
python "$PWD\scripts\fake_probes\flaky_ffprobe.py" %*
"@ | Set-Content -Encoding ASCII "$shimDir\ffprobe.cmd"

# 2. Activer pour la session
$env:CINESORT_FAKE_PROBE = "slow"          # ou "flaky"
$env:PATH = "$shimDir;$env:PATH"
$env:SLOW_PROBE_SLEEP_SECONDS = "5"        # accelere les tests
$env:FLAKY_PROBE_FAIL_FIRST_N = "2"
$env:FLAKY_PROBE_RESET = "1"               # reset compteur au demarrage
```

Verification rapide :

```powershell
ffprobe foo.mkv     # doit dormir 5s (mode slow) ou echouer 2x (mode flaky)
```

### Generation fichiers (b, d)

```powershell
python scripts/make_unreachable_files.py --out C:\tmp\cinesort_harness\unreach --count 5 --mode local-stub
python scripts/make_unreachable_files.py --out C:\tmp\cinesort_harness\unreach_unc --count 3 --mode unc
python scripts/make_synthetic_4k.py --out C:\tmp\cinesort_harness\big4k --count 3 --duration 2
```

Chaque generateur produit un manifest JSON (`*_manifest.json`) decrivant ce qui
a ete cree et le comportement attendu cote produit.

## Reset entre scenarios

```powershell
Remove-Item Env:CINESORT_FAKE_PROBE -ErrorAction SilentlyContinue
Remove-Item Env:SLOW_PROBE_SLEEP_SECONDS -ErrorAction SilentlyContinue
Remove-Item Env:FLAKY_PROBE_FAIL_FIRST_N -ErrorAction SilentlyContinue
Remove-Item "$env:TEMP\cinesort_fake_probe_count.txt" -ErrorAction SilentlyContinue
$env:PATH = ($env:PATH -split ";" | Where-Object { $_ -notlike "*cinesort_shims*" }) -join ";"
```

## Garanties

- Ne modifie pas `cinesort/`.
- Reutilisable (parametres `--out`, `--count`, env vars).
- Chaque script `py_compile`-able (verifie via `scripts/check_python_compile.py`).
- Documente : ce fichier + docstring sur chaque module.

## Liens

- Bilan : `docs/internal/BILAN_ITER13_2026-06-08.md`, section 1.
- Memoire : "limite honnete: prouve contre panne SIMULEE PAS vrai NAS".
