export const meta = {
  name: 'recon-f4',
  description: 'Recon F4 — confirme cause + site exact + approche de fix des 11 findings résultats-faux',
  phases: [{ title: 'Recon', detail: '8 lecteurs parallèles sur les 11 findings F4' }],
}

const REPO = 'C:/Users/<utilisateur>/projects/CineSort'
const BASE = `Repo: ${REPO}. Lis le VRAI code (Read/Grep) — les numéros de ligne du registre peuvent avoir dérivé,
donne le site EXACT actuel. Pour chaque finding : confirmé (yes/partial/no) + cause racine réelle + site
fichier:ligne actuel + approche de fix minimale + instrumentable avec un VRAI ffmpeg (yes/no/n-a).`

const TASKS = [
  { key: 'R8-034-035', prompt: `${BASE}
audio_perceptual.py (analyse perceptuelle AUDIO).
- R8-034 : ~L141-142 — un argv ffmpeg avec '-v quiet' (ou niveau qui tue le JSON loudnorm émis sur stderr/INFO)
  -> analyze_loudnorm renvoie None -> loudness EBU R128 jamais mesurée. Donne la commande argv exacte + comment
  le JSON loudnorm est censé être parsé, et quel niveau de verbosité le ferait apparaître.
- R8-035 : ~L234 — parse le bloc 'Overall' d'astats mais Crest factor / Dynamic range n'y sont QUE par canal
  (pas dans Overall) -> crest=dynrange=None -> 2 poids audio figés à 50. Donne le code de parsing exact + d'où
  lire crest/dynrange réellement (quel bloc/clé astats).` },
  { key: 'R8-036', prompt: `${BASE}
video_analysis.py (analyse perceptuelle VIDÉO), ~L90.
R8-036 : un filtre 'signalstats,blockdetect,blurdetect' SANS 'metadata=mode=print' -> 0 ligne de métadonnée
parsée -> blockiness_mean=blur_mean=0.0 -> _score_blockiness(0)=95 et _score_blur(0)=95 (parfait fabriqué).
Donne l'argv/filtre exact, comment les valeurs sont parsées (regex sur quelles clés lavfi.*), et où
_score_blockiness/_score_blur transforment 0 en 95. Confirme le pipeline blur/blockiness -> score visuel.` },
  { key: 'R8-037', prompt: `${BASE}
run_flow_support.py ~L564 (analyze_perceptual_batch) + l'API CineSortApi (_perceptual_cancel_event).
R8-037 : should_cancel n'est pas transmis à analyze_perceptual_batch ; api._perceptual_cancel_event jamais
assigné en prod -> les checks d'annulation sont inertes -> request_cancel n'arrête pas l'analyse perceptuelle.
Donne : signature de analyze_perceptual_batch (param should_cancel ?), où request_cancel pose le flag, où
_perceptual_cancel_event devrait être créé/passé, et le chemin de câblage minimal.` },
  { key: 'R8-038-039', prompt: `${BASE}
quality_score.py (scoring qualité).
- R8-038 : ~L563 _normalize_audio_bitrate_kbps divise par 1000 SEULEMENT si >10000 strict ; le bitrate est
  stocké en bps -> ~8000 bps (8 kbps) lu comme 8000 kbps -> bonus au lieu de malus (inversion de signe). Donne
  la fonction exacte + comment distinguer bps de kbps de façon robuste.
- R8-039 : ~L637 _best_audio_track = max(channels, bitrate) (codec-aveugle) alors que
  duplicate_compare._best_audio = max(codec_rank, channels) -> sur TrueHD/Atmos + piste lossy compat choisit la
  lossy -> étiquette codec fausse. Donne les 2 implémentations + la clé de tri correcte (codec_rank d'abord).` },
  { key: 'R8-040', prompt: `${BASE}
scene_parser.py ~L131 (nettoyage de nom pour query TMDb).
R8-040 : name.replace('.',' ') transforme 'DD5.1'->'DD5 1' AVANT _NOISE_RE qui ne matche plus -> résidu
'DD5 1'/'DDP5 1'/'DD7 1' pollue la query TMDb. Donne le code exact (ordre replace vs _NOISE_RE), le contenu de
_NOISE_RE pertinent, et le fix minimal (matcher les tokens audio AVANT le replace, ou adapter _NOISE_RE).
ATTENTION : ne pas casser le nettoyage release-group corrigé en R1/R4 (mémoire).` },
  { key: 'R8-041', prompt: `${BASE}
tmdb_client.py ~L515 (cache de recherche TMDb).
R8-041 : _cache_set(key, []) sur une réponse 200 + results=[] PUIS 'if cached is not None' (vrai pour [])
-> un film non identifié reste figé ~7 jours à travers les re-scans après UN hoquet TMDb (le fallback stale ne
couvre que les erreurs réseau). Donne : le code de mise en cache + de lecture, où la liste vide est écrite et
relue, et le fix (ne pas cacher un résultat vide comme valide, ou TTL court/négatif distinct).` },
  { key: 'R8-042', prompt: `${BASE}
duplicate_compare.py ~L142 (producteur) ↔ web/dashboard .../doublons.js ~L297 (rendu).
R8-042 : la carte rend total_score_a/b en '\${score}/100' MAIS ce sont des POINTS head-to-head
(sum(points_delta>0) vs <0, le perdant ~toujours 0) — PAS un 0..100 -> '30/100' / '0/100' faux même pour 2 bons
fichiers. Donne : ce que duplicate_compare produit réellement (nom du champ + sémantique), ce que doublons.js
lit/affiche, et le fix d'échelle/rendu cohérent (libellé 'points' ou vraie échelle).` },
  { key: 'R8-043-044', prompt: `${BASE}
- R8-043 : models.py ~L382 (to_dict perceptuel) — hdr_analysis absent de to_dict ET non ajouté côté
  perceptual_support -> d.hdr_analysis undefined côté UI -> champ HDR de la modale toujours 'sdr'. Donne le
  dataclass/to_dict, où hdr_analysis est calculé, et le câblage minimal jusqu'au dict consommé par l'UI.
  Instrumentable avec une fixture HDR (ffmpeg peut-il en générer une, ex. bt2020/smpte2084) ?
- R8-044 : mkv_title_check.py ~L53 (via quality_report_support.py ~L313) — égalité exacte case-insensitive
  container_title vs proposed_title -> 88% mismatch (release-names à points) = faux signal mkv_title_mismatch.
  Donne la comparaison exacte + un fix de normalisation (tokens/fuzzy) qui réduit les faux positifs sans rater
  les vrais.` },
]

phase('Recon')
const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    confirmed: { type: 'string' },
    sites: { type: 'string' },
    root_cause: { type: 'string' },
    fix_approach: { type: 'string' },
    instrumentable: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['confirmed', 'sites', 'root_cause', 'fix_approach', 'instrumentable'],
}

const results = await parallel(TASKS.map((t) => () =>
  agent(`${t.prompt}

Retourne un objet : confirmed, sites (fichier:ligne actuels), root_cause, fix_approach, instrumentable
(yes/no/n-a + comment), notes. <250 mots, précis et factuel sur le VRAI code.`,
    { label: `recon:${t.key}`, phase: 'Recon', schema: SCHEMA })
    .then((r) => ({ key: t.key, ...r }))))

return results.filter(Boolean)
