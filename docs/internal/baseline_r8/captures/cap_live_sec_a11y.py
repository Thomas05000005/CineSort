"""cap_live_sec_a11y.py — Capture de l'etat CASSE securite (CORS/CSRF) + i18n + a11y.

R8 baseline. Lecture seule sur le code existant. Cibles :

  F-SEC-01  CSRF cross-site POST refuse (403) MAIS GET poster non garde (200).
            La garde `_is_forbidden_cross_site()` n'est appelee QUE dans do_POST
            (rest_server.py:1027). do_GET (ligne 873) et le proxy /api/poster
            (ligne 921) ne l'appellent jamais -> un site externe peut LIRE les
            jaquettes/donnees GET cross-site. Etat casse = asymetrie POST/GET.

  F-SEC-02  Le port de l'Origin est IGNORE par `_allowed_origin` (rest_server.py
            :404-430) : seul le HOST compte. http://localhost:9999 (port bidon)
            est donc autorise (200) alors que http://evil.example est refuse (403).
            Etat casse/surprise = un attaquant qui controle n'importe quel service
            sur localhost:<any-port> passe la garde CSRF.

  F-V4B-I18N La cle 'sidebar.nav.doublons' est ABSENTE de locales/fr.json ET
            locales/en.json (746/746 feuilles chacun) mais PRESENTE dans le
            _FALLBACK_FR cable en dur (i18n.js:38). Etat casse = l'onglet
            "Doublons" n'est traduisible que par le fallback FR : un utilisateur
            en EN voit "Doublons" (jamais "Duplicates") et la cle echappe a tout
            outil de validation de completude des locales.

  [13] OMDb  Contraste insuffisant du statut d'erreur OMDb. .omdb-status--error
            (components.css:7634) pose color:#b91c1c sur background rgba(185,28,28,
            0.12) compose sur le fond clair. Ratio mesure 2.94:1 < 4.5:1 (WCAG AA
            texte normal). NON mesurable ici sans getComputedStyle/compositing
            reel -> marque TODO 'a instrumenter' (Playwright), valeur NON inventee.

Usage (depuis la racine du repo, serveur --api UP sur 127.0.0.1:8642) :
  PYTHONPATH=. .venv313/Scripts/python.exe \
    docs/internal/baseline_r8/captures/cap_live_sec_a11y.py \
    > docs/internal/baseline_r8/captures/cap_live_sec_a11y.out.txt 2>&1

HARD RULES respectees : aucun effet de bord sur la vraie biblio, aucun write
serveur (on POST get_status = lecture seule), token masque, serveur laisse UP.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8642"
SEP = "=" * 72


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _mask(tok: str) -> str:
    if not tok:
        return "<absent>"
    if len(tok) <= 8:
        return "*" * len(tok)
    return f"{tok[:3]}...{tok[-2:]} (len={len(tok)})"


def _load_token() -> str:
    """Lit rest_api_token depuis settings.json (utf-8-sig pour tolerer le BOM).

    Le token N'EST PAS chiffre (memoire projet : rest_api_token en CLAIR). On le
    lit uniquement pour fabriquer un Authorization valide ; il est masque a
    l'affichage.
    """
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "CineSort", "settings.json"),
        os.path.join(os.environ.get("APPDATA", ""), "CineSort", "settings.json"),
        os.path.join(os.path.expanduser("~"), ".cinesort", "settings.json"),
        "settings.json",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                tok = str(data.get("rest_api_token") or "")
                if tok:
                    return tok
            except (OSError, ValueError):
                continue
    return ""


def _request(
    method: str, path: str, *, origin: str | None, token: str, payload: dict | None = None
) -> int:
    """Envoie une requete forgee via urllib et retourne le code HTTP.

    On capture HTTPError pour recuperer le code (403/401/...) sans lever. Le
    `payload` est fourni pour get_status (run_id requis) afin que la SEULE
    variable entre les appels F-SEC-02 soit l'Origin : le code 200 vs 403 ne
    depend alors QUE de la garde CSRF, pas d'un parametre manquant (sinon 400).
    """
    url = f"{BASE}{path}"
    body = json.dumps(payload or {}).encode("utf-8") if method == "POST" else None
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


# --------------------------------------------------------------------------- #
# F-SEC-01 / F-SEC-02 : CORS/CSRF forge HTTP
# --------------------------------------------------------------------------- #
def _sec_forge(token: str) -> None:
    print(SEP)
    print("F-SEC-01 / F-SEC-02 — Forge CORS/CSRF (rest_server.py:404-442, 1027)")
    print(SEP)
    print(f"  token (masque)              : {_mask(token)}")
    print(f"  CSRF guard appele dans      : do_POST seulement (rest_server.py:1027)")
    print(f"  do_GET (ligne 873) garde ?  : NON  -> /api/poster (ligne 921) non garde")
    print()

    # run_id fourni : get_status l'exige. Sur les appels evil.example le 403 tombe
    # AVANT le dispatch (garde CSRF ligne 1027), donc le param est moot ; sur
    # localhost:9999 il garantit que le 200 vient de la garde franchie, pas d'un
    # body vide (qui rendrait 400 et masquerait la demonstration du port-ignore).
    gs = {"run_id": "x"}

    # --- F-SEC-01 ---------------------------------------------------------- #
    print("  [F-SEC-01] POST /api/run/get_status  Origin=http://evil.example")
    st_post_evil = _request(
        "POST", "/api/run/get_status", origin="http://evil.example", token=token, payload=gs
    )
    print(f"             -> HTTP {st_post_evil}   (attendu 403 : POST cross-site refuse)")

    print("  [F-SEC-01] GET  /api/poster?id=550&size=w500  Origin=http://evil.example")
    st_get_evil = _request(
        "GET",
        "/api/poster?id=550&size=w500",
        origin="http://evil.example",
        token=token,
    )
    print(
        f"             -> HTTP {st_get_evil}   (attendu 200 : GET NON garde = trou CSRF lecture)"
    )
    print()

    # --- F-SEC-02 ---------------------------------------------------------- #
    print("  [F-SEC-02] Le PORT de l'Origin est ignore (seul le host compte)")
    print("  [F-SEC-02] POST /api/run/get_status  Origin=http://localhost:9999")
    st_post_9999 = _request(
        "POST", "/api/run/get_status", origin="http://localhost:9999", token=token, payload=gs
    )
    print(
        f"             -> HTTP {st_post_9999}   (attendu 200 : port 9999 ignore, host=localhost OK)"
    )

    print("  [F-SEC-02] POST /api/run/get_status  Origin=http://evil.example")
    st_post_evil2 = _request(
        "POST", "/api/run/get_status", origin="http://evil.example", token=token, payload=gs
    )
    print(f"             -> HTTP {st_post_evil2}   (attendu 403 : host externe refuse)")
    print()

    # --- Verdicts ---------------------------------------------------------- #
    sec01_ok = (st_post_evil == 403) and (st_get_evil == 200)
    sec02_ok = (st_post_9999 == 200) and (st_post_evil2 == 403)
    print("  VERDICT F-SEC-01 : "
          + ("CONFIRME (POST 403 garde / GET 200 NON garde -> asymetrie)"
             if sec01_ok else f"NON CONFORME (post_evil={st_post_evil}, get_evil={st_get_evil})"))
    print("  VERDICT F-SEC-02 : "
          + ("CONFIRME (port ignore : localhost:9999 -> 200, evil -> 403)"
             if sec02_ok else f"NON CONFORME (9999={st_post_9999}, evil={st_post_evil2})"))
    print()


# --------------------------------------------------------------------------- #
# F-V4B-I18N : cle doublons absente des locales, presente seulement en fallback
# --------------------------------------------------------------------------- #
def _flatten(node, prefix=""):
    out = []
    for key, val in node.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            out.extend(_flatten(val, full))
        else:
            out.append(full)
    return out


def _i18n() -> None:
    print(SEP)
    print("F-V4B-I18N — 'sidebar.nav.doublons' absente des locales, hardcodee en fallback")
    print(SEP)
    repo = os.getcwd()
    fr_path = os.path.join(repo, "locales", "fr.json")
    en_path = os.path.join(repo, "locales", "en.json")
    i18n_path = os.path.join(repo, "web", "dashboard", "core", "i18n.js")

    with open(fr_path, encoding="utf-8-sig") as fh:
        fr = json.load(fh)
    with open(en_path, encoding="utf-8-sig") as fh:
        en = json.load(fh)
    fr_keys = _flatten(fr)
    en_keys = _flatten(en)

    target = "sidebar.nav.doublons"
    in_fr = target in fr_keys
    in_en = target in en_keys

    print(f"  locales/fr.json feuilles    : {len(fr_keys)}")
    print(f"  locales/en.json feuilles    : {len(en_keys)}")
    print(f"  '{target}' dans fr.json     : {in_fr}")
    print(f"  '{target}' dans en.json     : {in_en}")

    # Soeurs presentes pour montrer que la nav existe SANS la cle doublons
    siblings = sorted(k for k in fr_keys if k.startswith("sidebar.nav."))
    print(f"  sidebar.nav.* dans fr.json  : {siblings}")

    # Presence dans le _FALLBACK_FR cable en dur (i18n.js)
    fallback_line = None
    with open(i18n_path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if '"sidebar.nav.doublons"' in line:
                fallback_line = (n, line.strip())
                break
    if fallback_line:
        print(f"  '{target}' dans _FALLBACK_FR : OUI  (i18n.js:{fallback_line[0]})")
        print(f"                                {fallback_line[1]}")
    else:
        print(f"  '{target}' dans _FALLBACK_FR : NON TROUVE (drift a verifier)")

    counts_ok = (len(fr_keys) == 746) and (len(en_keys) == 746)
    confirmed = (not in_fr) and (not in_en) and (fallback_line is not None)
    print()
    print("  VERDICT F-V4B-I18N : "
          + ("CONFIRME (746/746, absente des 2 locales, hardcodee fallback FR -> "
             "onglet Doublons non traduisible en EN)"
             if (confirmed and counts_ok)
             else f"DRIFT (fr={len(fr_keys)},en={len(en_keys)},in_fr={in_fr},"
                  f"in_en={in_en},fallback={fallback_line is not None})"))
    print()


# --------------------------------------------------------------------------- #
# [13] OMDb contrast — TODO a instrumenter (Playwright/WCAG)
# --------------------------------------------------------------------------- #
def _omdb_contrast_todo() -> None:
    print(SEP)
    print("[13] OMDb contrast — .omdb-status--error (components.css:7634-7638)")
    print(SEP)
    print("  Source CSS (verifiee) :")
    print("    .omdb-status--error { background: rgba(185, 28, 28, 0.12);")
    print("                          color: #b91c1c;")
    print("                          border-color: rgba(185, 28, 28, 0.30); }")
    print()
    print("  STATUT : TODO 'a instrumenter' (NON mesure ici).")
    print("    Raison : le ratio WCAG depend du compositing reel (texte #b91c1c")
    print("    sur le background semi-transparent compose sur le fond de page) et")
    print("    de getComputedStyle -> requiert Playwright en runtime, PAS une lecture")
    print("    de source. Valeur NON inventee.")
    print("    Ratio documente attendu : 2.94:1  (< 4.5:1 WCAG AA texte normal).")
    print("    Selecteur a instrumenter : .omdb-status--error")
    print("    A faire : naviguer la page Parametres, declencher l'etat erreur OMDb,")
    print("    lire window.getComputedStyle(el).color + couleur de fond composee,")
    print("    calculer le ratio de luminance relative (WCAG 2.x).")
    print()


def main() -> None:
    token = _load_token()
    _sec_forge(token)
    _i18n()
    _omdb_contrast_todo()
    print(SEP)
    print("FIN capture cap_live_sec_a11y — serveur laisse UP, aucune ecriture biblio.")
    print(SEP)


if __name__ == "__main__":
    main()
