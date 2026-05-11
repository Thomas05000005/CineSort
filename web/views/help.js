/* views/help.js — Vue Aide v5 (FAQ + glossaire + raccourcis + Support).
 *
 * V5bis-07 : ES module exporte `initHelp(container, opts)` (utilise par la SPA
 * dashboard et la webview pywebview natif). Remplace l'ancienne IIFE legacy.
 * Les sections sont preservees integralement :
 * - V1-14 : 15 FAQ + 16 termes glossaire
 * - V3-08 : 3 categories de raccourcis enrichies (Navigation, Actions, Validation)
 * - V3-13 : Support (ouvrir logs, copier chemin, signaler bug)
 *
 * Les acces backend passent par apiPost (REST + fallback pywebview cote
 * helpers), jamais d'appel direct au bridge natif depuis cette vue.
 */

import { apiPost, escapeHtml, $ } from "./_v5_helpers.js";

const PROJECT_GITHUB_URL = "https://github.com/PLACEHOLDER/cinesort";

/* V3-08 — Liste exhaustive des raccourcis clavier (3 categories).
 * Navigation : Alt+1..Alt+8 (sidebar) et 1 / 2 / .. / 8 hors champ texte.
 * Actions globales : Ctrl+K (palette), Ctrl+S (save), F5 (refresh), F1 / ? (aide), Esc.
 * Validation : Up/Down ou j/k, Espace/a (approuver), r (rejeter), i (inspecteur),
 * Ctrl+A (tout approuver), f (focus mode).
 * Les tags <kbd> sont preserves litteralement dans le source pour la lisibilite
 * et pour valider la presence semantique en tests structurels. */
const SHORTCUTS = [
  {
    category: "Navigation",
    items: [
      { keysHtml: "<kbd>Alt</kbd>+<kbd>1</kbd>", desc: "Accueil" },
      { keysHtml: "<kbd>Alt</kbd>+<kbd>2</kbd>", desc: "Bibliotheque" },
      { keysHtml: "<kbd>Alt</kbd>+<kbd>3</kbd>", desc: "Qualite" },
      { keysHtml: "<kbd>Alt</kbd>+<kbd>4</kbd>", desc: "Jellyfin" },
      { keysHtml: "<kbd>Alt</kbd>+<kbd>5</kbd>", desc: "Plex" },
      { keysHtml: "<kbd>Alt</kbd>+<kbd>6</kbd>", desc: "Radarr" },
      { keysHtml: "<kbd>Alt</kbd>+<kbd>7</kbd>", desc: "Journaux" },
      { keysHtml: "<kbd>Alt</kbd>+<kbd>8</kbd>", desc: "Parametres" },
      { keysHtml: "<kbd>1</kbd> / <kbd>2</kbd> / .. / <kbd>8</kbd>", desc: "Navigation directe (hors champ texte)" },
    ],
  },
  {
    category: "Actions globales",
    items: [
      { keysHtml: "<kbd>Ctrl</kbd>+<kbd>K</kbd>", desc: "Ouvrir la palette de commandes (recherche)" },
      { keysHtml: "<kbd>Ctrl</kbd>+<kbd>S</kbd>", desc: "Sauvegarder les decisions de validation" },
      { keysHtml: "<kbd>F5</kbd>", desc: "Rafraichir la vue active" },
      { keysHtml: "<kbd>F1</kbd> ou <kbd>?</kbd>", desc: "Afficher la modale des raccourcis" },
      { keysHtml: "<kbd>Esc</kbd>", desc: "Fermer la modale ou le drawer actif" },
    ],
  },
  {
    category: "Validation (vue Validation active)",
    items: [
      { keysHtml: "<kbd>Up</kbd> <kbd>Down</kbd> ou <kbd>j</kbd> <kbd>k</kbd>", desc: "Naviguer entre les films" },
      { keysHtml: "<kbd>Espace</kbd> ou <kbd>a</kbd>", desc: "Approuver le film selectionne" },
      { keysHtml: "<kbd>r</kbd>", desc: "Rejeter le film selectionne" },
      { keysHtml: "<kbd>i</kbd>", desc: "Ouvrir l'inspecteur du film" },
      { keysHtml: "<kbd>Ctrl</kbd>+<kbd>A</kbd>", desc: "Tout approuver" },
      { keysHtml: "<kbd>f</kbd>", desc: "Basculer le mode focus" },
    ],
  },
];

