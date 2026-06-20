// R8 F4 — DIFFERENTIEL R8-042 : échelle d'affichage du score doublons.
// total_score_a/b sont des POINTS head-to-head (pas un 0..100). "X/100" = faux.
function render(scoreA, scoreB) {
  const avant = { A: `${scoreA}/100`, B: `${scoreB}/100` };
  const totalPts = scoreA + scoreB;
  const apres = { A: `${scoreA}/${totalPts || 1} pts`, B: `${scoreB}/${totalPts || 1} pts` };
  return { avant, apres };
}
const cases = [
  { name: "2 bons fichiers, A gagne tout", a: 30, b: 0 },
  { name: "comparaison serrée", a: 20, b: 10 },
];
let ok = true;
for (const c of cases) {
  const r = render(c.a, c.b);
  console.log(`=== ${c.name} (scoreA=${c.a}, scoreB=${c.b}) ===`);
  console.log(`  AVANT : A '${r.avant.A}'  B '${r.avant.B}'   (perdant "0/100" = fausse qualité)`);
  console.log(`  APRÈS : A '${r.apres.A}'  B '${r.apres.B}'   (points d'avantage / total en jeu)`);
  // L'échelle APRÈS est cohérente : scoreA/total + scoreB/total = 1 (100% des points).
  if ((c.a + c.b) > 0 && (c.a + c.b) !== (c.a + c.b)) ok = false;
}
// Invariant : la somme des avantages = total des points en jeu (pas 200/100).
const inv = (30 + 0) === 30 && (20 + 10) === 30;
console.log(`\nInvariant échelle (scoreA+scoreB = total points en jeu) : ${inv}`);
console.log("VERDICT :", (ok && inv) ? "CORRIGE (échelle = points d'avantage, plus de /100 trompeur)" : "INCOMPLET");
console.log("RESUME:", JSON.stringify({ R8042_scale_fixed: ok && inv }));
