#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ITER10 Gate lisibilite — mesure objective runtime (mojibake / contraste / unmount).

Lance python app.py --api + python app.py --dev (CDP), navigue le dashboard, et
mesure :
  - MOJIBAKE : labels DOM == chaines UTF-8 attendues (exact-match)
  - CONTRASTE : ratio WCAG calcule par theme (studio/cinema/luxe/neon)
  - UNMOUNT : 0 requete polling apres demontage (5s)
  - TIER : invariantes Gold #FFD700, Silver #C0C0C0, Bronze #CD7F32, Platinum #E5E4E2

Ecrit le verdict JSON dans le dossier de capture observe.

Le script REUTILISE le runtime CineSort deja lance par observe.py si possible,
sinon relance app.py --dev en mode CDP isole.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = PROJECT_ROOT / "docs/internal/observe/2026-06-08_ITER10_LISIBILITE"
# Le dossier de capture est cree par main(), PAS a l'import : un outil de mesure
# qui ecrit sur disque au seul fait d'etre importe n'est pas mesurable.
OUT_FILE = CAPTURE_DIR / "iter10_gate_lisibilite.json"
CDP_PORT = 9224  # different de observe.py (9223)

#: SOURCE UNIQUE des libelles d'etapes de la vue Traitement, dans l'ordre.
#:
#: Ils etaient encodes TROIS fois dans `scripts/` : dans `EXPECTED_LABELS`
#: (`step1`..`step5`, que personne ne relisait — un encodage MORT), dans la
#: liste litterale de la boucle de verification ci-dessous, et dans
#: `_iter10_gate_lisibilite_v2.py`. Renommer une etape dans l'application en
#: laissait deux qui mentaient, dont un incapable de faire echouer quoi que ce
#: soit. `_iter10_gate_lisibilite_v2.py` importe desormais cette liste.
STEP_LABELS = ("Analyse", "Vérification", "Validation", "Doublons", "Application")

#: SELECTEUR UNIQUE des libelles d'etapes dans le DOM.
#:
#: `web/dashboard/views/traitement.js` rend chaque libelle dans
#: `<span class="traitement-step-label">`. Le gate cherchait avec
#: `[data-step] .step-label, .step-card .step-label, .step-label, [data-step] span`
#: — les QUATRE jetons sont absents de l'arbre front : l'attribut reel est
#: `data-traitement-step` (`[data-step]` est un nom d'attribut EXACT, pas un
#: prefixe), la classe reelle `traitement-step-label` (un selecteur de classe ne
#: matche pas un prefixe non plus), et `.step-card` n'existe nulle part. La
#: collecte rendait donc une liste VIDE et les cinq controles d'etape
#: echouaient tous — sans consequence, puisque le code de sortie ne les
#: regardait pas (cf. `gate_ok`).
STEP_LABEL_SELECTOR = ".traitement-step-label"

# Cibles labels-cles (mojibake exact-match)
EXPECTED_LABELS = {
    "sidebar.home": "Accueil",
    "sidebar.processing": "Traitement",
    "sidebar.library": "Bibliothèque",
    "sidebar.quality": "Qualité",
    "sidebar.history": "Historique",
    "sidebar.settings": "Paramètres",
    # Derives de STEP_LABELS : pas de second encodage.
    **{f"step{i}": label for i, label in enumerate(STEP_LABELS, 1)},
}

# Tier invariantes (memoire user)
TIER_INVARIANTS = {
    "platinum": "#e5e4e2",
    "gold": "#ffd700",
    "silver": "#c0c0c0",
    "bronze": "#cd7f32",
}

THEMES = ["studio", "cinema", "luxe", "neon"]


#: Les quatre verdicts que le gate calcule, affiche — et qu'il ignorait.
GATE_VERDICT_KEYS = (
    "mojibake_OK",
    "contraste_4_themes_OK",
    "tier_colors_intactes",
    "unmount_no_poll_OK",
)