const FAQ_ITEMS = [
  {
    q: "Comment lancer mon premier scan ?",
    a: "Va dans Parametres -> Dossiers racine, ajoute le dossier qui contient tes films (ex. D:\\Films), enregistre, puis ouvre Bibliotheque -> Analyser. CineSort lit chaque fichier video, recupere les infos depuis TMDb et genere une analyse complete. Au premier lancement, le wizard 5 etapes te guide automatiquement.",
  },
  {
    q: "C'est quoi un dry-run ?",
    a: "Un dry-run (\"essai a sec\") simule l'application des changements sans rien deplacer ni renommer sur ton disque. Tu vois exactement ce qui serait fait. C'est l'option recommandee pour ton premier passage : zero risque de perdre un fichier. Decoche \"Mode dry-run\" dans l'ecran Application uniquement quand tu es sur de toi.",
  },
  {
    q: "Comment fonctionne l'auto-approbation ?",
    a: "Quand un film a un score eleve et une confiance forte (TMDb match exact + .nfo coherent), CineSort le marque automatiquement comme approuve. Tu peux decocher manuellement ceux que tu ne veux pas appliquer. Reglage : Parametres -> Validation -> seuils de confiance.",
  },
  {
    q: "Mes decisions ont disparu apres refresh, pourquoi ?",
    a: "Les decisions de validation sont persistees en base SQLite via Ctrl+S ou le bouton Enregistrer. Si tu n'as pas sauvegarde avant un F5 ou un changement de vue, elles sont perdues. CineSort affiche un avertissement \"decisions non sauvegardees\" si tu navigues sans enregistrer.",
  },
  {
    q: "Comment annuler un apply ?",
    a: "CineSort tient un journal de tous les deplacements/renommages (table apply_operations). Va dans Application -> Annuler, choisis le batch a defaire, previsualise en dry-run, puis confirme. L'annulation peut etre par batch entier ou film par film (Undo v5). Les conflits (fichier deja modifie depuis) sont rediriges vers _review/_undo_conflicts.",
  },
  {
    q: "Comment configurer Jellyfin / Plex / Radarr ?",
    a: "Parametres -> section Integrations. Pour Jellyfin : URL du serveur + cle API (Profil -> Cles API dans Jellyfin). Pour Plex : URL + token X-Plex-Token (recuperable via plex.tv/account). Pour Radarr : URL + cle API (Settings -> General). Le bouton \"Tester la connexion\" valide immediatement. Active le rafraichissement auto pour declencher un scan apres chaque apply.",
  },
  {
    q: "Mon scan ne trouve pas de films, que faire ?",
    a: "Verifie dans cet ordre : (1) le dossier racine est-il accessible (pas de NAS deconnecte) ; (2) les extensions video sont-elles supportees (mkv, mp4, avi, mov par defaut) ; (3) les fichiers ne sont-ils pas en lecture seule ou bloques par l'antivirus ; (4) consulte les Journaux pour le message d'erreur exact. Si rien ne marche, exporte les logs et signale via GitHub Issues.",
  },
  {
    q: "C'est quoi le mode perceptuel ?",
    a: "L'analyse perceptuelle regarde la vraie qualite de l'image et du son (pas seulement les metadonnees). Elle detecte les fake 4K (upscale), le DNR excessif (lissage qui efface le grain), le DRC audio (compression dynamique cinema/standard/broadcast), le HDR mal encode, etc. Reglage : Parametres -> Perceptuel. Active si tu veux noter la qualite reelle, pas juste la resolution affichee.",
  },
  {
    q: "Comment installer ffmpeg / mediainfo ?",
    a: "Parametres -> Outils video -> bouton \"Installer automatiquement\". CineSort telecharge les binaires officiels et les place dans le dossier de l'app, sans toucher au PATH systeme. Si tu prefereres une install manuelle : ffmpeg.org et mediaarea.net/MediaInfo, puis indique le chemin complet dans Parametres.",
  },
  {
    q: "Comment partager mes logs pour signaler un bug ?",
    a: "Parametres -> Journaux -> bouton \"Exporter le diagnostic\". Le fichier zip contient logs + version + config (sans tes cles API, automatiquement scrubbees : TMDb, Jellyfin, Plex, Radarr, mots de passe SMTP). Joins-le a une issue GitHub. Logs bruts : %LOCALAPPDATA%/CineSort/logs/cinesort.log (rotation 50 MB x 5).",
  },
  {
    q: "Mon antivirus dit que CineSort est dangereux",
    a: "Faux positif courant des EXE Python compiles avec PyInstaller. CineSort est open source (code lisible sur GitHub) et signe. Solutions : (1) ajoute une exception pour CineSort.exe dans ton antivirus ; (2) verifie la signature du binaire (clic droit -> Proprietes -> Signatures numeriques) ; (3) compile depuis les sources si tu prefereres. Pas de telemetrie, pas de code reseau hors TMDb/Jellyfin/Plex/Radarr (que tu actives toi-meme).",
  },
  {
    q: "Le dashboard distant ne se connecte pas",
    a: "Verifie : (1) Parametres -> API REST est active ; (2) tu utilises bien la cle d'acces complete (au moins 32 caracteres pour bind LAN) ; (3) firewall Windows autorise CineSort.exe sur le port 8642 ; (4) memes wifi pour PC et telephone. La carte \"Acces distant\" sur la page Accueil affiche l'URL et le QR code a scanner.",
  },
  {
    q: "Que veut dire 'tier Platinum / Gold / Silver / Bronze / Reject' ?",
    a: "C'est la note finale de qualite du film sur 5 paliers. Platinum = excellence (4K HDR Dolby Atmos sans defaut). Gold = tres bonne version (1080p ou 4K propre). Silver = correct (DVD ou 720p). Bronze = limite (basse resolution ou encode degradant). Reject = a refaire (fake 4K, audio mono, fichier corrompu). Le calcul combine resolution, codec, audio, sous-titres et detection perceptuelle.",
  },
  {
    q: "Comment exporter un rapport de mon analyse ?",
    a: "Apres un scan : Bibliotheque -> Application -> bouton \"Exporter\". Trois formats : HTML (rapport autonome avec graphiques, ouvrable dans tout navigateur, imprimable PDF via Ctrl+P) ; CSV enrichi (30 colonnes, ouvrable Excel) ; .nfo XML (Kodi/Jellyfin/Emby, un fichier par film a cote de la video).",
  },
  {
    q: "Puis-je utiliser CineSort sans connexion Internet ?",
    a: "Oui pour le scan local et l'application. Non pour l'enrichissement TMDb (titre original, annee, poster, collection). Astuce : lance un premier scan en ligne pour remplir le cache TMDb local, puis tu peux travailler hors ligne. Les sous-titres sont detectes localement sans Internet. Jellyfin/Plex/Radarr fonctionnent tant que ton serveur est accessible (LAN suffit).",
  },
];

