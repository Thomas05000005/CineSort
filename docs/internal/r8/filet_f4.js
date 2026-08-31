export const meta = {
  name: 'filet-f4-measure',
  description: 'Filet adversarial F4 (couche mesure/analyse) sur CineSort — résultats faux silencieux',
  phases: [
    { title: 'Find', detail: '3 finders (mesure du vide, cache empoisonnable, échelle/unité fausse)' },
    { title: 'Verify', detail: 'panel 3 sceptiques asymétriques + 2 leurres calibration' },
  ],
}

const REPO = 'C:/Users/<utilisateur>/projects/CineSort'

const CONTEXT = `
CineSort = app desktop Windows de tri de films. F4 = RÉSULTATS FAUX SILENCIEUX (l'app affiche
une valeur fausse sans planter). 11 fixes F4 VIENNENT D'ÊTRE FAITS (NE PAS les re-signaler, mais
cherche ce qu'ils ONT RATÉ / un résidu de MÊME CLASSE ailleurs) :
- R8-034 loudnorm -v quiet->info ; R8-035 crest/dynrange par canal ; R8-036 filtre vidéo
  metadata=mode=print + clés lavfi (avant : 0 frame -> block/blur=0 -> score 95 fabriqué).
- R8-038 bitrate audio bps->kbps inconditionnel ; R8-039 _best_audio_track codec-aware.
- R8-040 résidu DD5.1 ; R8-041 TMDb cache vide non empoisonnant ; R8-042 doublons /100 -> points ;
  R8-043 hdr_analysis exposé ; R8-044 mkv_title par tokens ; R8-037 cancel perceptuel câblé.
- R8-096 DÉFÉRÉ (connu) : seuils BLUR_* (0.01-0.10) != échelle blurdetect réelle (4-16) -> score
  blur saturé. NE PAS le re-signaler, c'est déjà enregistré.
Repo: ${REPO}. Lis le VRAI code (Read/Grep). Sévérité réelle. Défaut = pas un bug si doute.`

const FINDERS = [
  { key: 'void', prompt: `${CONTEXT}
PÉRIMÈTRE : "mesure du vide" — une métrique dont l'ABSENCE/échec mappe vers une valeur FLATTEUSE
(score parfait/neutre) au lieu de unknown. Lis cinesort/domain/perceptual/* (audio_perceptual,
video_analysis, composite_score, composite_score_v2, grain_analysis, hdr_analysis, models),
cinesort/domain/quality_score.py. CHERCHE : un _score_*(0)=valeur haute quand la donnée manque ;
un argv ffmpeg/ffprobe muet (sans metadata=print / mauvais -v) ; un parse regex sur des clés qui
ne sortent jamais ; un défaut de dataclass (0/None) traité comme "bon" par le scoring. (R8-036/034/035
déjà faits — cherche un AUTRE site du même type, ex. astats RMS/peak, signalstats, grain, ssim.)` },
  { key: 'cache', prompt: `${CONTEXT}
PÉRIMÈTRE : cache/persistance qui stocke un résultat NÉGATIF/VIDE/ERREUR comme s'il était valide
(comme R8-041 TMDb []). Lis cinesort/infra/tmdb_client.py, infra/integrations/poster_proxy.py,
infra/probe/disk_cache.py, infra/probe/service.py (cache probe), plan_support_core (row cache),
infra/db caches. CHERCHE : un _cache_set(cle, vide/None/erreur) puis lecture "is not None" ;
un TTL long sur un résultat négatif ; un cache qui ne distingue pas "pas trouvé" de "pas encore
cherché" ; un fallback stale qui sert une erreur.` },
  { key: 'scale', prompt: `${CONTEXT}
PÉRIMÈTRE : échelle/unité FAUSSE (dérive sémantique) — une valeur réelle rendue sur une mauvaise
échelle/unité (comme R8-042 points/100, R8-038 bps/kbps). Lis cinesort/domain/quality_score.py,
domain/duplicate_compare.py, web/dashboard/views/doublons.js, components/perceptual-modal.js,
domain/perceptual/constants.py (seuils vs échelle réelle des métriques), formatage taille/bitrate
(_fmtSize, fmtBytes, conversions). CHERCHE : un seuil calibré pour une échelle != celle de la
métrique ; un /100 ou % sur une valeur qui n'est pas 0..100 ; bps vs kbps vs Mbps ; Go vs Gio ;
un score affiché dans une mauvaise unité. (NE PAS re-signaler R8-096 seuils blur, déjà déféré.)` },
]

