/* global $, currentContextRunLabel */

function syncNextApplyViewState(){
  const dry = !!$("ckDryRun")?.checked;
  const quarantine = !!$("ckQuarantine")?.checked;
  const undoDry = !!$("ckUndoDryRun")?.checked;

  const modePill = $("applyModePill");
  if(modePill){
    modePill.textContent = dry ? "Simulation" : "Apply réel";
    modePill.classList.toggle("pillDanger", !dry);
  }

  const reviewPill = $("applyReviewPill");
  if(reviewPill){
    reviewPill.textContent = quarantine ? "_review actif" : "_review désactivé";
    reviewPill.classList.toggle("pillWarn", !quarantine);
  }

  const undoPill = $("applyUndoPill");
  if(undoPill){
    undoPill.textContent = undoDry ? "Undo dry-run" : "Undo réel";
    undoPill.classList.toggle("pillDanger", !undoDry);
  }

  const runPill = $("pillRun");
  if(runPill && !runPill.textContent?.trim()){
    runPill.textContent = `Run: ${currentContextRunLabel()}`;
  }
}

function bindNextApplyUi(){
  $("ckDryRun")?.addEventListener("change", syncNextApplyViewState);
  $("ckQuarantine")?.addEventListener("change", syncNextApplyViewState);
  $("ckUndoDryRun")?.addEventListener("change", syncNextApplyViewState);
  syncNextApplyViewState();
}

function enhanceNextApplyLayout(){
  const view = $("view-apply");
  if(!view || view.dataset.nextEnhanced === "1"){
    return;
  }
  view.dataset.nextEnhanced = "1";
  view.classList.add("applyNextView");

  const primary = view.querySelector(".viewPrimary");
  const legacyCard = primary?.querySelector(".card");
  if(!primary || !legacyCard){
    return;
  }

  const optionsGrid = legacyCard.querySelector(".grid2");
  const applyRow = $("btnApply")?.closest(".row");
  const applyResult = $("applyResult");
  const undoRow = $("btnUndoPreview")?.closest(".row");
  const undoResult = $("undoResult");

  const hero = document.createElement("div");
  hero.className = "card applyNextHero nextStageCard";
  hero.innerHTML = `
    <div class="applyNextHeroMain">
      <div class="panelEyebrow">Mise en production</div>
      <div class="cardTitle">Appliquer les lignes validées</div>
      <div class="muted">Commencez en simulation, vérifiez le résultat détaillé, puis passez au réel quand le lot est sûr.</div>
    </div>
    <div class="applyHeroMeta">
      <span class="pill" id="applyModePill">Simulation</span>
      <span class="pill" id="applyReviewPill">_review actif</span>
      <span class="pill" id="applyUndoPill">Undo dry-run</span>
    </div>
  `;

  const grid = document.createElement("div");
  grid.className = "applyNextGrid";

  const safetyCard = document.createElement("div");
  safetyCard.className = "card applySafetyCard nextWorkbenchCard nextSupportZone";
  safetyCard.innerHTML = `
    <div class="panelEyebrow">Sécurité</div>
    <div class="qualityPanelTitle">Préparer l'application</div>
    <div class="muted">Réglez le mode de passage avant de déclencher l’action principale. Les options restent compactes pour laisser la place au résultat.</div>
  `;
  if(optionsGrid){
    optionsGrid.classList.add("applySafetyOptions", "mt12");
    safetyCard.appendChild(optionsGrid);
  }
  const safetyHelp = document.createElement("details");
  safetyHelp.className = "detailsCard mt12";
  safetyHelp.innerHTML = `
    <summary>Conseil d’usage</summary>
    <ul class="muted mt10">
      <li>Confirmer la validation sauvegardée avant tout apply réel.</li>
      <li>Lancer un dry-run sur les gros lots ou les cas sensibles.</li>
      <li>Revenir sur Doublons si un doute persiste.</li>
    </ul>
  `;
  safetyCard.appendChild(safetyHelp);

  const resultCard = document.createElement("div");
  resultCard.className = "card applyResultCardNext nextWorkbenchCard nextDataZone";
  const resultHead = document.createElement("div");
  resultHead.className = "qualityPanelHead";
  resultHead.innerHTML = `
    <div>
      <div class="panelEyebrow">Action principale</div>
      <div class="qualityPanelTitle">Lancer l’application</div>
    </div>
  `;
  const applyMsg = $("applyMsg");
  if(applyMsg){
    applyMsg.classList.add("qualityInlineStatus");
    resultHead.appendChild(applyMsg);
  }
  resultCard.appendChild(resultHead);

  const primaryRow = document.createElement("div");
  primaryRow.className = "applyPrimaryRow mt12";
  const applyBtn = $("btnApply");
  if(applyBtn){
    primaryRow.appendChild(applyBtn);
  }
  resultCard.appendChild(primaryRow);

  const resultEyebrow = document.createElement("div");
  resultEyebrow.className = "applyResultHead mt12";
  resultEyebrow.innerHTML = '<div class="panelEyebrow">Résultat détaillé</div>';
  resultCard.appendChild(resultEyebrow);
  if(applyResult){
    resultCard.appendChild(applyResult);
  }

  grid.appendChild(safetyCard);
  grid.appendChild(resultCard);

  const undoCard = document.createElement("div");
  undoCard.className = "card applyUndoCardNext nextWorkbenchCard nextSupportZone";
  const undoHead = document.createElement("div");
  undoHead.className = "qualityPanelHead";
  undoHead.innerHTML = `
    <div>
      <div class="panelEyebrow">Secondaire</div>
      <div class="qualityPanelTitle">Undo du dernier apply</div>
    </div>
  `;
  const undoMsg = $("undoMsg");
  if(undoMsg){
    undoMsg.classList.add("qualityInlineStatus");
    undoHead.appendChild(undoMsg);
  }
  undoCard.appendChild(undoHead);

  const undoLead = document.createElement("div");
  undoLead.className = "muted";
  undoLead.textContent = "Prévisualisez toujours l’Undo avant de le lancer en réel. Aucune cible existante n’est écrasée pendant une restauration.";
  undoCard.appendChild(undoLead);

  if(undoRow){
    undoRow.classList.add("applyUndoToolbar", "mt12");
    undoCard.appendChild(undoRow);
  }
  if(undoResult){
    undoResult.classList.add("mt12");
    undoCard.appendChild(undoResult);
  }

  primary.replaceChildren(hero, grid, undoCard);
  syncNextApplyViewState();
}
