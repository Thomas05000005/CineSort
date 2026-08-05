#!/usr/bin/env node
/**
 * check_js_syntax.mjs — verificateur de syntaxe REEL pour les sources de `web/`.
 *
 * ======================================================================
 * POURQUOI CE FICHIER EXISTE : `node --check` MENTAIT
 * ======================================================================
 *
 * Mesure du 2026-08-03 (Node v24.14.1, depot sans package.json) :
 *
 *   $ printf '\nconst BROKEN = ;\n' >> web/dashboard/core/format.js
 *   $ node --check web/dashboard/core/format.js ; echo $?
 *   0                      <-- AUCUNE erreur signalee
 *
 * Balaye sur les 48 `.js` de `web/dashboard/`, en injectant a chaque fois la
 * meme erreur de syntaxe indiscutable (`const __BROKEN__ = ;`) :
 *
 *   47 fichiers sortent en 0   (FAUX VERT)
 *    1 fichier  sort  en 1   (`bootstrap-debug.js`)
 *
 * Cause isolee sur repro minimale :
 *
 *   fichier `.js` SANS import/export  -> parse en CommonJS -> erreur signalee
 *   fichier `.js` AVEC import/export  -> la detection de syntaxe de module de
 *                                        Node s'interpose et le processus sort
 *                                        en 0 sans jamais reverifier la source
 *                                        dans le goal « module ».
 *
 * `bootstrap-debug.js` est le seul fichier du dashboard charge par
 * `<script src>` sans `type="module"` : c'est une IIFE, sans import ni export,
 * donc le seul que l'ancienne commande verifiait vraiment. Les 47 autres sont
 * des modules ESM : leur « OK » ne valait rien. Une vingtaine de bilans internes
 * du depot citent `node --check` comme preuve de validite du JS ; ces preuves
 * sont nulles et remplacees par ce verificateur.
 *
 * ======================================================================
 * CE QUE FAIT CE VERIFICATEUR
 * ======================================================================
 *
 * 1. Il ne devine JAMAIS le goal d'analyse. Il le DERIVE de la maniere dont le
 *    navigateur charge reellement le fichier :
 *      - reference par un `<script src=...>` SANS `type="module"` -> goal script
 *        (verifie avec `--input-type=commonjs`, qui refuse import/export : le
 *        contrat de chargement est donc verifie lui aussi) ;
 *      - tout le reste sous `web/` -> goal module (`--input-type=module`).
 *    Le goal est TOUJOURS passe explicitement, la source arrivant sur stdin :
 *    le resultat ne depend donc ni de l'extension, ni de la presence ou du
 *    contenu d'un `package.json`. Meme si quelqu'un retire `"type": "module"`
 *    de la racine, ce verificateur reste juste.
 *
 * 2. Il s'auto-teste AVANT de conclure (`runCanaries`). Cinq canaris passent par
 *    exactement le meme chemin de code que les vrais fichiers. Si l'un d'eux ne
 *    se comporte pas comme prevu — typiquement parce qu'une future version de
 *    Node reintroduit un faux vert — le verificateur sort en 2 au lieu de
 *    conclure « tout va bien ». Un echec ne devient jamais un succes silencieux.
 *
 * 3. Il echoue si l'inventaire est vide ou si un `<script src>` local pointe sur
 *    un fichier absent : « zero fichier verifie » n'est pas un succes.
 *
 * ======================================================================
 * USAGE
 * ======================================================================
 *
 *   node scripts/check_js_syntax.mjs                  # verifie tout web/
 *   node scripts/check_js_syntax.mjs --root DIR       # verifie une autre copie
 *   node scripts/check_js_syntax.mjs --only REL       # un seul fichier
 *   node scripts/check_js_syntax.mjs --plan           # inventaire + goals, sans verifier
 *   node scripts/check_js_syntax.mjs --json           # sortie machine
 *   node scripts/check_js_syntax.mjs --self-test      # canaris seuls
 *
 * Codes de sortie :
 *   0 = tous les fichiers analysent proprement
 *   1 = au moins un fichier a une erreur de syntaxe (ou un inventaire invalide)
 *   2 = le verificateur lui-meme n'est pas digne de confiance (canari en echec)
 */

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(SCRIPT_DIR, "..");