const FINDER_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'string' } } },
  required: ['findings'],
}
const VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { verdict: { type: 'string', enum: ['REAL', 'REFUTED'] }, confidence: { type: 'string' }, reason: { type: 'string' } },
  required: ['verdict', 'confidence', 'reason'],
}

phase('Find')
const finderResults = await parallel(FINDERS.map((f) => () =>
  agent(`${f.prompt}

Retourne {findings:[...]}. CHAQUE finding = UNE string : "SEV|fichier:ligne|symptome|cause|valeur_fausse->correcte".
SEV in {HIGH,MED,LOW}. Si rien de réel: findings=[]. <200 mots interne, sortie compacte.`,
    { label: `find:${f.key}`, phase: 'Find', schema: FINDER_SCHEMA })))

const found = []
finderResults.filter(Boolean).forEach((r, i) => {
  (r.findings || []).forEach((s, j) => found.push({ id: `${FINDERS[i].key}-${j}`, claim: String(s), decoy: false }))
})

const decoys = [
  { id: 'DECOY-1', decoy: true, claim: `HIGH|quality_score.py|le score qualité global est toujours 0 pour tous les films (jamais calculé)|fonction _compute jamais appelée|0->réel` },
  { id: 'DECOY-2', decoy: true, claim: `HIGH|tmdb_client.py|le cache TMDb stocke la clé API en clair dans chaque entrée|fuite secret|clé exposée` },
]
const candidates = [...found, ...decoys]

phase('Verify')
const verdicts = await parallel(candidates.map((c) => () =>
  parallel([0, 1, 2].map((k) => () =>
    agent(`Tu es un sceptique (lentille ${['correctness-du-code', 'atteignable-runtime', 'intentionnel-ou-déjà-corrigé'][k]}).
Repo: ${REPO}. Lis le VRAI code concerné. Re-DÉRIVE seul si cette claim « résultat faux silencieux »
est un VRAI défaut NON déjà corrigé (R8-034..044 faits ; R8-096 seuils blur déféré). Défaut = REFUTED
si doute / déjà corrigé / intentionnel.

CLAIM: ${c.claim}

Retourne {verdict:REAL|REFUTED, confidence, reason}.`,
      { label: `verify:${c.id}:${k}`, phase: 'Verify', schema: VERIFY_SCHEMA })))
    .then((vs) => {
      const real = vs.filter(Boolean).filter((v) => v.verdict === 'REAL').length
      const total = vs.filter(Boolean).length
      return { ...c, votes_real: real, votes_total: total, survived: total > 0 && real >= 2, verdicts: vs }
    })))

const decoated = verdicts.filter(Boolean)
const decoys_leaked = decoated.filter((v) => v.decoy && v.survived).length
const survivors = decoated.filter((v) => !v.decoy && v.survived)
log(`Filet F4 : ${found.length} candidats + ${decoys.length} leurres ; survivants=${survivors.length} ; leurres passés=${decoys_leaked}`)

return {
  reliable: decoys_leaked === 0,
  candidates_count: found.length,
  decoys_leaked,
  survivors: survivors.map((s) => ({ id: s.id, claim: s.claim, votes: `${s.votes_real}/${s.votes_total}` })),
  all_verdicts: decoated.map((v) => ({ id: v.id, decoy: v.decoy, votes_real: v.votes_real, votes_total: v.votes_total, survived: v.survived, claim: v.claim.slice(0, 100) })),
}
