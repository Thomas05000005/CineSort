"""R8 F5 — DIFFÉRENTIEL R8-049/051/052 : _compute_active_insights émet les 8 types MÉTIER.

AVANT : le producteur n'émettait que des types « physiques » (new_rejects,
duplicates_to_resolve…) qu'AUCUNE route _INSIGHT_ROUTE_BY_TYPE (accueil.js) ni
notification ne reconnaissait -> panneaux morts, clics non routés, miroir Centre
de notifications vide. APRÈS : 7/8 types métier dérivés du bibliothécaire
(quality_reject, duplicates_probable, films_not_identified, subs_missing_fr,
sagas_incomplete, films_low_confidence, health_low). omdb_disagreements reste
dormant (aucune comparaison OMDb↔TMDb n'est calculée — résidu documenté).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f5_insights_8types_diff.py
"""

import cinesort.ui.api.dashboard_support as d

FRONT_METIER = {
    "quality_reject",
    "duplicates_probable",
    "films_not_identified",
    "subs_missing_fr",
    "sagas_incomplete",
    "films_low_confidence",
    "health_low",
    "omdb_disagreements",
}


class FakePerc:
    def list_perceptual_reports(self, run_id=None):
        return [{"global_tier_v2": "reject"}]

    def count_v2_warnings_flag(self, flag=None, run_ids=None):
        return 0

    def count_v2_tier_since(self, tier=None, since_ts=None):
        return 0


class FakeRun:
    def list_runs(self, limit=1):
        return []


class FakeStore:
    perceptual = FakePerc()
    run = FakeRun()


librarian = {
    "health_score": 35,
    "low_confidence_count": 4,
    "suggestions": [
        {"id": "duplicates", "count": 3, "message": "3 doublons"},
        {"id": "unidentified", "count": 2, "message": "2 non identifiés"},
        {"id": "missing_subtitles", "count": 5, "message": "5 sans sous-titres FR"},
        {"id": "collections_info", "count": 7, "message": "7 dans des sagas"},
    ],
}

avant = {i["type"] for i in d._compute_active_insights(object(), FakeStore(), ["rid1"], {}, {})} & FRONT_METIER
apres = {i["type"] for i in d._compute_active_insights(object(), FakeStore(), ["rid1"], {}, librarian)} & FRONT_METIER
print(f"AVANT (librarian non passé) : {len(avant)}/8 types métier -> {sorted(avant)}")
print(f"APRÈS (librarian dérivé)    : {len(apres)}/8 types métier -> {sorted(apres)}")
print(f"VERDICT : {'CORRIGE' if len(apres) >= 6 else 'INCOMPLET'} (omdb_disagreements dormant = pas de source)")