const GLOSSARY = [
  { term: "Tier", def: "Palier de qualite finale d'un film. 5 niveaux : Platinum (excellence) > Gold (tres bon) > Silver (correct) > Bronze (limite) > Reject (a refaire). Calcul combine score V2 + ajustements contextuels (era, codec, perceptual)." },
  { term: "Score V2", def: "Note composite sur 100 (CinemaLux v2). Pondere Video 60%, Audio 35%, Coherence 5%. Inclut l'analyse perceptuelle si activee. Plus lisible que le score V1 (legacy, conservé pour compat)." },
  { term: "Score V1", def: "Ancien systeme de scoring (pre-v7.5.0). Base uniquement sur les metadonnees (resolution, codec, audio). Conservé pour les rapports anterieurs a la migration 011." },
  { term: "Confidence", def: "Niveau de certitude du match TMDb. 0.95+ = certain (.nfo + IMDb id). 0.7-0.95 = forte. 0.5-0.7 = moyenne (relire). <0.5 = faible (a verifier manuellement)." },
  { term: "Probe", def: "Action d'analyser un fichier video pour extraire ses caracteristiques techniques (codec, resolution, bitrate, pistes audio, HDR). Outils utilises : ffprobe ou mediainfo, en parallele." },
  { term: "Dry-run", def: "Mode simulation : CineSort calcule tous les changements (deplacements, renommages) mais ne touche a aucun fichier. Tu vois le rapport complet avant d'appliquer pour de vrai. Recommande au premier passage." },
  { term: "Quarantine", def: "Dossier _review/ ou sont deplaces les fichiers non valides : films sans titre TMDb, doublons SHA1 (_duplicates_identical/), conflits (_review/_conflicts), fichiers corrompus. Tu peux les revoir et les sauver manuellement." },
  { term: "Edition", def: "Version particuliere d'un film : Director's Cut, Extended, IMAX, Theatrical, Unrated, etc. CineSort la detecte depuis le nom de fichier ou le .nfo et la garde dans le titre du dossier final." },
  { term: "Saga TMDb (Collection)", def: "Regroupement de films lies (ex. Le Seigneur des Anneaux, Marvel Cinematic Universe). CineSort les detecte via TMDb et peut creer un dossier parent _Collection/ pour les ranger ensemble." },
  { term: "Perceptual", def: "Analyse de la vraie qualite de l'image et du son (pas juste les metadonnees). Detecte fake 4K (upscale), DNR excessif, fake HDR, audio mono deguise en 5.1, etc. Active dans Parametres -> Perceptuel." },
  { term: "LPIPS", def: "Learned Perceptual Image Patch Similarity. Mesure scientifique de similarite visuelle (modele ML AlexNet). Plus fiable que SSIM ou PSNR pour comparer la qualite ressentie. Utilise pour comparer doublons." },
  { term: "Grain era", def: "Classification du grain pellicule par epoque : 16mm (1920+), 35mm classic (1950+), 35mm modern (1990+), digital noise (2000+), digital clean (2010+), UHD/Dolby Vision (2015+). Detecte le grain authentique versus DNR (lissage)." },
  { term: "DRC (Dynamic Range Compression)", def: "Niveau de compression de la dynamique audio. Cinema = grands ecarts conserves (musique forte, dialogues bas). Standard = legerement comprime. Broadcast = tres comprime (TV, plus uniforme mais ecrase)." },
  { term: "SSIM", def: "Structural Similarity Index. Compare deux images sur structure + luminance + contraste. Utilise pour detecter les fake 4K (un upscale a un SSIM eleve avec sa version 1080p reduite)." },
  { term: "Chromaprint", def: "Empreinte audio (audio fingerprint) generee par fpcalc. Permet de detecter qu'un meme film en deux versions (FR + EN) partage la meme bande son sans comparer les fichiers entiers." },
  { term: "NFO", def: "Fichier metadonnees XML format Kodi/Jellyfin/Emby (titre, annee, IMDb/TMDb id). Pose a cote de la video. CineSort le lit en priorite (source plus fiable que le nom de fichier) et peut le generer." },
];

