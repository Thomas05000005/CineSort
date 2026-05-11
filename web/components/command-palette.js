/* components/command-palette.js — Palette de commandes Ctrl+K (E1)
 *
 * Modale fullscreen avec champ de recherche floue + liste de commandes.
 * Fournit des actions rapides : navigation vues, scan, validation, etc.
 *
 * Touches :
 *   Ctrl+K ou Cmd+K     ouvre la palette
 *   Echap                ferme
 *   Fleche bas/haut      navigue dans les resultats
 *   Entree                execute la commande selectionnee
 */

(function () {
  let _overlay = null;
  let _input = null;
  let _list = null;
  let _commands = [];
  let _filtered = [];
  let _selectedIdx = 0;

  /* --- MRU (H9) ------------------------------------------------ */
  const _MRU_KEY = "cinesort.cmdPalette.mru";
  const _MRU_LIMIT = 10;

  function _loadMru() {
    try {
      const raw = localStorage.getItem(_MRU_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch { return []; }
  }
  function _saveMru(list) {
    try { localStorage.setItem(_MRU_KEY, JSON.stringify(list.slice(0, _MRU_LIMIT))); } catch { /* quota */ }
  }
  function _noteMru(id) {
    if (!id) return;
    const list = _loadMru().filter((x) => x !== id);
    list.unshift(id);
    _saveMru(list);
  }

  /* --- Parser prefixes (H8) ------------------------------------ */
  function _parseInput(str) {
    const trimmed = String(str || "").trim();
    const m = /^:(films|film|run|runs|settings|apply)\s+(.*)$/i.exec(trimmed);
    if (m) {
      let mode = m[1].toLowerCase();
      if (mode === "film") mode = "films";
      if (mode === "runs") mode = "run";
      return { mode, query: m[2] };
    }
    const m2 = /^:(films|film|run|runs|settings|apply)$/i.exec(trimmed);
    if (m2) {
      let mode = m2[1].toLowerCase();
      if (mode === "film") mode = "films";
      if (mode === "runs") mode = "run";
      return { mode, query: "" };
    }
    return { mode: null, query: trimmed };
  }

  const _SETTINGS_SECTIONS = [
    { id: "essentiel", label: "Essentiel" },
    { id: "tmdb", label: "TMDb" },
    { id: "probe", label: "Analyse video" },
    { id: "naming", label: "Renommage" },
    { id: "jellyfin", label: "Jellyfin" },
    { id: "plex", label: "Plex" },
    { id: "radarr", label: "Radarr" },
    { id: "theme", label: "Apparence" },
    { id: "notifications", label: "Notifications" },
    { id: "email", label: "Email" },
    { id: "watch", label: "Surveillance" },
    { id: "rest", label: "API REST" },
    { id: "plugins", label: "Plugins" },
    { id: "perceptual", label: "Perceptuel" },
  ];

  function _buildContextualCommands(mode, query) {
    const q = String(query || "").toLowerCase();
    if (mode === "films") {
      const rows = (window.state && Array.isArray(window.state.rows)) ? window.state.rows : [];
      return rows
        .filter((r) => (r.proposed_title || "").toLowerCase().includes(q))
        .slice(0, 20)
        .map((r) => ({
          id: `film-${r.row_id}`,
          title: `${r.proposed_title || "Sans titre"}${r.proposed_year ? " (" + r.proposed_year + ")" : ""}`,
          hint: r.folder || "",
          run: () => {
            if (typeof window.navigateTo === "function") window.navigateTo("validation");
            if (window.state) window.state.selectedRowId = r.row_id;
          },
        }));
    }
    if (mode === "settings") {
      return _SETTINGS_SECTIONS
        .filter((s) => !q || s.label.toLowerCase().includes(q))
        .map((s) => ({
          id: `settings-${s.id}`,
          title: `Reglages : ${s.label}`,
          hint: "Ouvrir la section",
          run: () => {
            if (typeof window.navigateTo === "function") window.navigateTo("settings");
            setTimeout(() => {
              const sec = document.querySelector(`[data-settings-section="${s.id}"]`) || document.getElementById(`settings-${s.id}`);
              if (sec && sec.scrollIntoView) sec.scrollIntoView({ behavior: "smooth", block: "start" });
            }, 120);
          },
        }));
    }
    if (mode === "run") {
      /* Placeholder : la liste des runs pourrait etre chargee async.
       * Pour l'instant on propose la nav vers history + filtre local. */
      return [
        { id: "run-history", title: "Ouvrir l'historique des runs", hint: "Voir tous les runs", run: () => window.navigateTo && window.navigateTo("history") },
      ];
    }
    if (mode === "apply") {
      return [
        { id: "apply-dry", title: "Apply : dry-run", hint: "Execution simulee", run: () => {
          if (typeof window.navigateTo === "function") window.navigateTo("execution");
          const ck = document.getElementById("ckDryRun"); if (ck) ck.checked = true;
        }},
        { id: "apply-real", title: "Apply : execution reelle", hint: "Deplacements definitifs", run: () => {
          if (typeof window.navigateTo === "function") window.navigateTo("execution");
          const ck = document.getElementById("ckDryRun"); if (ck) ck.checked = false;
        }},
        { id: "apply-undo", title: "Annuler le dernier apply", hint: "Undo v1", run: () => {
          if (typeof window.navigateTo === "function") window.navigateTo("execution");
          if (typeof window.undoLastApply === "function") window.undoLastApply();
        }},
      ];
    }
    return [];
  }

  function _buildCommands() {
    const cmds = [];
    /* Navigation vues */
    const views = [
      ["home", "Accueil", "Aller à l'accueil"],
      ["validation", "Validation", "Voir et éditer les décisions"],
      ["execution", "Application", "Lancer dry-run / apply / undo"],
      ["quality", "Qualité", "Scoring CinemaLux + presets"],
      ["jellyfin", "Jellyfin", "Statut + sync watched"],
      ["plex", "Plex", "Statut + sync"],
      ["radarr", "Radarr", "Candidats upgrade"],
      ["history", "Journaux", "Historique des runs"],
      ["settings", "Paramètres", "Réglages complets"],
    ];
    for (const [view, title, hint] of views) {
      cmds.push({
        id: `nav-${view}`,
        title: `Aller vers : ${title}`,
        hint,
        run: () => { if (typeof navigateTo === "function") navigateTo(view); },
      });
    }
    /* Actions principales */
    cmds.push({
      id: "scan-start",
      title: "Lancer un scan",
      hint: "Démarre une analyse sur les dossiers configurés",
      run: () => { if (typeof startPlan === "function") startPlan(); },
    });
    cmds.push({
      id: "save-validation",
      title: "Sauvegarder les décisions",
      hint: "Persiste validation.json (Ctrl+S)",
      run: () => { if (typeof persistValidation === "function") persistValidation(); },
    });
    cmds.push({
      id: "theme-toggle",
      title: "Basculer le thème clair/sombre",
      hint: "Permute light/dark",
      run: () => { if (typeof toggleTheme === "function") toggleTheme(); },
    });
    cmds.push({
      id: "shortcuts",
      title: "Afficher les raccourcis clavier",
      hint: "Modale d'aide (?)",
      run: () => { if (typeof openModal === "function") openModal("modalShortcuts"); },
    });
    return cmds;
  }

  function _ensureOverlay() {
    if (_overlay && document.body.contains(_overlay)) return _overlay;
    _overlay = document.createElement("div");
    _overlay.id = "cmd-palette-overlay";
    _overlay.className = "cmd-palette-overlay hidden";
    _overlay.setAttribute("role", "dialog");
    _overlay.setAttribute("aria-modal", "true");
    _overlay.setAttribute("aria-label", "Palette de commandes");
    _overlay.innerHTML = `
      <div class="cmd-palette">
        <input type="text" class="cmd-palette__input" placeholder="Tapez une commande... (:films, :run, :settings, :apply)" autocomplete="off" spellcheck="false" />
        <ul class="cmd-palette__list" role="listbox"></ul>
        <div class="cmd-palette__hint">↑↓ naviguer · Entrée exécuter · Échap fermer · Préfixes : :films :run :settings :apply</div>
      </div>`;
    document.body.appendChild(_overlay);
    _input = _overlay.querySelector(".cmd-palette__input");
    _list = _overlay.querySelector(".cmd-palette__list");
    _input.addEventListener("input", _refilter);
    _input.addEventListener("keydown", _onInputKey);
    _overlay.addEventListener("click", (e) => { if (e.target === _overlay) _close(); });
    return _overlay;
  }

  function _fuzzyScore(text, query) {
    if (!query) return 1;
    const t = text.toLowerCase();
    const q = query.toLowerCase();
    if (t.includes(q)) return 100 - t.indexOf(q);
    /* Match lettres dans l'ordre */
    let qi = 0;
    for (let i = 0; i < t.length && qi < q.length; i++) {
      if (t[i] === q[qi]) qi += 1;
    }
    return qi === q.length ? 50 - (t.length - q.length) / 2 : 0;
  }

  function _refilter() {
    const raw = _input.value || "";
    const parsed = _parseInput(raw);
    if (parsed.mode) {
      /* Commandes contextuelles (H8) */
      _filtered = _buildContextualCommands(parsed.mode, parsed.query);
    } else if (!parsed.query) {
      /* Input vide : MRU en haut, puis toutes les commandes (H9). */
      const mru = _loadMru();
      const byId = new Map(_commands.map((c) => [c.id, c]));
      const recent = mru.map((id) => byId.get(id)).filter(Boolean);
      const others = _commands.filter((c) => !mru.includes(c.id));
      _filtered = [...recent, ...others];
    } else {
      _filtered = _commands
        .map(c => ({ c, s: Math.max(_fuzzyScore(c.title, parsed.query), _fuzzyScore(c.hint || "", parsed.query) * 0.6) }))
        .filter(x => x.s > 0)
        .sort((a, b) => b.s - a.s)
        .map(x => x.c);
    }
    _selectedIdx = 0;
    _render();
  }

  function _render() {
    if (!_list) return;
    if (_filtered.length === 0) {
      _list.innerHTML = '<li class="cmd-palette__empty">Aucune commande</li>';
      return;
    }
    _list.innerHTML = _filtered.map((c, i) => `
      <li class="cmd-palette__item${i === _selectedIdx ? " is-selected" : ""}" data-idx="${i}" role="option" aria-selected="${i === _selectedIdx}">
        <div class="cmd-palette__title"></div>
        <div class="cmd-palette__hint-line"></div>
      </li>`).join("");
    _list.querySelectorAll(".cmd-palette__item").forEach((li, i) => {
      li.querySelector(".cmd-palette__title").textContent = _filtered[i].title;
      li.querySelector(".cmd-palette__hint-line").textContent = _filtered[i].hint || "";
      li.addEventListener("click", () => _execute(i));
      li.addEventListener("mouseenter", () => { _selectedIdx = i; _updateSelection(); });
    });
  }

  function _updateSelection() {
    _list.querySelectorAll(".cmd-palette__item").forEach((li, i) => {
      li.classList.toggle("is-selected", i === _selectedIdx);
      li.setAttribute("aria-selected", i === _selectedIdx ? "true" : "false");
    });
    const sel = _list.children[_selectedIdx];
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest" });
  }

  function _onInputKey(e) {
    if (e.key === "Escape") { e.preventDefault(); _close(); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); _selectedIdx = Math.min(_filtered.length - 1, _selectedIdx + 1); _updateSelection(); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); _selectedIdx = Math.max(0, _selectedIdx - 1); _updateSelection(); return; }
    if (e.key === "Enter") { e.preventDefault(); _execute(_selectedIdx); return; }
    /* R4-2 (29/04) : focus trap — Tab/Shift+Tab navigue dans la liste au lieu
     * de sortir de la modale. Convention macOS-style (Spotlight, Linear, Raycast). */
    if (e.key === "Tab") {
      e.preventDefault();
      if (e.shiftKey) {
        _selectedIdx = Math.max(0, _selectedIdx - 1);
      } else {
        _selectedIdx = Math.min(_filtered.length - 1, _selectedIdx + 1);
      }
      _updateSelection();
      return;
    }
  }

  function _execute(idx) {
    const cmd = _filtered[idx];
    if (!cmd) return;
    _noteMru(cmd.id);
    _close();
    try { cmd.run(); } catch (e) { console.error("[cmd-palette]", e); }
  }

  function _open() {
    _commands = _buildCommands();
    _ensureOverlay();
    _overlay.classList.remove("hidden");
    _input.value = "";
    _refilter();
    setTimeout(() => _input.focus(), 30);
  }

  function _close() {
    if (!_overlay) return;
    _overlay.classList.add("hidden");
  }

  /* Hotkey global Ctrl+K / Cmd+K */
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (_overlay && !_overlay.classList.contains("hidden")) _close();
      else _open();
    }
  });

  window.openCommandPalette = _open;

  /* v7.6.0 Vague 1 : API v5 — wrapper pour uniformiser avec top-bar-v5, etc.
   * Le DOM existant (classes legacy .cmd-palette__*) reste inchange tant que la
   * Vague 6+ ne refait pas le DOM en classes v5-palette-*.
   */
  window.CommandPalette = {
    open: _open,
    close: _close,
    isOpen: function () {
      return !!(_overlay && !_overlay.classList.contains("hidden"));
    },
  };
})();
