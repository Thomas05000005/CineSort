export const meta = {
  name: 'filet-f3-security',
  description: 'Filet adversarial securite F3 (surface reseau + execution) sur CineSort',
  phases: [
    { title: 'Find', detail: '3 finders securite (guards GET/POST, exec binaire, origine/bind)' },
    { title: 'Verify', detail: 'panel 3 sceptiques asymetriques + 2 leurres calibration' },
  ],
}

const REPO = 'C:/Users/blanc/projects/CineSort'

const CONTEXT = `
CineSort = app desktop locale Windows, REST sur 127.0.0.1:8642 (cinesort/infra/rest_server.py,
HTTP stdlib). INVARIANT : bypass auth loopback LEGITIME (client 127.0.0.1 + bind 127.0.0.1) — ne le
considere PAS comme une faille. Un attaquant local a deja le shell.
4 fixes F3 VIENNENT D'ETRE APPLIQUES (NE PAS les re-signaler comme bugs, mais cherche ce qu'ils ONT
RATE / un residu) :
- R8-030 : GET /api/poster?force=1 (purge cache + re-DL TMDb) neutralise si cross-site
  (_is_cross_site_get = Origin interdit OU Sec-Fetch-Site:cross-site). rest_server.py _handle_get.
- R8-031 : _allowed_origin n'autorise le loopback que sur _own_port() (port d'ecoute). rest_server.py.
- R8-032 : perceptual_support.py resout ffprobe via safe_tool_path (whitelist nom, infra/probe/tooling.py).
- R8-033 : ffmpeg_runner.resolve_ffmpeg_path refuse le sibling d'un chemin non-ffprobe.
Repo: ${REPO}. Lis le VRAI code (Read/Grep). Severite reelle (un prereq "ecrire settings.json" = local
= deja shell = LOW). Defaut = pas un bug si doute.`

const FINDERS = [
  { key: 'guards', prompt: `${CONTEXT}
PERIMETRE : couverture des gardes auth/CSRF/rate-limit sur les endpoints.
Lis rest_server.py : do_GET/_handle_get (toutes les branches : /api/health, /api/spec, /api/poster,
/dashboard, /shared, /locales, 404), do_POST (dispatch + _is_forbidden_cross_site + _is_rate_limited +
_check_auth), do_OPTIONS. CHERCHE : un GET a EFFET DE BORD non gate (autre que force, deja fixe) ; un
endpoint qui contourne une garde appliquee ailleurs (incoherence) ; /api/spec qui fuite la surface a un
LAN non authentifie ; un static file path-traversable. Ignore le bypass loopback legitime.` },
  { key: 'exec', prompt: `${CONTEXT}
PERIMETRE : execution de binaires externes depuis une donnee non fiable.
Grep tout subprocess/tracked_run/Popen + tout *_path lu depuis settings et passe en argv[0]
(ffprobe, ffmpeg, mediainfo, autres). Lis cinesort/infra/probe/* , cinesort/domain/perceptual/* ,
cinesort/app/*. CHERCHE : un site qui exec un binaire configure SANS passer par safe_tool_path /
_binary_name_allowed / resolve_ffmpeg_path durci (asymetrie residuelle save/exec) ; un autre outil
configurable (mediainfo_path ?) exec sans whitelist ; un argv ou un chemin media injecte sans garde.` },
  { key: 'origin', prompt: `${CONTEXT}
PERIMETRE : origine, CSRF, bind reseau.
Lis rest_server.py _allowed_origin / _is_forbidden_cross_site / _is_cross_site_get / _own_port /
_check_auth / start() / RestApiServer.__init__ (host/port/MIN_LAN_TOKEN_LENGTH) + cinesort_api.py
(construction RestApiServer, host="0.0.0.0" si rest_api_enabled). CHERCHE : une origine non-loopback
acceptee a tort ; un Sec-Fetch contournable ; un bind 0.0.0.0 par accident / token LAN trop faible ;
_own_port spoofable via Host menant a accepter un mauvais port ; le bypass actif en 0.0.0.0.` },
]

const FINDER_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'string' } } },
  required: ['findings'],
}

const VERIFY_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['REAL', 'REFUTED'] },
    confidence: { type: 'string' },
    reason: { type: 'string' },
  },
  required: ['verdict', 'confidence', 'reason'],
}

phase('Find')
const finderResults = await parallel(FINDERS.map((f) => () =>
  agent(`${f.prompt}

Retourne {findings:[...]}. CHAQUE finding = UNE string : "SEV|fichier:ligne|symptome|cause|vecteur".
SEV in {HIGH,MED,LOW}. Si rien de reel: findings=[]. <200 mots de raisonnement interne, sortie compacte.`,
    { label: `find:${f.key}`, phase: 'Find', schema: FINDER_SCHEMA })))

const found = []
finderResults.filter(Boolean).forEach((r, i) => {
  (r.findings || []).forEach((s, j) => found.push({ id: `${FINDERS[i].key}-${j}`, claim: String(s), decoy: false }))
})

// 2 leurres de calibration (faux connus) — mesurent le taux de faux positifs du panel.
const decoys = [
  { id: 'DECOY-1', decoy: true, claim: `HIGH|rest_server.py:_check_auth|le bypass loopback autorise n'importe quel client distant a sauter l'auth|bind 0.0.0.0 accepte 127.0.0.1 spoofe|RCE distant` },
  { id: 'DECOY-2', decoy: true, claim: `HIGH|poster_proxy.py:serve_poster|le proxy poster suit n'importe quelle URL fournie en query (open-relay/SSRF total)|aucune validation id/size|SSRF arbitraire` },
]
const candidates = [...found, ...decoys]

phase('Verify')
const verdicts = await parallel(candidates.map((c) => () =>
  parallel([0, 1, 2].map((k) => () =>
    agent(`Tu es un sceptique securite (lentille ${['correctness-code', 'atteignable-runtime', 'intentionnel-ou-deja-mitige'][k]}).
Repo: ${REPO}. Lis le VRAI code concerne. Re-DERIVE seul si cette claim securite est un VRAI defaut
exploitable NON deja corrige. INVARIANT : le bypass loopback legitime (127.0.0.1+bind 127.0.0.1) n'est PAS
une faille. Defaut = REFUTED si doute/prereq "deja shell local"/deja mitige.

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
const reliable = decoys_leaked === 0

log(`Filet F3 : ${found.length} candidats reels + ${decoys.length} leurres ; survivants=${survivors.length} ; leurres passes=${decoys_leaked}`)

return {
  reliable,
  candidates_count: found.length,
  decoys_leaked,
  survivors: survivors.map((s) => ({ id: s.id, claim: s.claim, votes: `${s.votes_real}/${s.votes_total}` })),
  all_verdicts: decoated.map((v) => ({ id: v.id, decoy: v.decoy, votes_real: v.votes_real, votes_total: v.votes_total, survived: v.survived, claim: v.claim.slice(0, 90) })),
}