/** Racine des sources front verifiees. Relative a la racine du depot. */
const WEB_DIR = "web";

/** Extensions considerees comme du source JavaScript. */
const JS_EXTENSIONS = new Set([".js", ".mjs"]);

/** Repertoires jamais parcourus (aucun n'existe aujourd'hui : c'est une garde). */
const SKIP_DIRS = new Set(["node_modules", ".git", "dist", "build"]);

/**
 * Lance `node --input-type=<goal> --check` en poussant la source sur stdin.
 *
 * stdin plutot qu'un chemin : c'est la seule forme ou le goal d'analyse est
 * impose explicitement et ou ni l'extension ni le `package.json` le plus proche
 * ne peuvent le rediriger en silence.
 *
 * @param {"module"|"commonjs"} goal
 * @param {Buffer} source
 * @returns {{ok: boolean, stderr: string, status: number|null, signal: string|null}}
 */
function checkSource(goal, source) {
  const res = spawnSync(process.execPath, [`--input-type=${goal}`, "--check"], {
    input: source,
    encoding: "buffer",
    windowsHide: true,
  });
  if (res.error) {
    throw new Error(`impossible de lancer node : ${res.error.message}`);
  }
  const stderr = res.stderr ? res.stderr.toString("utf8") : "";
  return { ok: res.status === 0, stderr, status: res.status, signal: res.signal };
}

/**
 * Canaris : ils empruntent le MEME chemin de code que les vrais fichiers.
 *
 * Sans eux, ce verificateur pourrait redevenir un faux vert a la faveur d'une
 * mise a jour de Node — exactement ce qui est arrive a `node --check`. Chaque
 * canari declare ce qu'il DOIT produire ; tout ecart rend l'outil non fiable.
 *
 * @returns {{name: string, goal: string, expectedOk: boolean, actualOk: boolean, passed: boolean}[]}
 */
function runCanaries() {
  const canaries = [
    // Le coeur du faux vert : une erreur de syntaxe dans un module DOIT sortir en 1.
    {
      name: "module-syntaxe-cassee",
      goal: "module",
      source: 'import { x } from "./x.js";\nexport const BROKEN = ;\n',
      expectedOk: false,
    },
    // ... sans pour autant rejeter un module valide (sinon l'outil est inutilisable).
    {
      name: "module-valide",
      goal: "module",
      source: 'import { x } from "./x.js";\nexport const OK = x;\n',
      expectedOk: true,
    },
    // Meme exigence dans le goal script.
    {
      name: "script-syntaxe-cassee",
      goal: "commonjs",
      source: "(function () { const BROKEN = ; })();\n",
      expectedOk: false,
    },
    {
      name: "script-valide",
      goal: "commonjs",
      source: "(function () { window.OK = true; })();\n",
      expectedOk: true,
    },
    // Preuve que les deux goals sont bien SEPARES : un `import` dans un fichier
    // charge en `<script>` classique est une erreur, et doit etre vue comme telle.
    {
      name: "script-refuse-import",
      goal: "commonjs",
      source: 'import { x } from "./x.js";\n',
      expectedOk: false,
    },
  ];

  return canaries.map((c) => {
    const { ok } = checkSource(/** @type {"module"|"commonjs"} */ (c.goal), Buffer.from(c.source, "utf8"));
    return {
      name: c.name,
      goal: c.goal,
      expectedOk: c.expectedOk,
      actualOk: ok,
      passed: ok === c.expectedOk,
    };
  });
}

/**
 * Enumere recursivement les sources JS sous `dir`, en chemins POSIX relatifs a `root`.
 *
 * @param {string} root
 * @param {string} dir
 * @returns {string[]}
 */
function listJsFiles(root, dir) {
  const out = [];
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      out.push(...listJsFiles(root, path.join(dir, entry.name)));
    } else if (entry.isFile() && JS_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
      out.push(path.relative(root, path.join(dir, entry.name)).split(path.sep).join("/"));
    }
  }
  return out.sort();
}

/**
 * Enumere les fichiers HTML sous `dir`.
 *
 * @param {string} dir
 * @returns {string[]} chemins absolus
 */
