# -*- coding: utf-8 -*-
"""
M4 - Matrice de cablage Actions UI bouton -> feedback (verif totale 2026-07).

REJOUABLE : python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/m4_actions_ui.py
Sortie    : docs/internal/verif_totale_2026_07/matrices/m4_actions_ui.json

Analyse statique (aucune execution de l'app) :
1. Extrait tous les attributs data-*action="..." emis dans les templates JS
   de web/dashboard (hors web/dashboard/tests).
2. Pour chaque famille d'attribut, localise les lectures deleguees
   (dataset.camelCase, closest("[data-...-action]"), selecteurs values).
3. Pour chaque (famille, valeur) : extrait le bloc handler
   (case "x" / if (action === "x") / [..].includes(action) / bind par
   selecteur value / fallback = fonction englobante du site de lecture)
   + suit les appels de fonctions locales (profondeur 3).
4. Sur le texte combine : endpoints apiPost/apiGet, etat pendant
   (disabled/spinner/skeleton/aria-busy), feedback succes (toast/notify/
   render/navigation/modal/window.open/callback on*, HORS blocs catch),
   gestion erreur (check .ok OU catch qui affiche), confirmation
   (dangerConfirmModal/confirm/showModal+actions), countdown.
5. Contrat API - 2 saveurs detectees par fichier :
   - core/api.js  : apiPost -> {status,data}, ne throw que sur erreur reseau
                    => res.ok est TOUJOURS undefined (check mort) ;
                    la gestion d'erreur exige data.ok===false OU catch.
   - _v5_helpers  : apiPost -> {ok,data,status}, ne throw JAMAIS
                    => res.ok est valide ; un catch seul est MORT.
6. Verdict par action :
   SANS_HANDLER      : famille jamais lue, ou valeur statique sans branche.
   CASSE             : branche sans effet observable, OU check res.ok mort
                       (saveur core/api.js) -> branche succes jamais prise.
   SANS_CONFIRMATION : action destructrice avec appel API sans confirmation.
   MUET_ERREUR       : appel API sans gestion d'erreur effective.
   MUET_SUCCES       : appel API sans feedback visible en cas de succes.
   OK                : cablage complet (ou action purement UI avec effet).
"""

import json
import os
import re
import sys
from collections import OrderedDict

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
DASH = os.path.join(REPO, "web", "dashboard")
OUT = os.path.join(REPO, "docs", "internal", "verif_totale_2026_07", "matrices", "m4_actions_ui.json")

MAX_FOLLOW_DEPTH = 2

# Valeurs qui matchent un mot-cle destructeur mais qui sont en realite des
# annulations/retours a l'etat par defaut, des previews ou des decisions
# reversibles (la destruction reelle est differee et confirmee ailleurs).
NON_DESTRUCTIVE_VALUES = {
    "unmark-delete",  # annule un marquage pour suppression
    "clear-override",  # retour au match TMDb automatique
    "undo-preview",  # simple preview de l'undo
    "keep",  # decision doublons reversible, destruction a Apply
    "show-presets",  # lecture seule
    "reload-plan",  # relecture
}
DESTRUCTIVE_VALUE = re.compile(
    r"\b(delete|remove|purge|reset|trash|wipe|apply)\b|run-apply|cancel-run|(?<!un)mark-delete", re.I
)
DESTRUCTIVE_ENDPOINT = re.compile(
    r"\b(delete|remove|purge|reset|apply|undo|wipe)\b|cancel_run|(?<!un)mark_for_deletion|delete_", re.I
)

# ---------------------------------------------------------------- utilitaires