def gate_ok(out: dict) -> bool:
    """Verdict global du gate : la mesure a abouti ET les quatre verdicts sont verts.

    `out["ok"]` etait pose a `True` **inconditionnellement**, a la fin du bloc
    `try`, juste apres les mesures ; le code de sortie valait `0 if out["ok"]`.
    Les quatre verdicts reellement calcules — `mojibake_OK`,
    `contraste_4_themes_OK`, `tier_colors_intactes`, `unmount_no_poll_OK` —
    etaient ecrits dans le JSON et imprimes sur stderr, mais n'entraient dans
    aucune decision. Le gate ne pouvait echouer que lorsque Playwright levait,
    c'est-a-dire quand la mesure n'avait PAS eu lieu : la seule chose qu'il
    gardait etait sa propre execution.

    Une cle absente vaut FAUX : un verdict qui n'a pas ete calcule n'est pas un
    verdict vert.
    """
    if not out.get("measured"):
        return False
    return all(bool(out.get(key)) for key in GATE_VERDICT_KEYS)


def verifier_etapes(steps: list[str]) -> dict:
    """Confronte les libelles collectes dans le DOM a `STEP_LABELS`, DANS L'ORDRE.

    Exact-match positionnel — ce que l'en-tete du module annonce depuis toujours
    (« labels DOM == chaines UTF-8 attendues (exact-match) »). Le controle
    d'origine faisait `any(expected in s for s in steps)` : n'importe quel noeud
    CONTENANT le libelle suffisait, donc un seul conteneur portant les cinq
    textes validait les cinq etapes d'un coup, et un libelle suffixe passait
    aussi. Combine a un selecteur qui ne matchait rien, il ne restait aucune
    mesure.
    """
    checks: dict = {}
    for i, expected_label in enumerate(STEP_LABELS, 1):
        actual = steps[i - 1] if i - 1 < len(steps) else ""
        checks[f"step{i}"] = {
            "expected": expected_label,
            "actual": actual,
            "actual_hex": actual.encode("utf-8").hex() if actual else "",
            "actual_list": steps,
            "ok": actual == expected_label,
        }
    return checks


#: Controles presents dans `labels` mais EXCLUS du verdict : ils ne peuvent
#: rendre que vert, donc les compter revient a diluer le verdict.
INFORMATIVE_CHECKS = frozenset({"bullets_u2022"})


def verdict_mojibake(checks: dict) -> dict:
    """Verdict mojibake : AUCUN libelle reellement casse n'est tolere.

    `checks["bullets_u2022"]` porte `"ok": True` EN DUR — c'est un controle
    informatif, les champs masques n'etant pas forcement montes dans le DOM
    courant. Le verdict appliquait par-dessus une tolerance d'un echec,
    commentee « tolerance 1 (bullets) ». Or le controle bullets etant deja vert
    par construction, cette tolerance ne le couvrait pas : elle restait
    disponible pour un VRAI libelle. Un `Bibliothèque` rendu en mojibake passait
    donc le gate — sur un gate dont c'est la raison d'etre.

    Le controle informatif est desormais EXCLU du denominateur au lieu d'etre
    compense par une tolerance, et le verdict exige l'unanimite du reste.
    """
    verdict_keys = [k for k in checks if k not in INFORMATIVE_CHECKS]
    count_ok = sum(1 for k in verdict_keys if checks[k].get("ok"))
    return {
        "labels_ok_count": count_ok,
        "labels_total": len(verdict_keys),
        "labels_informatifs": sorted(set(checks) & INFORMATIVE_CHECKS),
        "mojibake_OK": count_ok == len(verdict_keys),
    }


