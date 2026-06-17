"""CONTRACT-DIFF statiques (rejouables) — front (consumer) vs back (producer).

Pour chaque finding : on lit les CLES CONSOMMEES dans le JS (regex sur le vrai
fichier) et les CLES PRODUITES cote backend (introspection dataclass quand le
producteur est importable, sinon regex sur le vrai source au file:line verifie),
puis on imprime l'ENSEMBLE EN ECART (consumer keys absentes du producer) + l'etat
casse observe. Aucune dependance au serveur, aucune ecriture dans la vraie biblio :
lecture seule de fichiers source uniquement.

Run :
  PYTHONPATH=. .venv313/Scripts/python.exe \
    docs/internal/baseline_r8/captures/cap_contracts_static.py \
    > docs/internal/baseline_r8/captures/cap_contracts_static.out.txt 2>&1

Chaque bloc imprime :
  - les cles consumer (front) et producer (back) reellement extraites
  - le SET en ecart (manquantes cote producer)
  - une GATE de falsifiabilite : si la cle existait cote producer, l'ecart serait vide
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())

# Windows : forcer stdout/stderr en UTF-8 sinon le dump JSON des snippets JS
# (fleches U+2192, etc.) casse sous le codec cp1252 lors de la redirection.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = os.getcwd()


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _lines(rel: str):
    return _read(rel).splitlines()


def _slice(rel: str, start: int, end: int) -> str:
    """1-based inclusive line slice of a source file."""
    ls = _lines(rel)
    return "\n".join(ls[start - 1 : end])


def _keys_from_dict_literal(src: str) -> list:
    """Extrait les cles 'foo': ... d'un fragment de dict-literal python (TOUTES
    profondeurs confondues — utile pour les sous-dicts plats type 'detected')."""
    return re.findall(r"""["']([A-Za-z_][A-Za-z0-9_]*)["']\s*:""", src)


def _toplevel_dict_keys(src: str) -> list:
    """Extrait UNIQUEMENT les cles de profondeur 1 d'un return-dict python.

    Suit la profondeur des accolades a partir du PREMIER `{` rencontre : une cle
    "foo": n'est retenue que si elle est exactement a depth==1. Evite que les cles
    de sous-dicts (detected.*, subscores.*, thresholds_used.*) polluent le set des
    cles top-level (sinon on sous-estime l'ecart consumer/producer)."""
    depth = 0
    started = False
    keys = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            # consomme une string-literal ; si depth==1 et suivie de ':', c'est une cle
            quote = c
            j = i + 1
            buf = []
            while j < n and src[j] != quote:
                if src[j] == "\\":
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            k = j + 1
            while k < n and src[k] in " \t\n":
                k += 1
            if started and depth == 1 and k < n and src[k] == ":":
                name = "".join(buf)
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    keys.append(name)
            i = j + 1
            continue
        if c == "{":
            depth += 1
            started = True
        elif c == "}":
            depth -= 1
        i += 1
    # dedup en preservant l'ordre
    seen = set()
    out = []
    for x in keys:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _verify(rel: str, line: int, needle: str) -> str:
    """Confirme que `needle` est bien a `rel:line` ; retourne la VRAIE ligne trouvee
    (ou la 1re occurrence si elle a derive)."""
    ls = _lines(rel)
    real = ls[line - 1] if 0 < line <= len(ls) else ""
    if needle in real:
        return f"{rel}:{line} OK -> {real.strip()[:90]}"
    for i, l in enumerate(ls, 1):
        if needle in l:
            return f"{rel}:{line} DRIFT -> reel {rel}:{i} -> {l.strip()[:90]}"
    return f"{rel}:{line} ABSENT (needle={needle!r})"


def diff(consumer: set, producer: set) -> list:
    return sorted(consumer - producer)


results = {}


def emit(fid: str, *, consumer, producer, mismatch, broken, verify, extra=None):
    block = {
        "finding": fid,
        "consumer_keys": sorted(consumer),
        "producer_keys": sorted(producer),
        "mismatch_consumer_minus_producer": sorted(mismatch),
        "broken_state": broken,
        "verify": verify,
    }
    if extra:
        block.update(extra)
    results[fid] = block
    print("=" * 78)
    print(fid)
    print("-" * 78)
    print(json.dumps(block, indent=2, ensure_ascii=False))
    print()


# ===========================================================================
# F-V8-FILMVIEW-PROBE : film-detail.js lit probe.video/audio/subtitles/
# duration_s ; producer film_support nichee sous metrics["detected"].*
# ===========================================================================
FD = "web/dashboard/views/film-detail.js"
# consumer : ce que la fiche lit sur l'objet `probe`
fd_src = _read(FD)
# probe.video (L141,164,261,293..) probe.audio (L262) probe.subtitles (L263)
# probe.duration_s (L142) probe.container_format (L283)
probe_consumer = set(re.findall(r"\bprobe\.([A-Za-z_][A-Za-z0-9_]*)", fd_src))
# producer : metrics dict de compute_quality_score (quality_score.py:1627-1681) ;
# probe_dict = quality.get("metrics") (film_support.py:312). On extrait les cles
# TOP-LEVEL du metrics + le sous-dict detected.
metrics_top = _slice("cinesort/domain/quality_score.py", 1627, 1681)
# depth-1 uniquement : sinon detected.*/subscores.*/thresholds_used.* polluent
producer_metrics_top = set(_toplevel_dict_keys(metrics_top))
detected_block = _slice("cinesort/domain/quality_score.py", 1632, 1649)
detected_keys = set(_toplevel_dict_keys(detected_block))
emit(
    "F-V8-FILMVIEW-PROBE",
    consumer=probe_consumer,
    producer=producer_metrics_top,
    mismatch=probe_consumer - producer_metrics_top,
    broken=(
        "film-detail.js lit probe.video/probe.audio/probe.subtitles/probe.duration_s "
        "au TOP-LEVEL, mais le producer expose ces donnees uniquement sous "
        "metrics['detected'].{width,height,video_codec,audio_tracks_count,duration_s,...} "
        "-> Video/Audio/Sous-titres/Duree affichent vide (—) / 0 pour tout film."
    ),
    verify=[
        _verify(FD, 141, "probe.video"),
        _verify(FD, 142, "probe.duration_s"),
        _verify(FD, 262, "probe.audio"),
        _verify(FD, 263, "probe.subtitles"),
        _verify("cinesort/ui/api/film_support.py", 312, 'quality.get("metrics")'),
        _verify("cinesort/domain/quality_score.py", 1632, '"detected"'),
    ],
    extra={"producer_detected_subkeys": sorted(detected_keys)},
)

# ===========================================================================
# F-V8-FILMVIEW-CAND / DIR : candidates[0].confidence_label/.overview/.director
# absents du dataclass core.Candidate.
# ===========================================================================
from cinesort.domain import core  # noqa: E402

cand_fields = {f.name for f in dataclasses.fields(core.Candidate)}
cand_consumer = set()
# candidates[0]?.x ou topCandidate.x ou candidates[0].x
for m in re.finditer(r"(?:candidates\[0\]\??\.|topCandidate\.)([A-Za-z_][A-Za-z0-9_]*)", fd_src):
    cand_consumer.add(m.group(1))
emit(
    "F-V8-FILMVIEW-CAND",
    consumer=cand_consumer,
    producer=cand_fields,
    mismatch=cand_consumer - cand_fields,
    broken=(
        "film-detail.js lit candidates[0].confidence_label / .overview / .director "
        "mais core.Candidate n'a que {title,year,source,tmdb_id,poster_url,score,note,"
        "tmdb_collection_id,tmdb_collection_name} -> bloc TMDb fiche film affiche "
        "Confiance='?', pas de Synopsis, pas de Realisateur dans le hero."
    ),
    verify=[
        _verify(FD, 137, "candidates[0]?.director"),
        _verify(FD, 333, "confidence_label"),
        _verify(FD, 334, ".overview"),
        _verify("cinesort/domain/core.py", 379, "class Candidate"),
    ],
)

# F-V8-FILMVIEW-DIR : director lu sur candidates[0] (hero L137) alors que le
# backend l'expose en TOP-LEVEL data.director (film_support.py:418).
top_level_film = set(_toplevel_dict_keys(_slice("cinesort/ui/api/film_support.py", 406, 423)))
emit(
    "F-V8-FILMVIEW-DIR",
    consumer={"director(candidates[0])"},
    producer={f"director(top-level)" if "director" in top_level_film else "director(ABSENT)"},
    mismatch={"candidates[0].director != data.director"},
    broken=(
        "Hero fiche film lit candidates[0]?.director (L137) — toujours undefined "
        "car Candidate n'a pas de director. Le backend met le realisateur en "
        "TOP-LEVEL data.director (film_support.py:418, via _fetch_tmdb_extras). "
        "Le hero ignore data.director -> realisateur jamais affiche."
    ),
    verify=[
        _verify(FD, 137, "candidates[0]?.director"),
        _verify("cinesort/ui/api/film_support.py", 418, '"director": director'),
    ],
)

# ===========================================================================
# F-V8-PERCEPT-DISPLAY : perceptual-modal lit d.codec/width/grain_analysis/
# breakdown/hdr_analysis top-level ; producer get_perceptual_report niche sous
# metrics et n'emet pas codec/probe ; hdr_analysis absent du to_dict models.py.
# ===========================================================================
PM = "web/dashboard/components/perceptual-modal.js"
pm_src = _read(PM)
percept_consumer = set(re.findall(r"\bd\.([A-Za-z_][A-Za-z0-9_]*)", pm_src))
# producer : return dict de get_perceptual_report (perceptual.py:357-375)
percept_report = _slice("cinesort/infra/db/repositories/perceptual.py", 357, 375)
percept_producer = set(_keys_from_dict_literal(percept_report))
# focus : les cles d'AFFICHAGE probe/video que le modal lit mais que le report
# ne fournit pas (codec/width/height/grain_analysis/hdr_analysis/breakdown/bitrate_kbps)
focus = {"codec", "width", "height", "grain_analysis", "hdr_analysis", "breakdown", "bitrate_kbps", "bit_depth"}
emit(
    "F-V8-PERCEPT-DISPLAY",
    consumer=sorted(focus & percept_consumer),
    producer=percept_producer,
    mismatch=(focus & percept_consumer) - percept_producer,
    broken=(
        "perceptual-modal.js lit d.codec/d.width/d.height/d.grain_analysis/"
        "d.breakdown/d.hdr_analysis au TOP-LEVEL de `details`, mais "
        "get_perceptual_report (perceptual.py:357) ne renvoie que "
        "{visual_score,audio_score,global_score,metrics,settings_used,...} : "
        "grain_analysis est NICHE dans metrics (models.to_dict), codec/width/probe "
        "ne sont pas fournis -> Codec='—', Resolution=0x0, HDR='sdr', grain '—'."
    ),
    verify=[
        _verify(PM, 294, "d.codec"),
        _verify(PM, 290, "d.grain_analysis"),
        _verify(PM, 292, "d.hdr_analysis"),
        _verify(PM, 375, "d.breakdown"),
        _verify("cinesort/ui/api/perceptual_support.py", 123, '"details": report'),
        _verify("cinesort/infra/db/repositories/perceptual.py", 364, '"metrics": metrics'),
    ],
)

# [10]-hdr : hdr_analysis absent du to_dict composite (models.py:382)
percept_todict = _slice("cinesort/domain/perceptual/models.py", 382, 397)
percept_todict_keys = set(_keys_from_dict_literal(percept_todict))
emit(
    "F-V8-PERCEPT-HDR",
    consumer={"hdr_analysis"},
    producer=percept_todict_keys,
    mismatch={"hdr_analysis"} - percept_todict_keys,
    broken=(
        "perceptual-modal.js:292 lit d.hdr_analysis mais le to_dict du score "
        "perceptuel composite (models.py:382) n'emet que video_perceptual / "
        "grain_analysis / audio_perceptual : aucune cle hdr_analysis -> la cellule "
        "HDR du modal retombe toujours sur 'sdr'."
    ),
    verify=[
        _verify(PM, 292, "d.hdr_analysis"),
        _verify("cinesort/domain/perceptual/models.py", 389, '"grain_analysis"'),
    ],
    extra={"note": "grain_analysis present mais niche sous metrics; hdr_analysis totalement absent"},
)

# ===========================================================================
# F-V9-DUP-SCALE : doublons.js lit total_score_a/b comme un score ; producer
# duplicate_compare.py:142/149 = somme de points h2h (criteria), pas /100.
# ===========================================================================
DB = "web/dashboard/views/doublons.js"
db_src = _read(DB)
score_consumer = set(re.findall(r"comparison\.(total_score_[ab])", db_src))
score_producer_src = _slice("cinesort/domain/duplicate_compare.py", 142, 156)
score_producer = set(re.findall(r"\b(total_score_[ab])=", score_producer_src))
emit(
    "F-V9-DUP-SCALE",
    consumer=score_consumer,
    producer=score_producer,
    mismatch=set(),  # les cles MATCHENT, mais l'ECHELLE diverge
    broken=(
        "doublons.js:297 fait Math.round(Number(comparison.total_score_a)) en le "
        "traitant comme un score; or total_score_a = sum(max(0,points_delta)) sur "
        "les criteres (duplicate_compare.py:142) = total de POINTS tete-a-tete, "
        "borne par le nb de criteres (~7), PAS un score/100. Affichage 'X/100' "
        "trompeur : un gagnant net montre ~5-7 au lieu de ~95."
    ),
    verify=[
        _verify(DB, 297, "total_score_a"),
        _verify("cinesort/domain/duplicate_compare.py", 142, "score_a = sum(max(0, c.points_delta)"),
        _verify("cinesort/domain/duplicate_compare.py", 149, "total_score_a=score_a"),
    ],
    extra={"scale_kind": "consumer=score/100 attendu ; producer=somme points h2h (max ~ nb criteres)"},
)

# ===========================================================================
# F-V9-DUP-DECISION : doublons.js lit g.winner_decided ; jamais emis par le back.
# ===========================================================================
back_files = []
for dp, _dn, fns in os.walk(os.path.join(ROOT, "cinesort")):
    for fn in fns:
        if fn.endswith(".py"):
            back_files.append(os.path.join(dp, fn))
winner_decided_hits = []
for f in back_files:
    try:
        with open(f, encoding="utf-8") as fh:
            if "winner_decided" in fh.read():
                winner_decided_hits.append(os.path.relpath(f, ROOT))
    except OSError:
        pass
wd_consumer = set(re.findall(r"\.(winner_decided)\b", db_src))
emit(
    "F-V9-DUP-DECISION",
    consumer=wd_consumer,
    producer=set(),  # 0 hit backend
    mismatch=wd_consumer,
    broken=(
        "doublons.js:194/196 filtre les groupes sur g.winner_decided (onglets "
        "'En attente' / 'Decides'), mais AUCUN module cinesort/ n'emet jamais "
        "winner_decided -> tous les groupes restent 'pending', l'onglet 'Decides' "
        "est toujours vide meme apres avoir tranche."
    ),
    verify=[
        _verify(DB, 194, "winner_decided"),
        _verify(DB, 196, "winner_decided"),
        f"backend grep winner_decided -> {winner_decided_hits or '0 occurrence'}",
    ],
    extra={"backend_files_with_winner_decided": winner_decided_hits},
)

# ===========================================================================
# F-V9-DUP-UNITS : 3 formatters de taille divergents (labels Mo/Go vs Mio/Gio
# vs delegation core/format).
# ===========================================================================
def _grab_fmt(rel: str, anchor_line: int):
    ls = _lines(rel)
    chunk = "\n".join(ls[anchor_line - 1 : anchor_line + 6])
    labels = re.findall(r'`?\$\{[^}]*\}\s*(Mi?o|Gi?o)`|"(Mi?o|Gi?o)"|(Mi?o|Gi?o)`', chunk)
    flat = sorted({x for tup in labels for x in tup if x})
    deleg = "fmtBytes" in chunk or "_fmtBytesShared" in chunk
    return {"anchor": f"{rel}:{anchor_line}", "labels": flat, "delegates_to_shared": deleg,
            "snippet": ls[anchor_line - 1].strip()[:80]}
fmt1 = _grab_fmt(DB, 100)
fmt2 = _grab_fmt("web/dashboard/components/duplicate-comparator-modal.js", 57)
fmt3 = _grab_fmt("web/dashboard/views/library/lib-duplicates.js", 215)
emit(
    "F-V9-DUP-UNITS",
    consumer={"_fmtSize(doublons)", "_fmtSize(comparator-modal)", "_fmtSize(lib-duplicates)"},
    producer={"taille en octets (bytes) — meme source"},
    mismatch={"3 formatters incoherents pour la MEME valeur octets"},
    broken=(
        "3 implementations independantes de _fmtSize : doublons.js:100 affiche "
        "'Mo'/'Go' (label decimal mais division 1024^N), comparator-modal.js:57 "
        "affiche 'Mio'/'Gio' (base 1024 corrigee), lib-duplicates.js:215 delegue a "
        "fmtBytes (core/format.js, locale-aware) -> meme fichier affiche 3 tailles "
        "avec 3 unites differentes selon l'ecran."
    ),
    verify=[
        _verify(DB, 100, "function _fmtSize"),
        _verify("web/dashboard/components/duplicate-comparator-modal.js", 57, "function _fmtSize"),
        _verify("web/dashboard/views/library/lib-duplicates.js", 215, "function _fmtSize"),
    ],
    extra={"formatters": [fmt1, fmt2, fmt3]},
)

# ===========================================================================
# F-V4B-DUP1 : _quality_info_for_row ne renvoie que {score,tier} ;
# duplicate-comparator lit qualityA.codec/resolution/etc.
# ===========================================================================
qinfo_src = _slice("cinesort/ui/api/run_flow_support.py", 1438, 1447)
qinfo_keys = set(re.findall(r'"([a-z_]+)":', qinfo_src))
# consumer : ce que le modal/doublons lit sur quality_a / quality_b
cm_src = _read("web/dashboard/components/duplicate-comparator-modal.js")
q_consumer = set(re.findall(r"quality_[ab]\.([A-Za-z_][A-Za-z0-9_]*)", cm_src + db_src))
q_consumer |= set(re.findall(r"quality[AB]\.([A-Za-z_][A-Za-z0-9_]*)", cm_src + db_src))
emit(
    "F-V4B-DUP1",
    consumer=q_consumer,
    producer=qinfo_keys,
    mismatch=q_consumer - qinfo_keys,
    broken=(
        "_quality_info_for_row (run_flow_support.py:1446) ne renvoie que "
        "{'score':int,'tier':str}. Tout champ de qualite detaille (codec, "
        "resolution, bitrate...) lu cote front sur quality_a/quality_b est "
        "absent -> colonnes de comparaison qualite vides hormis score/tier."
    ),
    verify=[
        _verify("cinesort/ui/api/run_flow_support.py", 1446, '"score": int(qr.get("score")'),
    ],
    extra={"producer_keys_exhaustifs": sorted(qinfo_keys)},
)

# ===========================================================================
# F-V7-INSIGHT-ROUTE : accueil.js _INSIGHT_ROUTE_BY_TYPE keys vs types emis par
# _compute_active_insights (dashboard_support.py).
# ===========================================================================
AC = "web/dashboard/views/accueil.js"
ac_src = _read(AC)
route_block = re.search(r"_INSIGHT_ROUTE_BY_TYPE\s*=\s*\{(.*?)\}", ac_src, re.S)
route_keys = set(re.findall(r"([a-z_]+)\s*:", route_block.group(1))) if route_block else set()
ds_src = _read("cinesort/ui/api/dashboard_support.py")
# types emis par le producteur d'insights (fonction _compute_active_insights)
insight_types = set(re.findall(r'"type":\s*"([a-z_]+)"', ds_src))
emit(
    "F-V7-INSIGHT-ROUTE",
    consumer=route_keys,
    producer=insight_types,
    mismatch=route_keys & insight_types and (route_keys - insight_types) or route_keys,
    broken=(
        "accueil.js:524 route via _INSIGHT_ROUTE_BY_TYPE[insight.type] avec les cles "
        "{duplicates_probable,films_not_identified,films_low_confidence,subs_missing_fr,"
        "omdb_disagreements,quality_reject,health_low,sagas_incomplete}, mais le backend "
        "emet type in {run_in_progress,new_rejects,duplicates_to_resolve,dnr_partial,"
        "new_platinum_month}. INTERSECTION = 0 -> tout insight retombe sur le fallback "
        "/bibliotheque, les routes specifiques sont mortes."
    ),
    verify=[
        _verify(AC, 507, "_INSIGHT_ROUTE_BY_TYPE"),
        _verify(AC, 524, "_INSIGHT_ROUTE_BY_TYPE[insight.type"),
        _verify("cinesort/ui/api/dashboard_support.py", 1493, '"type": "run_in_progress"'),
    ],
    extra={"intersection": sorted(route_keys & insight_types)},
)

# ===========================================================================
# F-V7-INSIGHT-SUBS : qualite.js cherche un insight type/code includes
# 'subs_missing' ; aucun type emis ne le contient.
# ===========================================================================
QU = "web/dashboard/views/qualite.js"
qu_src = _read(QU)
subs_match = [ln for ln in qu_src.splitlines() if "subs_missing" in ln]
subs_in_types = sorted(t for t in insight_types if "subs_missing" in t)
emit(
    "F-V7-INSIGHT-SUBS",
    consumer={'insight.type/code includes "subs_missing"'},
    producer=insight_types,
    mismatch={"subs_missing"} if not subs_in_types else set(),
    broken=(
        "qualite.js:333 cherche insights.find(i => (i.type||i.code).includes('subs_missing')) "
        "mais aucun type d'insight backend ne contient 'subs_missing' "
        f"(types={sorted(insight_types)}) -> compteur 'Subs FR manquants' toujours '—'. "
        "Le fallback librarian suggestion (id includes 'subs_missing') echoue aussi : "
        "librarian emet l'id 'missing_subtitles' (cf F-V8-LIBRARIAN-ROUTE)."
    ),
    verify=[
        _verify(QU, 333, "subs_missing"),
        _verify(QU, 336, "subs_missing"),
    ],
    extra={"qualite_lines": [l.strip()[:90] for l in subs_match][:4]},
)

# ===========================================================================
# F-V8-LIBRARIAN-ROUTE : librarian.py ids vs front (accueil route map + qualite).
# ===========================================================================
lib_src = _read("cinesort/domain/librarian.py")
lib_ids = set(re.findall(r'"id":\s*"([a-z_]+)"', lib_src))
emit(
    "F-V8-LIBRARIAN-ROUTE",
    consumer=route_keys,
    producer=lib_ids,
    mismatch=route_keys - lib_ids,
    broken=(
        "librarian.generate_suggestions emet id in {codec_obsolete,duplicates,"
        "missing_subtitles,unidentified,low_resolution,collections_info}. Le front "
        "route map accueil (_INSIGHT_ROUTE_BY_TYPE) et qualite.js (id includes "
        "'subs_missing') utilisent un vocabulaire DIFFERENT : 'duplicates_probable' "
        "vs 'duplicates', 'subs_missing' vs 'missing_subtitles', "
        "'films_not_identified' vs 'unidentified' -> aucune suggestion ne route/"
        "matche correctement."
    ),
    verify=[
        _verify("cinesort/domain/librarian.py", 115, '"id": "duplicates"'),
        _verify("cinesort/domain/librarian.py", 168, '"id": "missing_subtitles"'),
        _verify("cinesort/domain/librarian.py", 189, '"id": "unidentified"'),
    ],
    extra={"librarian_ids": sorted(lib_ids), "front_route_keys": sorted(route_keys),
           "intersection": sorted(route_keys & lib_ids)},
)

# ===========================================================================
# F-V8-INSIGHT-NOTIF : emit_from_insights lit ins['code'] ; les insights
# dashboard n'ont qu'un 'type' -> 0 notification creee.
# ===========================================================================
notif_src = _read("cinesort/ui/api/notifications_support.py")
notif_reads_code = 'ins.get("code")' in notif_src
insight_has_code = '"code"' in ds_src and bool(re.search(r'"code":\s*"', ds_src))
emit(
    "F-V8-INSIGHT-NOTIF",
    consumer={"ins['code'] (notifications_support)"},
    producer={"type" if insight_types else "?"},
    mismatch={"code"} if notif_reads_code else set(),
    broken=(
        "emit_from_insights (notifications_support.py:254) fait "
        "code=str(ins.get('code')).strip(); if not code: continue. Or "
        "_compute_active_insights (dashboard_support.py:1711) cree des dicts avec "
        "la cle 'type' (pas 'code') et emit_from_insights est appele dessus "
        "(dashboard_support.py:1726) -> tous les insights sont skippes, AUCUNE "
        "notification miroir n'est jamais creee (write-only mort)."
    ),
    verify=[
        _verify("cinesort/ui/api/notifications_support.py", 254, 'ins.get("code")'),
        _verify("cinesort/ui/api/dashboard_support.py", 1726, "emit_from_insights"),
        _verify("cinesort/ui/api/dashboard_support.py", 1711, "_compute_active_insights"),
    ],
    extra={"insights_emit_code_literal": insight_has_code,
           "insights_emit_type": sorted(insight_types)},
)

# ===========================================================================
# F-V9-CACHE-STATS : stats_snapshot_for_cache omet films_rejected_*/
# root_level_films_seen/tv_episodes_seen/folders_rejected_scandir_error.
# ===========================================================================
snap_src = _slice("cinesort/app/plan_support_core.py", 168, 182)
snap_keys = set(re.findall(r'"([a-z_]+)":', snap_src))
stats_fields = {f.name for f in dataclasses.fields(core.Stats)}
expected_diag = {"films_rejected_ext", "films_rejected_size", "films_rejected_name",
                 "root_level_films_seen", "tv_episodes_seen", "folders_rejected_scandir_error"}
omitted = expected_diag - snap_keys
# tous existent bien sur le dataclass ?
on_dataclass = expected_diag & stats_fields
emit(
    "F-V9-CACHE-STATS",
    consumer=expected_diag,  # ce que le snapshot DEVRAIT capturer (champs reels du dataclass)
    producer=snap_keys,
    mismatch=omitted,
    broken=(
        "stats_snapshot_for_cache (plan_support_core.py:168) ne capture pas "
        "films_rejected_ext/size/name, root_level_films_seen, tv_episodes_seen, "
        "folders_rejected_scandir_error — pourtant champs reels de core.Stats. "
        "Sur un replan CACHE-HIT, ces compteurs de diagnostic scan repartent a 0 "
        "(consommes par dashboard scan_diagnostic L354-369 et run_flow L74) -> "
        "le panneau 'pourquoi des films ont ete rejetes' ment apres un cache-hit."
    ),
    verify=[
        _verify("cinesort/app/plan_support_core.py", 168, "def stats_snapshot_for_cache"),
        _verify("cinesort/domain/core.py", 353, "films_rejected_ext"),
        _verify("cinesort/domain/core.py", 358, "folders_rejected_scandir_error"),
        _verify("cinesort/ui/api/dashboard_support.py", 359, "folders_rejected_scandir_error"),
    ],
    extra={"champs_omis_mais_reels_sur_dataclass": sorted(on_dataclass & omitted)},
)

# ===========================================================================
# [11] historique.js duplicate groups : winner_label / size_savings absents du
# producer history_support.duplicates_decided ({title,year,winner}).
# ===========================================================================
HI = "web/dashboard/views/historique.js"
hi_src = _read(HI)
dup_block = _slice("cinesort/ui/api/history_support.py", 337, 343)
dup_producer = set(_keys_from_dict_literal(dup_block))
dup_consumer = set()
for m in re.finditer(r"\bg\.([A-Za-z_][A-Za-z0-9_]*)", hi_src):
    dup_consumer.add(m.group(1))
dup_focus = {"winner_label", "size_savings"}
emit(
    "F-HIST-DUP-11",
    consumer=sorted(dup_focus & dup_consumer),
    producer=dup_producer,
    mismatch=dup_focus - dup_producer,
    broken=(
        "historique.js:764 lit g.winner_label et :765 lit g.size_savings pour "
        "l'onglet Doublons de l'Inspecteur, mais duplicates_decided "
        "(history_support.py:337) n'emet que {title,year,winner(=row_id)} -> "
        "'winner' tombe sur l'id brut, et 'Go recuperes' n'apparait jamais."
    ),
    verify=[
        _verify(HI, 764, "g.winner_label"),
        _verify(HI, 765, "g.size_savings"),
        _verify("cinesort/ui/api/history_support.py", 341, '"winner": str(dec.get("winner_row_id")'),
    ],
    extra={"producer_keys": sorted(dup_producer)},
)

# ===========================================================================
# [12] historique.js films : decision / status / is_duplicate absents du producer
# history_support.films ({film_id,title,year,tier,score}).
# ===========================================================================
films_block = _slice("cinesort/ui/api/history_support.py", 320, 328)
films_producer = set(_keys_from_dict_literal(films_block))
film_consumer = set()
for m in re.finditer(r"\bfilm\.([A-Za-z_][A-Za-z0-9_]*)", hi_src):
    film_consumer.add(m.group(1))
film_focus = {"decision", "status", "is_duplicate"}
emit(
    "F-HIST-FILM-12",
    consumer=sorted(film_focus & film_consumer),
    producer=films_producer,
    mismatch=film_focus - films_producer,
    broken=(
        "historique.js:651 lit film.decision || film.status et :652 lit "
        "film.is_duplicate pour le badge de statut, mais le producer films "
        "(history_support.py:320) n'emet que {film_id,title,year,tier,score} -> "
        "le badge statut/doublon de l'onglet Films est toujours faux/vide."
    ),
    verify=[
        _verify(HI, 651, "film.decision"),
        _verify(HI, 652, "film.is_duplicate"),
        _verify("cinesort/ui/api/history_support.py", 322, '"film_id": rid'),
    ],
    extra={"producer_keys": sorted(films_producer)},
)

# ===========================================================================
# RESUME final
# ===========================================================================
summary = {fid: {"mismatch": b["mismatch_consumer_minus_producer"]} for fid, b in results.items()}
print("=" * 78)
print("RESUME:", json.dumps({
    "findings": list(results.keys()),
    "all_have_nonempty_mismatch": all(
        b["mismatch_consumer_minus_producer"] for fid, b in results.items()
        if fid not in ("F-V9-DUP-SCALE", "F-V9-DUP-UNITS", "F-V8-FILMVIEW-DIR")
    ),
    "per_finding_mismatch": summary,
}, ensure_ascii=False))