function listHtmlFiles(dir) {
  const out = [];
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      out.push(...listHtmlFiles(full));
    } else if (entry.isFile() && entry.name.toLowerCase().endsWith(".html")) {
      out.push(full);
    }
  }
  return out.sort();
}

const SCRIPT_TAG_RE = /<script\b([^>]*)>/gi;
const SRC_ATTR_RE = /\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/i;
const TYPE_ATTR_RE = /\btype\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/i;

/**
 * Derive le goal de chaque fichier depuis les `<script src>` des pages HTML.
 *
 * Un fichier reference SANS `type="module"` est un script classique : c'est le
 * navigateur qui fait foi, pas une heuristique sur le contenu (c'est justement
 * une heuristique sur le contenu qui a produit le faux vert de `node --check`).
 *
 * @param {string} root
 * @returns {{classic: Set<string>, modules: Set<string>, missing: string[]}}
 */
function classifyFromHtml(root) {
  const classic = new Set();
  const modules = new Set();
  const missing = [];

  for (const htmlPath of listHtmlFiles(path.join(root, WEB_DIR))) {
    const html = readFileSync(htmlPath, "utf8");
    for (const tag of html.matchAll(SCRIPT_TAG_RE)) {
      const attrs = tag[1] || "";
      const srcMatch = SRC_ATTR_RE.exec(attrs);
      if (!srcMatch) continue; // script inline : pas de fichier a verifier
      const src = (srcMatch[1] ?? srcMatch[2] ?? srcMatch[3] ?? "").trim();
      if (!src || /^[a-z]+:/i.test(src) || src.startsWith("//")) continue; // ressource distante
      const typeMatch = TYPE_ATTR_RE.exec(attrs);
      const type = (typeMatch ? (typeMatch[1] ?? typeMatch[2] ?? typeMatch[3] ?? "") : "").trim().toLowerCase();

      const target = path.resolve(path.dirname(htmlPath), src.split("?")[0].split("#")[0]);
      const rel = path.relative(root, target).split(path.sep).join("/");
      if (!existsSync(target) || !statSync(target).isFile()) {
        missing.push(`${path.relative(root, htmlPath).split(path.sep).join("/")} -> ${src}`);
        continue;
      }
      if (type === "module") modules.add(rel);
      else classic.add(rel);
    }
  }
  return { classic, modules, missing };
}

/**
 * Construit le plan de verification : un goal explicite par fichier.
 *
 * @param {string} root
 * @returns {{files: {path: string, goal: "module"|"commonjs", reason: string}[], missing: string[], conflicts: string[]}}
 */
function buildPlan(root) {
  const { classic, modules, missing } = classifyFromHtml(root);
  const conflicts = [...classic].filter((p) => modules.has(p));
  const jsFiles = listJsFiles(root, path.join(root, WEB_DIR));

  const files = jsFiles.map((rel) => {
    if (classic.has(rel) && !modules.has(rel)) {
      return { path: rel, goal: /** @type {"commonjs"} */ ("commonjs"), reason: "<script src> sans type=module" };
    }
    if (modules.has(rel)) {
      return { path: rel, goal: /** @type {"module"} */ ("module"), reason: '<script type="module">' };
    }
    return { path: rel, goal: /** @type {"module"} */ ("module"), reason: "module ESM importe" };
  });

  return { files, missing, conflicts };
}

function parseArgs(argv) {
  const opts = { root: DEFAULT_ROOT, json: false, plan: false, selfTest: false, only: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--root") {
      opts.root = path.resolve(argv[++i] ?? "");
    } else if (arg.startsWith("--root=")) {
      opts.root = path.resolve(arg.slice("--root=".length));
    } else if (arg === "--only") {
      opts.only = (argv[++i] ?? "").split(path.sep).join("/");
    } else if (arg.startsWith("--only=")) {
      opts.only = arg.slice("--only=".length).split(path.sep).join("/");
    } else if (arg === "--json") {
      opts.json = true;
    } else if (arg === "--plan") {
      opts.plan = true;
    } else if (arg === "--self-test") {
      opts.selfTest = true;
    } else {
      throw new Error(`argument inconnu : ${arg}`);
    }
  }
  return opts;
}