def _wait_port(host: str, port: int, timeout: int = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(1)
    return False


def main() -> int:
    out: dict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "labels": {},
        "contrast": {},
        "tier_runtime": {},
        "unmount": {},
        "measured": False,
        "ok": False,
    }

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    # Lance python app.py --dev en CDP 9224, state isole.
    isolated_state = CAPTURE_DIR / "_iter10_state"
    isolated_state.mkdir(parents=True, exist_ok=True)
    (isolated_state / "CineSort").mkdir(exist_ok=True)
    # Seed settings test_library.
    seed = {
        "root": str(PROJECT_ROOT / "test_library"),
        "roots": [str(PROJECT_ROOT / "test_library")],
        "tmdb_enabled": False,
        "auto_check_updates": False,
        "rest_api_port": 8651,
    }
    (isolated_state / "CineSort" / "settings.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")

    env = os.environ.copy()
    env["CINESORT_E2E"] = "1"
    env["CINESORT_CDP_PORT"] = str(CDP_PORT)
    env["LOCALAPPDATA"] = str(isolated_state)
    env["CINESORT_OBSERVE_FORCE_DEV"] = "1"

    print(f"[iter10] launching app.py --dev CDP={CDP_PORT}", file=sys.stderr)
    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "app.py"), "--dev"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        if not _wait_port("127.0.0.1", CDP_PORT, timeout=90):
            out["error"] = f"CDP port {CDP_PORT} unreachable after 90s"
            OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
            return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            ctx = browser.contexts[0]
            page = None
            for p in ctx.pages:
                if "/dashboard" in (p.url or ""):
                    page = p
                    break
            if page is None:
                page = ctx.pages[0]
            try:
                page.wait_for_function(
                    "() => window.__APP_READY__ === true || document.readyState === 'complete'",
                    timeout=30000,
                )
            except Exception:
                pass

            # Test 1 : MOJIBAKE — recuperer textContent de tous les .v5-sidebar-label
            # et items workflow stepper, comparer exact-match aux strings attendues.
            page.evaluate("() => { window.location.hash = '/accueil'; }")
            page.wait_for_timeout(2000)

            sidebar_labels = page.evaluate(
                r"""() => {
                    const out = {};
                    const sidebar = document.querySelectorAll('[data-route] .v5-sidebar-label, .v5-sidebar [data-route]');
                    const all = document.querySelectorAll('[data-route]');
                    all.forEach((el) => {
                        const route = el.getAttribute('data-route');
                        const label = el.querySelector('.v5-sidebar-label, span.label, span')?.textContent?.trim()
                            || el.textContent?.trim() || '';
                        if (route && label) out[route] = label;
                    });
                    return out;
                }"""
            )
            out["sidebar_labels_raw"] = sidebar_labels

            # Compare labels expected vs rendered
            checks = {}
            mapping_route_to_key = {
                "home": "sidebar.home",
                "processing": "sidebar.processing",
                "library": "sidebar.library",
                "quality": "sidebar.quality",
                "history": "sidebar.history",
                "settings": "sidebar.settings",
            }
            for route, key in mapping_route_to_key.items():
                expected = EXPECTED_LABELS[key]
                actual = sidebar_labels.get(route, "")
                # Strip the icon prefix - just take the textual part
                ok = expected in actual or actual == expected
                checks[key] = {
                    "expected": expected,
                    "actual": actual,
                    "actual_hex": actual.encode("utf-8").hex() if actual else "",
                    "ok": ok,
                }

            # Get steps from Traitement view
            page.evaluate("() => { window.location.hash = '/traitement'; }")
            page.wait_for_timeout(2500)
            # Ordre du DOM conserve, aucune deduplication : le controle est
            # POSITIONNEL, donc perdre un doublon decalerait tout le reste.
            steps = page.evaluate(
                r"""(selector) => {
                    return Array.from(document.querySelectorAll(selector))
                        .map((el) => (el.textContent || '').trim());
                }""",
                STEP_LABEL_SELECTOR,
            )
            out["steps_raw"] = steps
            checks.update(verifier_etapes(steps))

            # Bullets U+2022 for masked secrets in Parametres > Integrations
            page.evaluate("() => { window.location.hash = '/parametres'; }")
            page.wait_for_timeout(2000)
            bullets_test = page.evaluate(
                r"""() => {
                    const inputs = document.querySelectorAll('input[type=password], input[name*=token], input[name*=key], input[name*=password]');
                    const out = [];
                    inputs.forEach((i) => {
                        const v = i.value || '';
                        if (v.includes('•')) out.push({name: i.name || i.id, value: v, hex: Array.from(v).map(c => c.codePointAt(0).toString(16)).join(',')});
                    });
                    return out;
                }"""
            )
            checks["bullets_u2022"] = {
                "expected": "U+2022 (•) present in any masked secret",
                "actual": bullets_test,
                "ok": True,  # Si ce champ n'est jamais affiche (formulaire pas encore monte), n'invalide pas mojibake general
                "note": "informatif - les champs masques ne sont pas obligatoirement dans le DOM courant",
            }

            out["labels"] = checks
            out.update(verdict_mojibake(checks))

            # Test 2 : CONTRASTE — pour chaque theme, calcul ratio runtime
            ratio_js = r"""
            (theme) => {
                const luminance = (r, g, b) => {
                    const a = [r, g, b].map(v => {
                        v = v / 255;
                        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
                    });
                    return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
                };
                const parseRGB = (s) => {
                    const m = s.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
                    return m ? [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])] : null;
                };
                const ratio = (rgb1, rgb2) => {
                    const l1 = luminance(...rgb1);
                    const l2 = luminance(...rgb2);
                    const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
                    return (hi + 0.05) / (lo + 0.05);
                };
                // Set theme
                document.body.dataset.theme = theme;
                document.documentElement.dataset.theme = theme;
                // Wait one frame
                return new Promise((resolve) => {
                    requestAnimationFrame(() => {
                        const probe = document.createElement('div');
                        probe.style.position = 'fixed';
                        probe.style.left = '-9999px';
                        probe.style.color = 'var(--text-primary)';
                        probe.style.backgroundColor = 'var(--bg)';
                        document.body.appendChild(probe);
                        const cs = getComputedStyle(probe);
                        const fg = parseRGB(cs.color);
                        const bg = parseRGB(cs.backgroundColor);
                        probe.style.color = 'var(--text-secondary)';
                        const cs2 = getComputedStyle(probe);
                        const fg2 = parseRGB(cs2.color);
                        probe.style.color = 'var(--text-muted)';
                        const cs3 = getComputedStyle(probe);
                        const fg3 = parseRGB(cs3.color);
                        // Tier colors invariants
                        probe.style.color = 'var(--tier-gold)';
                        const tier_gold = getComputedStyle(probe).color;
                        probe.style.color = 'var(--tier-silver)';
                        const tier_silver = getComputedStyle(probe).color;
                        probe.style.color = 'var(--tier-bronze)';
                        const tier_bronze = getComputedStyle(probe).color;
                        probe.style.color = 'var(--tier-platinum)';
                        const tier_platinum = getComputedStyle(probe).color;
                        document.body.removeChild(probe);
                        const out = {
                            theme,
                            fg_primary: fg,
                            bg: bg,
                            ratio_primary: fg && bg ? ratio(fg, bg) : null,
                            ratio_secondary: fg2 && bg ? ratio(fg2, bg) : null,
                            ratio_muted: fg3 && bg ? ratio(fg3, bg) : null,
                            tier_gold,
                            tier_silver,
                            tier_bronze,
                            tier_platinum,
                        };
                        resolve(out);
                    });
                });
            }
            """
            contrast_results = {}
            tier_results = {}
            for theme in THEMES:
                res = page.evaluate(ratio_js, theme)
                contrast_results[theme] = {
                    "ratio_primary": res.get("ratio_primary"),
                    "ratio_secondary": res.get("ratio_secondary"),
                    "ratio_muted": res.get("ratio_muted"),
                    "fg_primary": res.get("fg_primary"),
                    "bg": res.get("bg"),
                    "ok_primary": (res.get("ratio_primary") or 0) >= 4.5,
                    "ok_secondary": (res.get("ratio_secondary") or 0) >= 4.5,
                    "ok_muted": (res.get("ratio_muted") or 0) >= 3.0,
                }
                tier_results[theme] = {
                    "gold": res.get("tier_gold"),
                    "silver": res.get("tier_silver"),
                    "bronze": res.get("tier_bronze"),
                    "platinum": res.get("tier_platinum"),
                }

            out["contrast"] = contrast_results
            out["tier_runtime"] = tier_results
            out["contraste_4_themes_OK"] = all(
                contrast_results[t]["ok_primary"] and contrast_results[t]["ok_secondary"] for t in THEMES
            )

            # Verifie tier invariantes : convertir chaque rgb(...) en hex et comparer
            def rgb_to_hex(s):
                if not s:
                    return None
                m = __import__("re").match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", s)
                if not m:
                    return None
                return "#{:02x}{:02x}{:02x}".format(int(m[1]), int(m[2]), int(m[3]))

            tier_intactes = True
            tier_check = {}
            for theme in THEMES:
                tc = tier_results[theme]
                hexes = {k: rgb_to_hex(v) for k, v in tc.items()}
                tier_check[theme] = {"hexes": hexes}
                for name, expected_hex in TIER_INVARIANTS.items():
                    actual = hexes.get(name)
                    if actual != expected_hex:
                        tier_intactes = False
                        tier_check[theme][f"{name}_MISMATCH"] = {
                            "expected": expected_hex,
                            "actual": actual,
                        }
            out["tier_check"] = tier_check
            out["tier_colors_intactes"] = tier_intactes

            # Test 3 : UNMOUNT — naviguer vers /doublons puis quitter, mesurer 0 polling 5s
            polling_log = []

            def on_request(req):
                url = req.url
                if "/api/run/get_status" in url or "/api/run/get_dashboard" in url or "/api/duplicate" in url.lower():
                    polling_log.append({"ts": time.time(), "url": url})

            page.on("request", on_request)

            # Naviguer vers doublons
            page.evaluate("() => { window.location.hash = '/doublons'; }")
            page.wait_for_timeout(3000)
            baseline = len(polling_log)
            # Naviguer ailleurs (accueil) pour declencher unmount
            page.evaluate("() => { window.location.hash = '/accueil'; }")
            page.wait_for_timeout(700)  # grace
            mark_unmount = len(polling_log)
            # Mesure 5s post-unmount
            page.wait_for_timeout(5000)
            post_unmount = len(polling_log)
            new_after_unmount = post_unmount - mark_unmount

            out["unmount"] = {
                "baseline_doublons": baseline,
                "mark_unmount": mark_unmount,
                "post_unmount": post_unmount,
                "new_requests_after_unmount_5s": new_after_unmount,
                "ok": new_after_unmount == 0,
                "sample_requests": polling_log[:20],
            }

            # Test 4 : traitement polling (par defaut)
            polling_log2 = []

            def on_req2(req):
                if "/api/run/get_status" in req.url:
                    polling_log2.append(req.url)

            page.on("request", on_req2)
            page.evaluate("() => { window.location.hash = '/traitement'; }")
            page.wait_for_timeout(3000)
            base_t = len(polling_log2)
            page.evaluate("() => { window.location.hash = '/accueil'; }")
            page.wait_for_timeout(700)
            mark_t = len(polling_log2)
            page.wait_for_timeout(5000)
            after_t = len(polling_log2)
            new_t = after_t - mark_t
            out["unmount_traitement"] = {
                "baseline_traitement": base_t,
                "mark_unmount": mark_t,
                "post_unmount": after_t,
                "new_requests_after_unmount_5s": new_t,
                "ok": new_t == 0,
            }

            out["unmount_no_poll_OK"] = out["unmount"]["ok"] and out["unmount_traitement"]["ok"]

            # La mesure est allee au bout. Le VERDICT, lui, se calcule a partir
            # des quatre resultats (cf. gate_ok) — pas de l'absence d'exception.
            out["measured"] = True
            browser.close()
    except Exception as exc:
        import traceback

        out["error"] = str(exc)
        out["traceback"] = traceback.format_exc()
    finally:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass

    out["ok"] = gate_ok(out)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[iter10] wrote {OUT_FILE}", file=sys.stderr)
    verdicts = " ".join(f"{key}={out.get(key)}" for key in GATE_VERDICT_KEYS)
    print(f"[iter10] measured={out.get('measured')} {verdicts}", file=sys.stderr)
    print(f"[iter10] GATE {'OK' if out['ok'] else 'ECHEC'}", file=sys.stderr)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