function _lower(s) {
  return String(s || "").toLowerCase();
}

function _matchesQuery(item, q) {
  if (!q) return true;
  const lq = _lower(q);
  const hay = _lower((item.q || item.term || "") + " " + (item.a || item.def || ""));
  return hay.indexOf(lq) !== -1;
}

function _renderFaqList(query) {
  const items = FAQ_ITEMS.filter((it) => _matchesQuery(it, query));
  if (items.length === 0) {
    return '<p class="v5-text-muted">Aucune question ne correspond a ta recherche.</p>';
  }
  let html = '<div class="help-faq-list">';
  for (const it of items) {
    html += '<details class="help-faq-item"><summary>' + escapeHtml(it.q) + "</summary>";
    html += '<div class="help-faq-answer">' + escapeHtml(it.a) + "</div></details>";
  }
  html += "</div>";
  return html;
}

function _renderGlossaryList(query) {
  const items = GLOSSARY.filter((it) => _matchesQuery(it, query));
  if (items.length === 0) {
    return '<p class="v5-text-muted">Aucun terme ne correspond a ta recherche.</p>';
  }
  let html = '<dl class="help-glossary">';
  for (const it of items) {
    html += "<dt>" + escapeHtml(it.term) + "</dt>";
    html += "<dd>" + escapeHtml(it.def) + "</dd>";
  }
  html += "</dl>";
  return html;
}