function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`${err.message}\n`);
    return 2;
  }

  // --- 1. Auto-test : l'outil se prouve avant de juger quoi que ce soit. ---
  const canaries = runCanaries();
  const brokenCanaries = canaries.filter((c) => !c.passed);
  if (brokenCanaries.length > 0) {
    const detail = brokenCanaries
      .map((c) => `  - ${c.name} (goal ${c.goal}) : attendu ${c.expectedOk ? "OK" : "ERREUR"}, obtenu ${c.actualOk ? "OK" : "ERREUR"}`)
      .join("\n");
    process.stderr.write(
      "VERIFICATEUR NON FIABLE : les canaris d'auto-test ne se comportent pas comme prevu.\n" +
        `${detail}\n` +
        "Cet outil existe parce que `node --check` sortait en 0 sur une erreur de syntaxe averee.\n" +
        "Plutot que de repeter ce faux vert, il refuse de conclure. Verifiez la version de Node\n" +
        `(ici ${process.version}) et le support de --input-type / --check.\n`,
    );
    if (opts.json) process.stdout.write(`${JSON.stringify({ ok: false, reason: "canaries", canaries }, null, 2)}\n`);
    return 2;
  }
  if (opts.selfTest) {
    if (opts.json) process.stdout.write(`${JSON.stringify({ ok: true, canaries }, null, 2)}\n`);
    else {
      for (const c of canaries) process.stdout.write(`  canari OK : ${c.name} (goal ${c.goal})\n`);
      process.stdout.write(`${canaries.length} canaris conformes — le verificateur est digne de confiance.\n`);
    }
    return 0;
  }

  // --- 2. Inventaire + goal explicite par fichier. ---
  const { files: planned, missing, conflicts } = buildPlan(opts.root);
  const files = opts.only ? planned.filter((f) => f.path === opts.only) : planned;

  if (opts.plan) {
    const payload = { root: opts.root, count: files.length, missing, conflicts, files };
    if (opts.json) process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
    else for (const f of files) process.stdout.write(`  ${f.goal.padEnd(9)} ${f.path}  (${f.reason})\n`);
    return missing.length > 0 || conflicts.length > 0 || files.length === 0 ? 1 : 0;
  }

  const problems = [];
  if (files.length === 0) {
    problems.push(
      opts.only
        ? `--only ${opts.only} : ce fichier n'est pas dans l'inventaire de ${opts.root}`
        : `aucun fichier JS trouve sous ${path.join(opts.root, WEB_DIR)} — un inventaire vide n'est pas un succes`,
    );
  }
  for (const ref of missing) problems.push(`<script src> pointe sur un fichier absent : ${ref}`);
  for (const dup of conflicts) problems.push(`${dup} est charge a la fois en module et en script classique`);

  // --- 3. Verification reelle, goal impose, source sur stdin. ---
  const failures = [];
  for (const file of files) {
    const source = readFileSync(path.join(opts.root, file.path));
    const { ok, stderr } = checkSource(file.goal, source);
    if (!ok) failures.push({ path: file.path, goal: file.goal, stderr: stderr.trim() });
  }

  const ok = failures.length === 0 && problems.length === 0;

  if (opts.json) {
    process.stdout.write(`${JSON.stringify({ ok, checked: files.length, failures, problems, canaries }, null, 2)}\n`);
  } else {
    for (const p of problems) process.stderr.write(`INVENTAIRE : ${p}\n`);
    for (const f of failures) {
      process.stderr.write(`\nERREUR DE SYNTAXE — ${f.path} (analyse en goal « ${f.goal} »)\n`);
      // stderr de node parle de « [stdin] » : on reinjecte le vrai chemin.
      process.stderr.write(`${f.stderr.split("[stdin]").join(f.path)}\n`);
    }
    if (ok) {
      process.stdout.write(`${files.length} fichier(s) JS de web/ analyses sans erreur (${canaries.length} canaris conformes).\n`);
    } else {
      process.stderr.write(`\n${failures.length} fichier(s) en erreur sur ${files.length} analyse(s).\n`);
    }
  }

  return ok ? 0 : 1;
}

process.exitCode = main();