def read_text(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def iter_js_files():
    for root, dirs, files in os.walk(DASH):
        dirs[:] = [d for d in dirs if d not in ("tests", "node_modules")]
        for fn in sorted(files):
            if fn.endswith(".js"):
                yield os.path.join(root, fn)


def rel(path):
    return os.path.relpath(path, REPO).replace("\\", "/")


def line_of(text, idx):
    return text.count("\n", 0, idx) + 1


def camel(family):
    parts = family.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def scan_block(text, start, open_ch="{", close_ch="}"):
    """Depuis text[start] == open_ch, renvoie l'index APRES le fermant.
    Scanner tolerant : saute strings, template literals (${} imbriques),
    commentaires // et /* */."""
    i = start
    n = len(text)
    depth = 0
    mode = []  # pile: 'brace', 'sq', 'dq', 'tpl', 'tplexpr'
    while i < n:
        c = text[i]
        top = mode[-1] if mode else None
        if top in ("sq", "dq"):
            if c == "\\":
                i += 2
                continue
            if (top == "sq" and c == "'") or (top == "dq" and c == '"') or c == "\n":
                mode.pop()
            i += 1
            continue
        if top == "tpl":
            if c == "\\":
                i += 2
                continue
            if c == "`":
                mode.pop()
                i += 1
                continue
            if c == "$" and i + 1 < n and text[i + 1] == "{":
                mode.append("tplexpr")
                i += 2
                continue
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "'":
            mode.append("sq")
        elif c == '"':
            mode.append("dq")
        elif c == "`":
            mode.append("tpl")
        elif c == "{" and open_ch == "{":
            if top == "tplexpr":
                mode.append("brace")
            else:
                depth += 1
        elif c == "}" and open_ch == "{":
            if top == "tplexpr":
                mode.pop()
            elif top == "brace":
                mode.pop()
            else:
                depth -= 1
                if depth == 0:
                    return i + 1
        elif c == open_ch and open_ch != "{":
            depth += 1
        elif c == close_ch and open_ch != "{":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


# ------------------------------------------------- extraction des definitions

FUNC_DECL_RX = re.compile(r"(?:^|\n)[ \t]*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")
FUNC_EXPR_RX = re.compile(
    r"(?:^|\n)[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)\n]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
)


def _skip_ws(text, i):
    n = len(text)
    while i < n and text[i] in " \t\r\n":
        i += 1
    return i


def extract_functions(text):
    """Renvoie (funcs: name->body, spans: [(start,end,name)])."""
    funcs = {}
    spans = []

    for m in FUNC_DECL_RX.finditer(text):
        name = m.group(1)
        # m.end() est juste apres '(' de la liste de params -> equilibre les ().
        pend = scan_block(text, m.end() - 1, "(", ")")
        j = _skip_ws(text, pend)
        if j < len(text) and text[j] == "{":
            end = scan_block(text, j)
            funcs.setdefault(name, text[j:end])
            spans.append((m.start(), end, name))

    for m in FUNC_EXPR_RX.finditer(text):
        name = m.group(1)
        text[m.end() : m.end() + 4]
        j = m.end()
        if text[m.end() - 2 : m.end()] == "=>":
            j = _skip_ws(text, m.end())
            if j < len(text) and text[j] == "{":
                end = scan_block(text, j)
                funcs.setdefault(name, text[j:end])
                spans.append((m.start(), end, name))
            else:
                eol = text.find("\n", j)
                eol = eol if eol > 0 else len(text)
                funcs.setdefault(name, text[j:eol])
                spans.append((m.start(), eol, name))
        else:
            # const f = function (...) { ... }  ou  const f = ident =>
            brace = text.find("{", m.end())
            arrow = text.find("=>", m.end(), m.end() + 200)
            if arrow != -1 and (brace == -1 or arrow < brace):
                j = _skip_ws(text, arrow + 2)
                if j < len(text) and text[j] == "{":
                    end = scan_block(text, j)
                    funcs.setdefault(name, text[j:end])
                    spans.append((m.start(), end, name))
                else:
                    eol = text.find("\n", j)
                    eol = eol if eol > 0 else len(text)
                    funcs.setdefault(name, text[j:eol])
                    spans.append((m.start(), eol, name))
            elif brace != -1 and brace - m.end() < 300:
                end = scan_block(text, brace)
                funcs.setdefault(name, text[brace:end])
                spans.append((m.start(), end, name))
    return funcs, spans


CALL_RX = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
CALL_STOPLIST = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "function",
    "typeof",
    "String",
    "Number",
    "Boolean",
    "Array",
    "Object",
    "JSON",
    "parseInt",
    "parseFloat",
    "setTimeout",
    "setInterval",
    "clearTimeout",
    "encodeURIComponent",
    "decodeURIComponent",
    "fetch",
    "Promise",
    "Error",
}
# Ne pas suivre les fonctions de rendu/bind : elles re-attachent les listeners
# de TOUTES les actions et pollueraient l'analyse avec les endpoints des autres
# branches. Leur simple appel compte deja comme feedback (RX_RENDER sur le texte).
EXPAND_EXCLUDE_RX = re.compile(r"^_?(render|build|bind|esc|fmt|format|html)", re.I)