function _renderFaqSection() {
  return (
    '<section class="v5-help-section help-section">' +
      "<h3>Foire aux questions (" + FAQ_ITEMS.length + ")</h3>" +
      '<div id="helpFaqContainer">' + _renderFaqList("") + "</div>" +
    "</section>"
  );
}

function _renderGlossarySection() {
  return (
    '<section class="v5-help-section help-section">' +
      "<h3>Glossaire metier (" + GLOSSARY.length + " termes)</h3>" +
      '<div id="helpGlossaryContainer">' + _renderGlossaryList("") + "</div>" +
    "</section>"
  );
}

function _renderShortcutsSection() {
  let html = '<section class="v5-help-shortcuts help-shortcuts" id="helpShortcutsSection">';
  html += "<h3>Raccourcis clavier</h3>";
  html += '<p class="v5-text-muted">Memorise ces combinaisons pour gagner du temps. ' +
    "Les raccourcis Alt+chiffre fonctionnent meme dans les champs texte ; les chiffres seuls " +
    "ne sont actifs qu'en dehors d'un champ.</p>";
  for (const cat of SHORTCUTS) {
    html += "<h4>" + escapeHtml(cat.category) + "</h4>";
    html += '<table class="shortcuts-table">' +
      '<thead><tr><th scope="col">Raccourci</th><th scope="col">Action</th></tr></thead><tbody>';
    for (const it of cat.items) {
      html += "<tr><td>" + it.keysHtml + "</td><td>" + escapeHtml(it.desc) + "</td></tr>";
    }
    html += "</tbody></table>";
  }
  html += "</section>";
  return html;
}

/* V3-13 — Section Support : ouvrir logs, copier chemin, signaler bug. */
function _renderSupportSection(paths) {
  const url = escapeHtml(PROJECT_GITHUB_URL);
  const logDir = paths && paths.log_dir ? String(paths.log_dir) : "%LOCALAPPDATA%\\CineSort\\logs";
  const logExists = !(paths && paths.exists === false);
  return (
    '<section class="v5-help-support help-support">' +
      "<h3>Aide supplementaire</h3>" +
      "<p>Tu n'as pas trouve la reponse ? Reproduis le bug, ouvre le dossier des logs " +
      "et joins le fichier <code>cinesort.log</code> a ton signalement :</p>" +
      "<ol>" +
        "<li>Reproduis le bug</li>" +
        "<li>Ouvre le dossier des logs et joins le fichier <code>cinesort.log</code></li>" +
        "<li>Decris ce que tu attendais et ce qui s'est passe</li>" +
      "</ol>" +
      "<ul>" +
        "<li><strong>Signaler un bug ou poser une question</strong> : " +
          '<a href="' + url + '/issues" target="_blank" rel="noopener noreferrer">' + url + "/issues</a></li>" +
        "<li><strong>Documentation complete</strong> : " +
          '<a href="' + url + '#readme" target="_blank" rel="noopener noreferrer">README sur GitHub</a></li>' +
        "<li><strong>Diagnostic exportable</strong> : Parametres -> Journaux -> Exporter le diagnostic. " +
          "Les cles API et mots de passe sont automatiquement scrubbees du zip.</li>" +
      "</ul>" +
      '<div class="support-actions">' +
        '<button type="button" class="v5-btn v5-btn--primary" id="btnOpenLogs"' +
          (logExists ? "" : " disabled") + ">Ouvrir le dossier des logs</button>" +
        '<button type="button" class="v5-btn" id="btnCopyLogPath">Copier le chemin</button>' +
        '<a class="v5-btn" href="' + url + '/issues" target="_blank" rel="noopener noreferrer">' +
          "Signaler un bug sur GitHub</a>" +
      "</div>" +
      '<p class="v5-text-muted help-support-hint" id="helpSupportHint" aria-live="polite">' +
        "Chemin : <code id=\"helpLogPath\">" + escapeHtml(logDir) + "</code>" +
      "</p>" +
    "</section>"
  );
}

