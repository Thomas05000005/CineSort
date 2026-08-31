export const meta = {
  name: 'recon-f5',
  description: 'Recon F5 — map des findings features-mortes/contrats/seams contre le code vivant',
  phases: [{ title: 'Recon', detail: '7 lecteurs parallèles (clusters A-G)' }],
}

const REPO = 'C:/Users/<utilisateur>/projects/CineSort'
const BASE = `Repo: ${REPO}. Lis le VRAI code (Read/Grep). Les numéros de ligne du registre peuvent avoir dérivé.
Pour CHAQUE finding : confirmé (yes/partial/no) + site fichier:ligne ACTUEL + cause racine + DÉCISION
recommandée (CÂBLER / RETIRER / ALIGNER-CONTRAT / FORK-DESIGN-à-signaler) + fix minimal + comment prouver le
différentiel (endpoint/payload/clé front↔back). Distingue feature attendue (câbler) vs vestige (retirer).`

const TASKS = [
  { key: 'C-film-detail', prompt: `${BASE}
DÉCISION PRODUIT D1 : SUPPRIMER la vue standalone web/dashboard/views/film-detail.js (route /film/:id) ;
garder UNIQUEMENT le composant web/dashboard/components/film-detail.js. Recon :
- Liste TOUTES les références à la vue standalone (route /film/:id dans app.js / router, imports, liens
  href/navigate vers /film/, mentions). Donne fichier:ligne de chacune.
- VÉRIFIE que le COMPOSANT components/film-detail.js est COMPLET : lit-il probe.detected.*, candidate.score,
  confidence, synopsis/overview, réalisateur/director, sections Vidéo/Audio/Sous-titres ? (R8-053/054/055 ne
  concernent QUE la vue standalone ; confirme que le composant est bon.)
- Signale toute DÉPENDANCE qui casserait si on retire la route (lien mort).` },
  { key: 'D-perceptual', prompt: `${BASE}
R8-056 SEAM perceptual display-path. perceptual-modal.js (~265) charge par DÉFAUT get_perceptual_details
(repositories/perceptual.py ~357) qui sert le report DB BRUT (métriques sous d.metrics, champs probe absents)
mais la modale lit d.codec/d.width/d.grain_analysis/d.breakdown top-level -> sections vides sur film en cache.
Recon : compare la forme servie par get_perceptual_details vs get_perceptual_report (à jour to_dict) vs ce que
la modale attend. Donne le fix : servir PARTOUT la forme aplatie que la modale attend (cohérent avec les fixes
F4 R8-034/035/036 : la forme doit exposer loudnorm/crest/dynrange/block/blur réels). Endpoints concernés.` },
  { key: 'E-doublons', prompt: `${BASE}
SEAM #4 doublons. Confirme :
- R8-057 DUP-DECISION : check_duplicates (run_flow_support.py ~1744) ne joint jamais winner_decided/winner_side
  -> badge « Décidé » disparaît au refresh (decidedCount=0). Décision persistée où ? (table/colonne). Fix :
  joindre la décision dans le payload check_duplicates. doublons.js ~194 (lecture).
- R8-058 DUP-UNITS : 3 formateurs de taille (doublons.js ~100, duplicate-comparator-modal.js ~57,
  lib-duplicates.js ~215). Quel helper centralisé EXISTE (nom + fichier) ? Les 3 doivent l'adopter.
- R8-059 DUP1 : _quality_info_for_row (run_flow_support.py ~1446) ne renvoie que {score,tier} ; doublons.js
  ~367 attend codec/résolution/audio. Fix : enrichir le payload.` },
  { key: 'F-cache-history', prompt: `${BASE}
Confirme :
- R8-060 CACHE-STATS : stats_snapshot_for_cache (plan_support_core.py ~168) capture 13 champs mais OMET
  films_rejected_ext/size/name, root_level_films_seen, tv_episodes_seen, folders_rejected_scandir_error ->
  round-trip à perte sur cache HIT (plan_support_core ~208 lecture). Donne les 2 listes de champs (écriture vs
  lecture) pour aligner. Le différentiel = round-trip sans perte.
- R8-061 HIST-DUP : history_support.py ~337 builder duplicates_decided ne produit que {title,year,winner} ;
  front lit g.winner_label + g.size_savings. Fix : ajouter les champs.
- R8-062 HIST-FILM : history_support.py ~317 builder films ne produit que {film_id,title,year,tier,score} ;
  front lit film.decision/.status/.is_duplicate. Fix : ajouter les champs.` },
  { key: 'B-insights', prompt: `${BASE}
SEAM #2 insights (vocabulaire producteur↔consommateur). Confirme :
- _compute_active_insights émet QUELS types exactement ? (grep la fonction). Liste les 5 types réels.
- R8-049 NOTIF : notifications_support.py ~254 emit_from_insights lit ins.get("code") jamais émis -> if not
  code: continue -> chaque insight sauté.
- R8-050 SUBS : qualite.js ~333 cherche .includes("subs_missing") ; back émet missing_subtitles.
- R8-051 ROUTE : accueil.js ~507 _INSIGHT_ROUTE_BY_TYPE keyé sur 8 types, 0/5 match les types émis.
- R8-052 LIBRARIAN-ROUTE : librarian.py 92-234, 4/6 suggestions id divergent de la map front.
Donne la grille de contrat : types ÉMIS vs types ATTENDUS (notif/subs/route). Décision : aligner le producteur
sur le vocabulaire front OU l'inverse ? (le moins de code mort, le plus de features vivantes).` },
  { key: 'A-dead-views', prompt: `${BASE}
Cluster vues mortes. Pour CHAQUE : est-ce une feature ATTENDUE (câbler/router) ou un VESTIGE (retirer) ?
- R8-045 ENRICH-DEAD : vue Enrichissement IA, aucune route app.js ; enrichment_facade n'expose pas
  get_status/apply_bulk. Feature réelle ou morte-née ? (grep la vue + la façade).
- R8-046 DEAD-01 : quality-simulator.js ~155 + custom-rules-editor.js ~457, hosts qij.js/quality.js morts
  (app.js redirige /qij->/accueil, /quality->/qualite). ~1100 l. code mort.
- R8-047 LIBWF-DEAD : initLibraryWorkflow, /library->/bibliotheque jamais montée.
- R8-048 INDEX-CMT : index.html ~92 commentaire trompeur.
Donne pour chacun : route réelle dans app.js, atteignable ou non, et recommandation RETIRER vs CÂBLER.` },
  { key: 'G-toggles', prompt: `${BASE}
Cluster config fantôme (toggles write-only, 0 consommateur). Pour CHAQUE : CÂBLER (vraie feature) / RETIRER
(vestige) / FORK-DESIGN-à-signaler (décision produit ambiguë) ? Confirme le « 0 consommateur » par grep.
- R8-063 cleanup_orphans + cleanup_empty_folders (parametres.js 151) absents de Config/build_cfg_from_settings.
- R8-064 auto_approve_enabled (parametres.js 105) : get_auto_approved_summary 0 appelant UI.
- R8-065 séparateur preset défaut + subtitle_lang_priority fantôme (vraie clé subtitle_expected_languages).
- R8-066 KPI-DUPGROUPS : traitement.js 245 <- dashboard_support.py 542, k.duplicates_groups absent des kpis.
- R8-067 animations_enabled (parametres.js 277) 0 consommateur DOM/CSS.
- R8-068 global_workers inerte. R8-069 desktop_notifications_enabled 0 conso. R8-070 retention_days ne purge
  rien (prune_disk_cache jamais appelé). R8-071 naming_template non lu. R8-072 effects_mode gap inverse.
Donne pour chacun la reco + le différentiel (toggle ON≠OFF mesurable si câblé ; disparu si retiré).` },
]

phase('Recon')
const SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    findings_status: { type: 'string' }, sites: { type: 'string' }, decision: { type: 'string' },
    fix_approach: { type: 'string' }, differential: { type: 'string' }, fork_design: { type: 'string' },
  },
  required: ['findings_status', 'sites', 'decision', 'fix_approach'],
}

const results = await parallel(TASKS.map((t) => () =>
  agent(`${t.prompt}

Retourne un objet : findings_status, sites (fichier:ligne actuels par finding), decision (CÂBLER/RETIRER/
ALIGNER/FORK-DESIGN par finding), fix_approach, differential, fork_design (liste des FORK-DESIGN à signaler).
<350 mots, précis sur le VRAI code.`,
    { label: `recon:${t.key}`, phase: 'Recon', schema: SCHEMA })
    .then((r) => ({ key: t.key, ...r }))))

return results.filter(Boolean)