def expand_calls(block, funcs, depth=0, visited=None):
    if visited is None:
        visited = set()
    combined = [block]
    if depth >= MAX_FOLLOW_DEPTH:
        return block
    for m in CALL_RX.finditer(block):
        name = m.group(1)
        if name in CALL_STOPLIST or name in visited or name not in funcs:
            continue
        if EXPAND_EXCLUDE_RX.match(name):
            continue
        visited.add(name)
        combined.append(expand_calls(funcs[name], funcs, depth + 1, visited))
    return "\n".join(combined)


# ------------------------------------------------------- extraction des blocs

DISPATCH_TOKEN_RX = re.compile(r"\baction\b|\bdataset\b|\bkind\b|\bcmd\b|\bdecision\b")


def _if_condition_block(text, cmp_idx):
    """cmp_idx pointe dans une condition. Remonte au `if (` englobant,
    equilibre la condition, renvoie (body, ok) ou (None, False)."""
    # cherche le dernier `if (` avant cmp_idx sur la meme instruction
    seg_start = max(0, cmp_idx - 300)
    seg = text[seg_start:cmp_idx]
    m = None
    for m2 in re.finditer(r"\bif\s*\(", seg):
        m = m2
    if not m:
        return None, False
    open_paren = seg_start + m.end() - 1
    cond_end = scan_block(text, open_paren, "(", ")")
    if cond_end <= cmp_idx:  # la condition ne couvre pas notre comparaison
        return None, False
    cond = text[open_paren:cond_end]
    if not DISPATCH_TOKEN_RX.search(cond):
        return None, False
    j = _skip_ws(text, cond_end)
    if j < len(text) and text[j] == "{":
        end = scan_block(text, j)
        return text[j:end], True
    # statement unique sans accolades : jusqu'au ; ou fin de ligne
    semi = text.find(";", j)
    eol = text.find("\n", j)
    stop = min(x for x in (semi, eol, len(text)) if x > 0)
    return text[j : stop + 1], True


def _allowed_ranges(read_positions, spans, text_len):
    """Plages plausibles de dispatch : plus petite fonction nommee englobant
    chaque site de lecture de la famille (sinon fenetre autour du site)."""
    ranges = []
    for rp in read_positions:
        best = None
        for s, e, _name in spans:
            if s <= rp < e and (best is None or (e - s) < (best[1] - best[0])):
                best = (s, e)
        ranges.append(best if best else (max(0, rp - 500), min(text_len, rp + 4000)))
    return ranges