function _setHint(message, isError) {
  const hint = document.getElementById("helpSupportHint");
  if (!hint) return;
  hint.textContent = message || "";
  if (isError && message) {
    hint.classList.add("help-support-hint--error");
  } else {
    hint.classList.remove("help-support-hint--error");
  }
}

async function _onClickOpenLogs(btn) {
  btn.disabled = true;
  try {
    const res = await apiPost("open_logs_folder");
    const data = res?.data || {};
    if (res.ok && data.ok !== false) {
      _setHint("Ouvert : " + (data.opened || ""));
    } else {
      const errMsg = data.error || res.error || "Impossible d'ouvrir le dossier.";
      _setHint("Erreur : " + errMsg, true);
    }
  } finally {
    btn.disabled = false;
  }
}

async function _onClickCopyLogPath(btn) {
  const res = await apiPost("get_log_paths");
  const data = res?.data || {};
  const path = data.log_dir || "";
  if (!path) {
    _setHint("Chemin des logs introuvable.", true);
    return;
  }
  if (!navigator.clipboard) {
    _setHint("Copie impossible. Chemin : " + path, true);
    return;
  }
  try {
    await navigator.clipboard.writeText(path);
    const original = btn.textContent;
    btn.textContent = "Copie !";
    setTimeout(() => { btn.textContent = original; }, 1500);
    _setHint("");
  } catch {
    _setHint("Copie impossible. Chemin : " + path, true);
  }
}

function _bindEvents(container) {
  // Recherche debounced
  const input = container.querySelector("#helpSearchInput");
  if (input) {
    let debounce = null;
    input.addEventListener("input", () => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(() => {
        const q = input.value;
        const faq = container.querySelector("#helpFaqContainer");
        const glo = container.querySelector("#helpGlossaryContainer");
        if (faq) faq.innerHTML = _renderFaqList(q);
        if (glo) glo.innerHTML = _renderGlossaryList(q);
      }, 80);
    });
  }

  // Actions Support
  container.addEventListener("click", (ev) => {
    const t = ev.target;
    if (!t || t.nodeType !== 1) return;
    if (t.id === "btnOpenLogs") {
      _onClickOpenLogs(t);
    } else if (t.id === "btnCopyLogPath") {
      _onClickCopyLogPath(t);
    }
  });
}

/**
 * Initialise la vue Aide v5.
 * Charge les chemins de logs (V3-13), rend FAQ + glossaire + raccourcis + Support,
 * puis attache les events (recherche, boutons logs).
 *
 * @param {HTMLElement} container - element ou injecter la vue
 * @param {object} [opts] - options reservees pour usages futurs
 */
export async function initHelp(container, opts = {}) {
  if (!container) return;
  const pathsRes = await apiPost("get_log_paths").catch(() => ({ data: {} }));
  const paths = (pathsRes && pathsRes.data) || {};

  container.innerHTML = `
    <div class="v5-help">
      <header class="v5-help-header">
        <h2>Aide</h2>
        <p class="v5-text-muted">FAQ, glossaire et support pour CineSort. Utilise la recherche pour filtrer les questions et les termes.</p>
      </header>
      <div class="v5-help-search">
        <input type="search" id="helpSearchInput" class="v5-input"
          placeholder="Chercher une question, un terme..."
          aria-label="Filtrer la FAQ et le glossaire"
          autocomplete="off" spellcheck="false" />
      </div>
      ${_renderFaqSection()}
      ${_renderGlossarySection()}
      ${_renderShortcutsSection()}
      ${_renderSupportSection(paths)}
    </div>
  `;

  _bindEvents(container);

  const input = container.querySelector("#helpSearchInput");
  if (input) {
    input.focus();
    try { input.setSelectionRange(0, 0); } catch { /* noop */ }
  }
}

export default initHelp;