def find_specific_block(text, family, value, read_positions, spans, funcs):
    """Modes cibles sur la valeur : case / selector-bind / if-eq / includes.
    Renvoie (bloc, ligne, mode) ou None."""
    v = re.escape(value)
    allowed = _allowed_ranges(read_positions, spans, len(text))

    def in_allowed(idx):
        return any(s <= idx < e for (s, e) in allowed)

    # 1) case "value": (avec fallthrough) - prefere une plage de dispatch,
    #    sinon n'importe ou (dispatcher delegue type _handleAction(action)).
    case_matches = list(re.finditer(r'case\s+["\']' + v + r'["\']\s*:', text))
    case_matches.sort(key=lambda m: (0 if in_allowed(m.start()) else 1, m.start()))
    if case_matches:
        m = case_matches[0]
        start = m.end()
        nxt = re.compile(r'\n\s*(?:case\s+["\']|default\s*:)')
        pos = start
        while True:
            mn = nxt.search(text, pos)
            end = mn.start() if mn else min(len(text), start + 4000)
            if text[start:end].strip() or not mn:
                return (text[start:end], line_of(text, m.start()), "case")
            pos = mn.end()
            colon = text.find(":", mn.start())
            start = colon + 1 if colon > 0 else pos

    # 2) bind par selecteur value : [data-fam="value"] ... addEventListener
    #    (callback inline OU reference nommee resolue via funcs)
    fam = re.escape(family)
    for m in re.finditer(r"\[" + fam + r'\s*=\s*[\'"\\]*' + v + r'[\'"\\]*\]', text):
        tail_idx = text.find("addEventListener(", m.end(), m.end() + 600)
        if tail_idx != -1:
            # callback = reference nommee ? (ancre sur CE addEventListener)
            ma = re.match(
                r'addEventListener\(\s*["\']\w+["\']\s*,\s*([A-Za-z_$][\w$]*)\s*[,)]', text[tail_idx : tail_idx + 120]
            )
            if ma and ma.group(1) not in ("async", "function") and ma.group(1) in funcs:
                return (funcs[ma.group(1)], line_of(text, m.start()), "selector-bind-named")
            j = text.find("{", tail_idx)
            if j != -1:
                end = scan_block(text, j)
                return (text[j:end], line_of(text, m.start()), "selector-bind")

    # 3) if (action === "value") ... UNIQUEMENT dans une plage de dispatch
    #    (les comparaisons hors dispatch sont du code de rendu, pas un handler).
    for m in re.finditer(r'[!=]==?\s*["\']' + v + r'["\']|["\']' + v + r'["\']\s*[!=]==?', text):
        if not in_allowed(m.start()):
            continue
        body, ok = _if_condition_block(text, m.start())
        if ok:
            return (body, line_of(text, m.start()), "if-eq")

    # 4) ["a","b"].includes(action)
    for m in re.finditer(r'\[[^\]\n]*["\']' + v + r'["\'][^\]\n]*\]\s*\.includes\(', text):
        j = text.find("{", m.end())
        if j != -1 and j - m.end() < 300:
            end = scan_block(text, j)
            return (text[j:end], line_of(text, m.start()), "includes")

    return None


def find_delegated_block(text, read_positions, spans):
    """Fallback : fonction nommee englobant un site de lecture de la famille
    (handlers 'valeur = donnee' sans branche par valeur, ex. data-row-action)."""
    for rp in read_positions:
        best = None
        for s, e, name in spans:
            if s <= rp < e and (best is None or (e - s) < (best[1] - best[0])):
                best = (s, e, name)
        if best:
            return (text[best[0] : best[1]], line_of(text, rp), "delegated-read")
        return (text[max(0, rp - 300) : rp + 1500], line_of(text, rp), "read-window")
    return None


# ------------------------------------------------------------ analyse du bloc

RX_API = re.compile(r'\b(apiPost|apiGet)\(\s*(["\'`])([^"\'`\n]*)\2')
RX_API_DYN = re.compile(r"\b(apiPost|apiGet)\(\s*`([^`\n]*)`")
RX_PENDING = re.compile(
    r'\.disabled\s*=\s*true|setAttribute\(\s*["\']disabled|aria-busy|'
    r"classList\.(?:add|toggle)\([^)\n]*(?:load|spin|busy|pending|progress)|"
    r"is-loading|--loading|\bskeleton|\bspinner|Skeleton|showSpinner|_setBusy|setLoading|"
    r"en cours|In[Ff]light",
    re.I,
)
RX_TOAST = re.compile(r"\bshowToast\(|\bnotify[A-Z(]|\btoast\(|pushNotification|addNotification", re.I)
RX_RENDER = re.compile(
    r"\b_?render[A-Za-z_]*\(|\b_reload\(|\breload[A-Z][\w]*\(|\brefresh[A-Za-z_]*\(|"
    r"\.innerHTML\s*=|\.textContent\s*=|_renderInPlace|_renderAll|replaceChildren|"
    r"\.remove\(\)|_load[A-Z]\w*\(|_setStatus\(|_set\w*Message\(|_show\w*Message\("
)
RX_NAV = re.compile(r"\bnavigateTo\(|location\.hash\s*=|window\.location\s*=|\.hash\s*=|window\.open\(")
RX_MODAL = re.compile(
    r"\bshowModal\(|\bopen[A-Z]\w*Modal\(|Modal\(\{|\.showModal\(|open[A-Z]\w*Drawer|openDrawer|renderFilmDetail\("
)
RX_CALLBACK = re.compile(r"\bon[A-Z]\w*\s*\(")
RX_CONFIRM = re.compile(
    r"dangerConfirmModal\(|window\.confirm\(|\bconfirm\(|confirmModal|ConfirmModal|"
    # modales de confirmation construites a la main :
    r'role["\']?,?\s*["\']alertdialog|data-[\w-]*-confirm\b|CONFIRMER|irr[eé]versible'
)
RX_COUNTDOWN = re.compile(r"countdown", re.I)
RX_OK_CHECK = re.compile(
    r"\.ok\s*[!=]==?\s*(?:true|false)|if\s*\([^)\n]*\.ok\b|\.ok\s*\?|!\s*\w+(?:\.\w+)*\.ok\b|"
    r"&&\s*\w+(?:\.\w+)*\.ok\b|\.ok\s*&&|\.status\s*[!=]==?\s*200|\.status\s*>=\s*400"
)
RX_RES_OK = re.compile(r"\b(?:res|resp|r|settingsRes\.value)\??\.ok\b(?!\s*=[^=])")
RX_DATA_OK = re.compile(r"\bdata\??\.ok\b|\bd\.ok\b|\.data\??\.ok\b|payload\??\.ok\b")
RX_STATE_MUT = re.compile(
    r"_state\.[\w.$]+(?:\[[^\]\n]*\])?\s*=|_current\w*\s*=|\.dataset\.\w+\s*=|classList\.(add|remove|toggle)|\.style\.\w+\s*="
)
RX_CATCH = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{")


def catch_bodies(text):
    bodies = []
    for m in RX_CATCH.finditer(text):
        brace = text.find("{", m.end() - 1)
        if brace != -1:
            end = scan_block(text, brace)
            bodies.append(text[brace:end])
    return bodies


def analyze(action_value, combined, funcs, api_flavor):
    catches = catch_bodies(combined)
    catch_txt_exp = expand_calls("\n".join(catches), funcs) if catches else ""
    success_txt = combined
    for cb in catches:
        success_txt = success_txt.replace(cb, "")

    endpoints = []
    for m in RX_API.finditer(combined):
        ep = m.group(3).strip()
        if ep and not any(e["endpoint"] == ep and e["fn"] == m.group(1) for e in endpoints):
            endpoints.append({"fn": m.group(1), "endpoint": ep})
    for m in RX_API_DYN.finditer(combined):
        ep = m.group(2).strip()
        if ep and not any(e["endpoint"] == ep for e in endpoints):
            endpoints.append({"fn": m.group(1), "endpoint": ep, "dynamic": True})
    has_api = bool(endpoints)

    pending = bool(RX_PENDING.search(combined))
    fb_toast = bool(RX_TOAST.search(success_txt))
    fb_render = bool(RX_RENDER.search(success_txt))
    fb_nav = bool(RX_NAV.search(success_txt))
    fb_modal = bool(RX_MODAL.search(success_txt))
    fb_callback = bool(RX_CALLBACK.search(success_txt))
    success_feedback = fb_toast or fb_render or fb_nav or fb_modal or fb_callback

    ok_check = bool(RX_OK_CHECK.search(combined))
    has_catch = bool(catches)
    catch_displays = bool(
        RX_TOAST.search(catch_txt_exp) or RX_RENDER.search(catch_txt_exp) or RX_MODAL.search(catch_txt_exp)
    )
    # res.ok mort UNIQUEMENT pour la saveur core/api.js ({status,data}).
    dead_res_ok = (
        api_flavor == "core" and has_api and bool(RX_RES_OK.search(combined)) and not RX_DATA_OK.search(combined)
    )
    if api_flavor == "v5_helpers":
        error_effective = ok_check  # le wrapper ne throw jamais
        dead_catch = has_catch and not ok_check
    else:
        error_effective = ok_check or catch_displays
        dead_catch = False

    confirm = bool(RX_CONFIRM.search(combined)) or bool(
        RX_MODAL.search(combined) and re.search(r"actions\s*:|onConfirm|confirmLabel", combined)
    )
    countdown = bool(RX_COUNTDOWN.search(combined))

    destructive = False
    if action_value not in NON_DESTRUCTIVE_VALUES:
        destructive = bool(DESTRUCTIVE_VALUE.search(action_value)) and has_api
        if not destructive:
            destructive = any(DESTRUCTIVE_ENDPOINT.search(e["endpoint"]) for e in endpoints)

    state_mut = bool(RX_STATE_MUT.search(combined))
    any_effect = has_api or success_feedback or state_mut or confirm or fb_modal

    return {
        "endpoints": endpoints,
        "api_flavor": api_flavor if has_api else None,
        "pending_state": pending,
        "success_feedback": {
            "any": success_feedback,
            "toast": fb_toast,
            "render": fb_render,
            "navigation": fb_nav,
            "modal_or_drawer": fb_modal,
            "callback": fb_callback,
        },
        "error_handling": {
            "ok_check": ok_check,
            "has_catch": has_catch,
            "catch_displays": catch_displays,
            "effective": error_effective,
            "dead_res_ok_check": dead_res_ok,
            "dead_catch_v5": dead_catch,
        },
        "confirmation": {"present": confirm, "countdown": countdown},
        "destructive": destructive,
        "any_effect": any_effect,
    }


def verdict(a):
    flags = []
    if not a["any_effect"]:
        return "CASSE", ["branche trouvee mais aucun effet observable (no-op)"]
    if a["error_handling"]["dead_res_ok_check"]:
        return "CASSE", [
            "check res.ok mort : apiPost core/api.js retourne {status,data} sans .ok -> branche succes jamais prise"
        ]
    if a["destructive"] and not a["confirmation"]["present"]:
        return "SANS_CONFIRMATION", ["action destructrice avec appel API sans confirmation"]
    if a["endpoints"]:
        if not a["error_handling"]["effective"]:
            fl = ["aucune gestion d'erreur effective (ni check .ok, ni catch qui affiche)"]
            if a["error_handling"]["dead_catch_v5"]:
                fl.append("catch mort : le wrapper _v5_helpers.apiPost ne throw jamais")
            return "MUET_ERREUR", fl
        if not a["success_feedback"]["any"]:
            return "MUET_SUCCES", ["aucun feedback visible en cas de succes"]
        if not a["error_handling"]["ok_check"] and a["error_handling"]["catch_displays"]:
            flags.append(
                "partiel : catch affiche mais pas de check data.ok===false (erreurs HTTP repondues silencieuses)"
            )
    if a["destructive"] and a["confirmation"]["present"] and not a["confirmation"]["countdown"]:
        flags.append("confirmation presente mais sans countdown (regle projet : delai 3s si >50 elements)")
    return "OK", flags


# ----------------------------------------------------------------------- main


def _view_of(relfile):
    parts = relfile.split("/")
    if "views" in parts:
        return parts[parts.index("views") + 1].replace(".js", "")
    if "components" in parts:
        return "component:" + parts[parts.index("components") + 1].replace(".js", "")
    return parts[-1].replace(".js", "")


def main():
    files = OrderedDict()
    for path in iter_js_files():
        files[path] = read_text(path)

    funcs_spans = {p: extract_functions(t) for p, t in files.items()}
    flavor_by_file = {}
    for p, t in files.items():
        if "_v5_helpers.js" in p or re.search(r'from\s+["\']\.{0,2}/?[\w./]*_v5_helpers\.js["\']', t):
            flavor_by_file[p] = "v5_helpers"
        else:
            flavor_by_file[p] = "core"

    # 1) emissions
    emissions = []
    rx_emit = re.compile(r'(?<!\[)\bdata-((?:[a-z0-9]+-)*action)\s*=\s*"([^"]*)"')
    for path, text in files.items():
        for m in rx_emit.finditer(text):
            emissions.append(
                {
                    "family": "data-" + m.group(1),
                    "value": m.group(2),
                    "file": rel(path),
                    "line": line_of(text, m.start()),
                    "dynamic": "${" in m.group(2),
                }
            )

    # 2) lectures par famille
    families = sorted({e["family"] for e in emissions})
    family_reads = {f: [] for f in families}
    for f in families:
        cam = camel(f[len("data-") :])
        rx_read = re.compile(
            r"dataset\." + re.escape(cam) + r"\b|"
            r"\[\s*" + re.escape(f) + r"\s*[\]=]|"
            r'getAttribute\(\s*["\']' + re.escape(f) + r'["\']'
        )
        for path, text in files.items():
            for m in rx_read.finditer(text):
                family_reads[f].append(
                    {"file": rel(path), "line": line_of(text, m.start()), "abs": path, "idx": m.start()}
                )

    # 3) dedoublonnage (famille, valeur)
    seen = OrderedDict()
    for e in emissions:
        key = (e["family"], e["value"])
        if key not in seen:
            seen[key] = {"emit_sites": [], "dynamic": e["dynamic"]}
        seen[key]["emit_sites"].append({"file": e["file"], "line": e["line"]})

    actions = []
    stats = {}

    def bump(v):
        stats[v] = stats.get(v, 0) + 1

    for (family, value), info in seen.items():
        reads = family_reads.get(family, [])
        read_files = sorted({r["file"] for r in reads})
        views = sorted({_view_of(s["file"]) for s in info["emit_sites"]})

        entry = {
            "family": family,
            "action": value,
            "views": views,
            "emit_sites": info["emit_sites"],
            "dynamic_value": info["dynamic"],
            "family_read_in": read_files,
        }

        if info["dynamic"]:
            entry["handler"] = {"found": bool(read_files), "mode": "dynamic-dispatch"}
            entry["analysis"] = None
            if read_files:
                entry["verdict"] = "OK"
                entry["flags"] = ["valeur dynamique : dispatch present, branche non tracee statiquement"]
            else:
                entry["verdict"] = "SANS_HANDLER"
                entry["flags"] = ["valeur dynamique et famille jamais lue"]
            actions.append(entry)
            bump(entry["verdict"])
            continue

        if value.isdigit():
            entry["handler"] = {"found": bool(read_files), "mode": "index-dispatch"}
            entry["analysis"] = None
            entry["verdict"] = "OK" if read_files else "SANS_HANDLER"
            entry["flags"] = ["dispatch par index de tableau (actions passees en JS)"]
            actions.append(entry)
            bump(entry["verdict"])
            continue

        if not read_files:
            entry["handler"] = {"found": False}
            entry["analysis"] = None
            entry["verdict"] = "SANS_HANDLER"
            entry["flags"] = ["famille d'attribut jamais lue (aucun listener)"]
            actions.append(entry)
            bump(entry["verdict"])
            continue

        handler = None
        emit_files = {s["file"] for s in info["emit_sites"]}
        # Les fichiers qui emettent l'attribut ET lisent la famille en premier :
        # le dispatch vit quasi toujours dans la vue qui rend le bouton.
        search_paths = sorted(
            (p for p in files if rel(p) in read_files), key=lambda p: (0 if rel(p) in emit_files else 1, rel(p))
        )
        # Passe A : modes cibles sur la valeur (case / selector / if-eq / includes)
        for path in search_paths:
            text = files[path]
            funcs, spans = funcs_spans[path]
            rpos = [r["idx"] for r in reads if r["abs"] == path]
            res = find_specific_block(text, family, value, rpos, spans, funcs)
            if res:
                block, ln, mode = res
                handler = {"found": True, "file": rel(path), "line": ln, "mode": mode, "confidence": "high"}
                combined = expand_calls(block, funcs)
                entry["analysis"] = analyze(value, combined, funcs, flavor_by_file[path])
                break
        # Passe B : fallback fonction englobante du listener (valeur = donnee)
        if handler is None:
            for path in search_paths:
                text = files[path]
                funcs, spans = funcs_spans[path]
                rpos = [r["idx"] for r in reads if r["abs"] == path]
                res = find_delegated_block(text, rpos, spans)
                if res:
                    block, ln, mode = res
                    handler = {"found": True, "file": rel(path), "line": ln, "mode": mode, "confidence": "low"}
                    combined = expand_calls(block, funcs)
                    entry["analysis"] = analyze(value, combined, funcs, flavor_by_file[path])
                    break

        if handler is None:
            entry["handler"] = {"found": False}
            entry["analysis"] = None
            entry["verdict"] = "SANS_HANDLER"
            entry["flags"] = ["famille lue mais aucune branche pour cette valeur"]
        else:
            entry["handler"] = handler
            v, fl = verdict(entry["analysis"])
            if handler["confidence"] == "low":
                fl = list(fl) + [
                    "confiance basse : bloc = fonction englobante du listener (valeur traitee comme donnee)"
                ]
            entry["verdict"], entry["flags"] = v, fl

        actions.append(entry)
        bump(entry["verdict"])

    out = {
        "matrix": "M4 - Actions UI bouton -> feedback",
        "generated_by": "docs/internal/verif_totale_2026_07/scripts_matrices/m4_actions_ui.py",
        "scope": "web/dashboard/**/*.js (hors tests/)",
        "verdict_definitions": {
            "OK": "handler + (si API) feedback succes + gestion erreur effective + (si destructif) confirmation",
            "MUET_SUCCES": "appel API sans aucun feedback visible en cas de succes",
            "MUET_ERREUR": "appel API sans gestion d'erreur effective (ni check .ok ni catch qui affiche)",
            "SANS_CONFIRMATION": "action destructrice (delete/reset/apply/cancel-run/...) avec API sans confirmation",
            "SANS_HANDLER": "attribut emis mais aucune branche/listener ne traite cette valeur",
            "CASSE": "branche sans effet observable, ou check res.ok mort sur retour apiPost {status,data}",
        },
        "api_contract_note": {
            "core/api.js": "apiPost -> {status,data} ; throw uniquement sur erreur reseau ; res.ok N'EXISTE PAS",
            "views/_v5_helpers.js": "apiPost -> {ok,data,status} ; ne throw JAMAIS ; un catch seul est mort",
        },
        "totals": {
            "unique_actions": len(actions),
            "emission_sites": len(emissions),
            "families": len(families),
        },
        "stats_by_verdict": dict(sorted(stats.items())),
        "actions": actions,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("OK ->", rel(OUT))
    print("Totaux:", json.dumps(out["totals"]))
    print("Verdicts:", json.dumps(out["stats_by_verdict"]))


if __name__ == "__main__":
    sys.exit(main())
