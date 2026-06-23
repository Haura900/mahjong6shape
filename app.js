const STATS_KEY = "sixShapeTrainerStats";
const TILE_CANDIDATES = ["1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "3z"];
const DAY_MS = 24 * 60 * 60 * 1000;

const state = {
  data: null,
  namedShapeDistance: new Map(),
  current: null,
  previousShapes: [],
  selectedUkeire: new Set(),
  selectedChanges: new Set(),
  selectedChangeOrder: [],
  selectedDiscards: new Map(),
  pendingChangeTile: "",
  judged: false,
  nextShape: "",
  nextTransition: null,
  transitionAnimation: null,
  stats: loadStats(),
};

const el = {};

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  restoreSettingsToControls();
  bindEvents();
  renderStats();
  try {
    await loadData();
    nextQuestion();
  } catch (error) {
    showLoadError(error);
  }
});

function bindElements() {
  for (const id of [
    "statsSummary",
    "statsByName",
    "dailyAccuracyChart",
    "resetStatsButton",
    "namedShapeWeightMultiplier",
    "includeUnnecessaryTileToggle",
    "reviewModeToggle",
    "questionCard",
    "handText",
    "shapeName",
    "transitionAnimation",
    "handTiles",
    "ukeireButtons",
    "changeButtons",
    "discardPanels",
    "discardModal",
    "discardModalBackdrop",
    "discardModalClose",
    "discardModalLead",
    "discardModalDrawTile",
    "discardModalButtons",
    "discardModalClear",
    "resultModal",
    "resultModalBackdrop",
    "resultModalClose",
    "resultModalBody",
    "resultNextButton",
    "judgeButton",
    "showAnswerButton",
    "previousButton",
    "nextButton",
    "specifiedShapeInput",
    "specifiedShapeButton",
    "specifiedShapeMessage",
    "resultPanel",
  ]) {
    el[id] = document.getElementById(id);
  }
  el.tileButtonTemplate = document.getElementById("tileButtonTemplate");
}

function bindEvents() {
  el.previousButton.addEventListener("click", previousQuestion);
  el.nextButton.addEventListener("click", nextQuestion);
  el.specifiedShapeButton.addEventListener("click", switchToSpecifiedProblem);
  el.specifiedShapeInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") switchToSpecifiedProblem();
  });
  el.judgeButton.addEventListener("click", () => judge(false));
  el.showAnswerButton.addEventListener("click", () => judge(true));
  el.resetStatsButton.addEventListener("click", resetStats);
  el.discardModalBackdrop.addEventListener("click", closeDiscardModal);
  el.discardModalClose.addEventListener("click", closeDiscardModal);
  el.discardModalClear.addEventListener("click", clearPendingChangeTile);
  el.resultModalBackdrop.addEventListener("click", closeResultModal);
  el.resultModalClose.addEventListener("click", closeResultModal);
  el.resultNextButton.addEventListener("click", nextQuestion);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDiscardModal();
      closeResultModal();
    }
  });
  el.namedShapeWeightMultiplier.addEventListener("change", () => {
    el.namedShapeWeightMultiplier.value = String(normalizedNamedShapeMultiplier());
    state.stats.settings.namedShapeWeightMultiplier = normalizedNamedShapeMultiplier();
    saveStats();
  });
  el.includeUnnecessaryTileToggle.addEventListener("change", () => {
    state.stats.settings.includeUnnecessaryTileShapes = el.includeUnnecessaryTileToggle.checked;
    saveStats();
  });
}

async function loadData() {
  if (window.SIX_SHAPE_QUIZ_DATA) {
    state.data = window.SIX_SHAPE_QUIZ_DATA;
    buildNamedShapeDistances();
    return;
  }
  const response = await fetch("quiz-data.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`quiz-data.jsonを読み込めません: ${response.status}`);
  }
  state.data = await response.json();
  buildNamedShapeDistances();
}

function buildNamedShapeDistances() {
  const problems = state.data?.problems || [];
  const reverseEdges = new Map();
  const queue = [];
  state.namedShapeDistance = new Map();

  for (const problem of problems) {
    reverseEdges.set(problem.shape, []);
  }

  for (const problem of problems) {
    for (const change of problem.changes || []) {
      if (!reverseEdges.has(change.toShape)) reverseEdges.set(change.toShape, []);
      reverseEdges.get(change.toShape).push(problem.shape);
    }
  }

  for (const problem of problems) {
    if (problem.isNamedShape) {
      state.namedShapeDistance.set(problem.shape, 0);
      queue.push(problem.shape);
    }
  }

  for (let index = 0; index < queue.length; index += 1) {
    const shape = queue[index];
    const distance = state.namedShapeDistance.get(shape);
    for (const previous of reverseEdges.get(shape) || []) {
      if (state.namedShapeDistance.has(previous)) continue;
      state.namedShapeDistance.set(previous, distance + 1);
      queue.push(previous);
    }
  }
}

function nextQuestion() {
  if (!state.data?.problems?.length) return;
  const previous = state.current;
  if (state.current) state.previousShapes.push(state.current.shape);
  const transition = !isReviewMode() && state.nextTransition ? state.nextTransition : null;
  state.current = takeNextProblem();
  state.transitionAnimation = buildTransitionAnimation(previous, state.current, transition);
  resetQuestionState();
  renderQuestion();
  scrollQuestionToTop();
}

function previousQuestion() {
  if (!state.previousShapes.length) return;
  const previousShape = state.previousShapes.pop();
  const previous = findProblem(previousShape);
  if (!previous) return;
  state.nextShape = "";
  state.nextTransition = null;
  state.current = previous;
  state.transitionAnimation = null;
  resetQuestionState();
  renderQuestion();
  scrollQuestionToTop();
}

function switchToSpecifiedProblem() {
  const normalized = normalizeSpecifiedShape(el.specifiedShapeInput.value);
  if (!normalized) {
    el.specifiedShapeMessage.textContent = "1〜9の数字6枚を入力してください。";
    return;
  }

  const problem = findProblem(normalized);
  if (!problem) {
    el.specifiedShapeMessage.textContent = `${normalized} は出題データにありません。`;
    return;
  }

  if (state.current) state.previousShapes.push(state.current.shape);
  state.current = problem;
  state.nextShape = "";
  state.nextTransition = null;
  state.transitionAnimation = null;
  resetQuestionState();
  renderQuestion();
  el.specifiedShapeMessage.textContent = `${normalized} に切り替えました。`;
  scrollQuestionToTop();
}

function normalizeSpecifiedShape(value) {
  const digits = String(value || "").trim().toLowerCase().replace(/m$/, "");
  if (!/^[1-9]{6}$/.test(digits)) return "";
  return `${[...digits].sort().join("")}m`;
}

function scrollQuestionToTop() {
  requestAnimationFrame(() => {
    el.questionCard.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function buildTransitionAnimation(previous, current, transition) {
  if (!previous || !current) return null;
  if (transition && transition.toShape === current.shape) {
    return {
      type: "change",
      fromHand: previous.hand,
      toHand: current.hand,
      draw: transition.draw,
      discard: transition.discard,
    };
  }
  return {
    type: "shuffle",
    fromHand: previous.hand,
    toHand: current.hand,
  };
}

function resetQuestionState() {
  state.selectedUkeire = new Set();
  state.selectedChanges = new Set();
  state.selectedChangeOrder = [];
  state.selectedDiscards = new Map();
  state.pendingChangeTile = "";
  state.judged = false;
  closeDiscardModal();
  closeResultModal();
  el.resultPanel.classList.add("hidden");
  el.resultPanel.innerHTML = "";
}

function takeNextProblem() {
  if (!isReviewMode() && state.nextShape) {
    const next = findProblem(state.nextShape);
    state.nextShape = "";
    state.nextTransition = null;
    if (next && shouldIncludeProblem(next)) return next;
  }
  state.nextTransition = null;
  const eligibleProblems = state.data.problems.filter(shouldIncludeProblem);
  if (isReviewMode()) {
    const dueProblems = eligibleProblems.filter(isReviewDue);
    if (dueProblems.length) return weightedRandomProblem(dueProblems);
  }
  return weightedRandomProblem(eligibleProblems);
}

function findProblem(shape) {
  return state.data.problems.find((problem) => problem.shape === shape);
}

function isReviewMode() {
  return Boolean(el.reviewModeToggle?.checked);
}

function shouldIncludeProblem(problem) {
  if (el.includeUnnecessaryTileToggle?.checked) return true;
  return !String(problem.shapeName || "").includes("\u4e0d\u8981\u724c");
}

function isReviewDue(problem) {
  const review = state.stats.review?.[problem.shape];
  if (!review?.lastCorrectAt) return true;
  const lastCorrect = Date.parse(review.lastCorrectAt);
  if (!Number.isFinite(lastCorrect)) return true;
  const intervalDays = Math.max(0, Number(review.intervalDays) || 0);
  return Date.now() > lastCorrect + intervalDays * 1.5 * DAY_MS;
}

function weightedRandomProblem(problems) {
  const totalWeight = problems.reduce((sum, problem) => sum + effectiveProblemWeight(problem), 0);
  if (totalWeight <= 0) return problems[Math.floor(Math.random() * problems.length)];
  let cursor = Math.random() * totalWeight;
  for (const problem of problems) {
    cursor -= effectiveProblemWeight(problem);
    if (cursor < 0) return problem;
  }
  return problems[problems.length - 1];
}

function effectiveProblemWeight(problem) {
  const baseWeight = Math.max(0, Number(problem.weight) || 0);
  return isGoodShapeProblem(problem) ? baseWeight * normalizedNamedShapeMultiplier() : baseWeight;
}

function isGoodShapeProblem(problem) {
  return Boolean(problem.isNamedShape || (problem.changes || []).some((change) => change.isNamedShape));
}

function normalizedNamedShapeMultiplier() {
  const value = Number(el.namedShapeWeightMultiplier?.value || 10);
  if (!Number.isFinite(value)) return 10;
  return Math.min(20, Math.max(1, value));
}

function restoreSettingsToControls() {
  const value = Number(state.stats.settings?.namedShapeWeightMultiplier ?? 10);
  el.namedShapeWeightMultiplier.value = String(Math.min(20, Math.max(1, value)));
  el.includeUnnecessaryTileToggle.checked = Boolean(
    state.stats.settings?.includeUnnecessaryTileShapes ?? false,
  );
}

function showLoadError(error) {
  console.error(error);
  el.handText.textContent = "問題データの読み込みに失敗しました";
  el.shapeName.textContent = "";
  el.resultPanel.classList.remove("hidden");
  el.resultPanel.innerHTML = `
    <h2 class="result-title wrong">読み込みエラー</h2>
    <p>quiz-data.js または quiz-data.json を読み込めませんでした。</p>
    <p class="small">GitHub Pagesではそのまま動きます。ローカルで確認する場合は、リポジトリルートで <code>python -m http.server 8765</code> を実行して <code>http://127.0.0.1:8765/</code> を開いてください。</p>
    <pre>${escapeHtml(error?.message || String(error))}</pre>
  `;
}

function renderQuestion(playTransitionAnimation = true) {
  const problem = state.current;
  el.previousButton.disabled = state.previousShapes.length === 0;
  el.handText.textContent = problem.hand;
  el.shapeName.textContent = isReviewMode() ? "復習" : "";
  if (playTransitionAnimation) renderTransitionAnimation();
  renderTileImages(
    el.handTiles,
    problem.handTiles,
    playTransitionAnimation ? state.transitionAnimation : null,
  );
  renderTileButtonGroup(el.ukeireButtons, TILE_CANDIDATES, "ukeire");
  renderTileButtonGroup(el.changeButtons, TILE_CANDIDATES.filter((tile) => tile !== "3z"), "change");
  renderDiscardPanels();
}

function renderTransitionAnimation() {
  const animation = state.transitionAnimation;
  el.transitionAnimation.innerHTML = "";
  el.transitionAnimation.classList.add("hidden");
  if (!animation) return;

  el.transitionAnimation.classList.remove("hidden");
  if (animation.type === "change") {
    el.transitionAnimation.innerHTML = `
      <div class="transition-card transition-change">
        <span class="transition-label">前問</span>
        <strong>${escapeHtml(animation.fromHand)}</strong>
        <span class="transition-arrow">→</span>
        <span class="transition-action">ツモ ${tileImagesHtml([animation.draw])}</span>
        <span class="transition-action">打 ${tileImagesHtml([animation.discard])}</span>
        <span class="transition-arrow">→</span>
        <span class="transition-label">今問</span>
        <strong>${escapeHtml(animation.toHand)}</strong>
      </div>
    `;
    return;
  }

  el.transitionAnimation.classList.add("hidden");
}

function renderTileImages(container, tiles, animation = null) {
  container.innerHTML = "";
  let highlightedDraw = false;
  for (const tile of tiles) {
    const img = document.createElement("img");
    img.className = "tile-img";
    if (animation?.type === "shuffle") img.classList.add("tile-shuffle");
    if (animation?.type === "change" && tile === animation.draw && !highlightedDraw) {
      img.classList.add("tile-drawn");
      highlightedDraw = true;
    }
    img.src = tileImageSrc(tile);
    img.alt = tile;
    img.title = tile;
    container.appendChild(img);
  }
}

function renderTileButtonGroup(container, tiles, kind) {
  container.innerHTML = "";
  for (const tile of tiles) {
    const button = createTileButton(tile);
    button.dataset.tile = tile;
    button.dataset.kind = kind;
    button.classList.toggle("selected", isSelected(kind, tile));
    if (kind === "ukeire" && state.selectedChanges.has(tile)) button.disabled = true;
    if (kind === "change" && state.selectedUkeire.has(tile)) button.disabled = true;
    button.addEventListener("click", () => toggleTile(kind, tile));
    container.appendChild(button);
  }
}

function createTileButton(tile) {
  const button = el.tileButtonTemplate.content.firstElementChild.cloneNode(true);
  const img = button.querySelector("img");
  const label = button.querySelector("span");
  img.src = tileImageSrc(tile);
  img.alt = tile;
  img.title = tile;
  label.textContent = tile;
  return button;
}

function isSelected(kind, tile) {
  if (kind === "ukeire") return state.selectedUkeire.has(tile);
  if (kind === "change") return state.selectedChanges.has(tile);
  return false;
}

function toggleTile(kind, tile) {
  if (state.judged) return;
  if (kind === "change") {
    if (state.selectedUkeire.has(tile)) return;
    openDiscardModal(tile);
    return;
  }

  const selected = kind === "ukeire" ? state.selectedUkeire : state.selectedChanges;
  const other = kind === "ukeire" ? state.selectedChanges : state.selectedUkeire;
  if (!selected.has(tile) && other.has(tile)) return;

  if (selected.has(tile)) {
    selected.delete(tile);
  } else {
    selected.add(tile);
  }
  renderQuestion(false);
}

function openDiscardModal(changeTile) {
  state.pendingChangeTile = changeTile;
  el.discardModalLead.textContent = `${changeTile}をツモした後に切る牌を選んでください。`;
  el.discardModalDrawTile.innerHTML = `
    <span>ツモ</span>
    <img src="${tileImageSrc(changeTile)}" alt="${changeTile}" title="${changeTile}">
    <strong>${escapeHtml(changeTile)}</strong>
  `;

  el.discardModalButtons.innerHTML = "";
  const discardCandidates = uniqueTilesInHand(state.current.handTiles).filter((candidate) => candidate !== "3z");
  for (const discard of discardCandidates) {
    const button = createTileButton(discard);
    button.classList.toggle("selected", state.selectedDiscards.get(changeTile) === discard);
    button.addEventListener("click", () => selectDiscardForChange(changeTile, discard));
    el.discardModalButtons.appendChild(button);
  }

  el.discardModalClear.disabled = !state.selectedChanges.has(changeTile);
  el.discardModal.classList.remove("hidden");
}

function closeDiscardModal() {
  if (!el.discardModal || el.discardModal.classList.contains("hidden")) return;
  el.discardModal.classList.add("hidden");
  state.pendingChangeTile = "";
}

function closeResultModal() {
  if (!el.resultModal || el.resultModal.classList.contains("hidden")) return;
  el.resultModal.classList.add("hidden");
}

function selectDiscardForChange(changeTile, discard) {
  if (state.judged) return;
  state.selectedChanges.add(changeTile);
  state.selectedDiscards.set(changeTile, discard);
  state.selectedChangeOrder = [changeTile, ...state.selectedChangeOrder.filter((value) => value !== changeTile)];
  closeDiscardModal();
  renderQuestion(false);
}

function clearPendingChangeTile() {
  const changeTile = state.pendingChangeTile;
  if (!changeTile || state.judged) return;
  state.selectedChanges.delete(changeTile);
  state.selectedDiscards.delete(changeTile);
  state.selectedChangeOrder = state.selectedChangeOrder.filter((value) => value !== changeTile);
  closeDiscardModal();
  renderQuestion(false);
}

function renderDiscardPanels() {
  el.discardPanels.innerHTML = "";
  const changeTiles = state.selectedChangeOrder.filter((tile) => state.selectedChanges.has(tile));
  if (!changeTiles.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "変化牌を選ぶと、その牌ごとの打牌選択が表示されます。";
    el.discardPanels.appendChild(empty);
    return;
  }

  for (const changeTile of changeTiles) {
    const panel = document.createElement("section");
    panel.className = "discard-panel";

    const drawTile = document.createElement("div");
    drawTile.className = "discard-draw-tile";
    drawTile.innerHTML = `<img src="${tileImageSrc(changeTile)}" alt="${changeTile}" title="${changeTile}"><span>ツモ ${changeTile}</span>`;
    panel.appendChild(drawTile);

    const body = document.createElement("button");
    body.type = "button";
    body.className = "discard-panel-body discard-summary-button";
    body.disabled = state.judged;
    body.addEventListener("click", () => openDiscardModal(changeTile));
    const title = document.createElement("h4");
    title.textContent = "打牌";
    body.appendChild(title);

    const selected = state.selectedDiscards.get(changeTile);
    body.insertAdjacentHTML(
      "beforeend",
      selected
        ? `<div class="tile-row">${tileImagesHtml([selected])}<span>${escapeHtml(selected)}</span></div>`
        : `<p class="hint">未選択</p>`,
    );
    panel.appendChild(body);
    el.discardPanels.appendChild(panel);
  }
}

function judge(showOnly) {
  if (!state.current || state.judged) return;
  const evaluation = evaluateAnswer();
  state.judged = true;
  if (!showOnly) {
    state.nextTransition = chooseNextTransitionAfterJudge(evaluation);
    state.nextShape = state.nextTransition?.toShape || "";
  }
  renderResult(evaluation, showOnly);
  if (!showOnly) {
    updateStats(evaluation);
    saveStats();
    renderStats();
  }
}

function chooseNextTransitionAfterJudge(evaluation) {
  const changes = evaluation.problem.changes || [];
  if (!changes.length) return null;
  const candidates = chooseNamedShapeRouteCandidates(evaluation.problem, changes);
  if (!candidates.length) return null;
  return weightedChangePick(candidates);
}

function chooseNamedShapeRouteCandidates(problem, candidates) {
  if (!candidates.length) return candidates;
  const includedCandidates = candidates.filter((change) => {
    const destination = findProblem(change.toShape);
    return destination && shouldIncludeProblem(destination);
  });
  if (!includedCandidates.length) return [];
  candidates = includedCandidates;
  candidates = filterSimulatorPreferredCandidates(candidates);

  if (problem.isNamedShape) {
    const namedCandidates = candidates.filter((change) => isNamedShape(change.toShape));
    if (namedCandidates.length) return namedCandidates;
  }

  const currentDistance = namedShapeDistance(problem.shape);
  const closerCandidates = candidates.filter((change) => namedShapeDistance(change.toShape) < currentDistance);
  if (closerCandidates.length) {
    const bestDistance = Math.min(...closerCandidates.map((change) => namedShapeDistance(change.toShape)));
    return closerCandidates.filter((change) => namedShapeDistance(change.toShape) === bestDistance);
  }

  return candidates;
}

function filterSimulatorPreferredCandidates(candidates) {
  const byDraw = new Map();
  for (const change of candidates) {
    if (!byDraw.has(change.draw)) byDraw.set(change.draw, []);
    byDraw.get(change.draw).push(change);
  }
  return [...byDraw.values()].flatMap((drawChanges) => {
    const preferred = drawChanges.filter((change) => change.simulatorPreferred === true);
    return preferred.length ? preferred : drawChanges;
  });
}

function namedShapeDistance(shape) {
  return state.namedShapeDistance.get(shape) ?? Number.POSITIVE_INFINITY;
}

function isNamedShape(shape) {
  return Boolean(findProblem(shape)?.isNamedShape);
}

function weightedChangePick(candidates) {
  const totalWeight = candidates.reduce((sum, change) => {
    const problem = findProblem(change.toShape);
    return sum + (problem ? effectiveProblemWeight(problem) : 0);
  }, 0);
  if (totalWeight <= 0) return candidates[Math.floor(Math.random() * candidates.length)];
  let cursor = Math.random() * totalWeight;
  for (const change of candidates) {
    const problem = findProblem(change.toShape);
    cursor -= problem ? effectiveProblemWeight(problem) : 0;
    if (cursor < 0) return change;
  }
  return candidates[candidates.length - 1];
}

function evaluateAnswer() {
  const problem = state.current;
  const correctUkeire = new Set(problem.ukeireTiles);
  const selectedUkeire = state.selectedUkeire;
  const correctChanges = new Map(problem.changes.map((change) => [change.draw, change]));
  const selectedChanges = state.selectedChanges;
  const namedChanges = problem.changes.filter((change) => change.isNamedShape);

  const ukeireCorrect = intersection(selectedUkeire, correctUkeire);
  const ukeireMissed = difference(correctUkeire, selectedUkeire);
  const ukeireExtra = difference(selectedUkeire, correctUkeire);
  const changeCorrect = intersection(selectedChanges, new Set(correctChanges.keys()));
  const changeMissed = difference(new Set(correctChanges.keys()), selectedChanges);
  const changeExtra = difference(selectedChanges, new Set(correctChanges.keys()));

  const discardResults = buildDiscardResults(problem.changes);

  const namedChangeMisses = namedChanges.filter((change) => !selectedChanges.has(change.draw));
  const namedDiscardErrors = discardResults.filter(
    (change) => change.isNamedShape && selectedChanges.has(change.draw) && !change.discardCorrect,
  );

  const ukeireHasError = ukeireMissed.length > 0 || ukeireExtra.length > 0;
  const criticalChangeError = namedChangeMisses.length > 0 || namedDiscardErrors.length > 0;
  const exactChanges =
    changeMissed.length === 0 &&
    changeExtra.length === 0 &&
    discardResults.every((change) => state.selectedChanges.has(change.draw) && change.discardCorrect);
  const perfect = !ukeireHasError && exactChanges;
  const correct = !ukeireHasError && !criticalChangeError;

  return {
    problem,
    perfect,
    correct,
    status: perfect ? "perfect" : correct ? "correct" : "wrong",
    ukeireCorrect,
    ukeireMissed,
    ukeireExtra,
    changeCorrect,
    changeMissed,
    changeExtra,
    discardResults,
    namedChangeMisses,
    namedDiscardErrors,
    ukeireHasError,
    criticalChangeError,
  };
}

function buildDiscardResults(changes) {
  const byDraw = new Map();
  for (const change of changes) {
    if (!byDraw.has(change.draw)) byDraw.set(change.draw, []);
    byDraw.get(change.draw).push(change);
  }

  return [...byDraw.entries()].map(([draw, drawChanges]) => {
    const maxUkeireCount = Math.max(...drawChanges.map((change) => change.toUkeireCount));
    const maxUkeireChanges = drawChanges.filter((change) => change.toUkeireCount === maxUkeireCount);
    const acceptedChanges = maxUkeireChanges;
    const acceptedDiscards = uniqueStrings(acceptedChanges.map((change) => change.discard)).sort(tileSort);
    const selected = state.selectedDiscards.get(draw) || "";
    const representative =
      acceptedChanges.find((change) => change.discard === selected)
      || acceptedChanges.find((change) => change.simulatorPreferred === true)
      || acceptedChanges[0];
    return {
      ...representative,
      draw,
      discard: acceptedDiscards[0] || representative.discard,
      acceptedDiscards,
      selectedDiscard: selected,
      discardCorrect: acceptedDiscards.includes(selected),
      isNamedShape: acceptedChanges.some((change) => change.isNamedShape),
    };
  });
}

function renderResult(result, showOnly) {
  const titleText = showOnly
    ? "答え"
    : result.status === "perfect"
      ? "大正解"
      : result.status === "correct"
        ? "正解"
        : "不正解";
  const resultHtml = `
    <h2 class="result-title ${result.status}">${escapeHtml(titleText)}</h2>
    <section class="result-box result-hand">
      <h4>元の手牌</h4>
      <div class="tile-row">${tileImagesHtml(result.problem.handTiles)}</div>
      <p>${escapeHtml(result.problem.hand)} ${escapeHtml(result.problem.shapeName)}</p>
    </section>
    ${showOnly ? '<p class="warn">この表示では成績は更新していません。</p>' : ""}
    ${!showOnly && state.nextShape ? `<p class="ok">次の問題は変化後の ${escapeHtml(state.nextShape)}33z です。</p>` : ""}
    <div class="result-grid">
      ${renderTileResultBox("受け入れ牌", result.ukeireCorrect, result.ukeireMissed, result.ukeireExtra)}
      ${renderTileResultBox("変化牌", result.changeCorrect, result.changeMissed, result.changeExtra)}
      ${renderDiscardResultBox(result)}
    </div>
    <section class="result-box answer-list">
      <h4>変化の正解</h4>
      ${result.problem.changes.length ? result.problem.changes.map(renderChangeAnswer).join("") : "<p>変化牌なし</p>"}
    </section>
  `;
  el.resultPanel.innerHTML = resultHtml;
  el.resultPanel.classList.remove("hidden");
  el.resultModalBody.innerHTML = resultHtml;
  el.resultModal.classList.remove("hidden");
}

function renderTileResultBox(title, correct, missed, extra) {
  return `
    <section class="result-box">
      <h4>${escapeHtml(title)}</h4>
      <p><span class="ok">正しく選択:</span> ${formatTileList(correct)}</p>
      <p><span class="ng">選び漏れ:</span> ${formatTileList(missed)}</p>
      <p><span class="warn">余計に選択:</span> ${formatTileList(extra)}</p>
    </section>
  `;
}

function renderDiscardResultBox(result) {
  const rows = result.discardResults
    .filter((change) => state.selectedChanges.has(change.draw) || change.isNamedShape)
    .map((change) => {
      const status = change.discardCorrect ? "ok" : change.isNamedShape ? "ng" : "warn";
      const mark = change.discardCorrect ? "○" : change.isNamedShape ? "×" : "△";
      const note = change.discardCorrect
        ? ""
        : change.isNamedShape
          ? "（良形の打牌ミス）"
          : "（参考: 非良形の打牌違い）";
      const selected = change.selectedDiscard || "未選択";
      const correctDiscards = change.acceptedDiscards?.length ? change.acceptedDiscards.join(" / ") : change.discard;
      const furitenNote = change.furitenRisk
        ? "（正解。ただし変化後にフリテンとなる可能性あり）"
        : "";
      const simulatorNote =
        change.discardCorrect && change.simulatorPreferred === false
          ? `（正解。ただし何切る期待値では最良より ${Math.abs(
              Number(change.simulatorDifferenceFromBest || 0),
            ).toFixed(4)} 低い）`
          : "";
      return `
        <p class="discard-result ${status}">
          <strong>${mark} ${escapeHtml(change.draw)}</strong>:
          選択 ${escapeHtml(selected)} / 正解 ${escapeHtml(correctDiscards)}
          ${change.isNamedShape ? "（良形）" : ""} ${note} ${furitenNote} ${simulatorNote}
        </p>
      `;
    })
    .join("");
  return `
    <section class="result-box">
      <h4>打牌</h4>
      ${rows || "<p>選択された変化牌なし</p>"}
    </section>
  `;
}

function renderChangeAnswer(change) {
  const delta = change.toUkeireCount - change.fromUkeireCount;
  const deltaText = delta >= 0 ? `+${delta}` : `${delta}`;
  return `
    <div class="change-answer">
      <div>
        <strong>ツモ ${escapeHtml(change.draw)} / 打 ${escapeHtml(change.discard)}</strong>
        ${change.isNamedShape ? ' <span class="ok">良形変化</span>' : ""}
        ${change.simulatorPreferred === true ? ' <span class="ok">何切る最良</span>' : ""}
        ${change.simulatorPreferred === false ? ' <span class="warn">期待値劣後</span>' : ""}
        ${change.furitenRisk === true ? ' <span class="warn">フリテン注意</span>' : ""}
      </div>
      <div class="tile-row">${tileImagesHtml(shapeToHandTiles(change.toShape))}</div>
      <div>${escapeHtml(change.toHand)} ${escapeHtml(change.toShapeName)}</div>
      <div class="small">受け入れ枚数: ${change.fromUkeireCount} → ${change.toUkeireCount} (${deltaText})</div>
      ${renderSimulatorComparison(change)}
      ${renderFuritenRisk(change)}
    </div>
  `;
}

function renderFuritenRisk(change) {
  const details = change.furitenRiskDetails || [];
  if (!details.length) return "";
  const rows = details.map((detail) => {
    const waits = (detail.waits || [])
      .filter((tile) => tile.endsWith("m"))
      .join("・");
    return `
      <div>
        次にツモ${escapeHtml(detail.draw)} / 打${escapeHtml(detail.discard)}
        → ${escapeHtml(detail.toShape)}:
        待ち ${escapeHtml(waits || (detail.waits || []).join("・"))}
      </div>
    `;
  }).join("");
  return `
    <div class="furiten-warning">
      <strong>注意: この打牌は正解ですが、後の良形変化でフリテンになる可能性があります</strong>
      <div>先に切る牌: ${escapeHtml(change.discard)}</div>
      ${rows}
    </div>
  `;
}

function renderSimulatorComparison(change) {
  const comparison = change.simulatorComparison;
  if (!comparison) return "";
  const candidate = (comparison.candidates || []).find(
    (item) => item.discard === change.discard,
  );
  if (!candidate) return "";
  const bestText = (comparison.candidates || [])
    .filter((item) => item.isBest)
    .map((item) => `打${item.discard} ${formatExpectedScore(item.expectedScore)}`)
    .join(" / ");
  const difference = Number(candidate.differenceFromBest || 0);
  const differenceText = Math.abs(difference) < 1e-9
    ? "最良"
    : `最良との差 ${difference.toFixed(4)}`;
  const warning = change.simulatorPreferred === false
    ? '<div class="simulator-warning"><strong>注意: この打牌は正解ですが、何切るシミュレーターの期待値では最良ではありません</strong></div>'
    : "";
  return `
    <div class="simulator-comparison">
      ${warning}
      <div>
        何切るシミュレーター:
        打${escapeHtml(candidate.discard)}
        期待値 ${formatExpectedScore(candidate.expectedScore)}
        (${escapeHtml(differenceText)})
      </div>
      <div>比較上位: ${escapeHtml(bestText)}</div>
      <div class="small">
        ${escapeHtml(comparison.hand)} / 9巡目 / 東場南家 / ドラ表示牌なし
      </div>
    </div>
  `;
}

function formatExpectedScore(value) {
  return Number(value).toFixed(4);
}

function updateStats(result) {
  const stats = state.stats;
  const now = new Date();
  const nowIso = now.toISOString();
  const shape = result.problem.shape;

  stats.totalQuestions += 1;
  if (result.perfect) stats.correctQuestions += 1;
  if (result.correct) stats.correctAnswers += 1;
  if (result.ukeireHasError) stats.ukeireMisses += 1;
  if (result.criticalChangeError) stats.changeMisses += 1;

  if (!stats.shapeStats[shape]) {
    stats.shapeStats[shape] = { seen: 0, perfect: 0, correct: 0, ukeireMisses: 0, changeMisses: 0 };
  }
  const shapeStats = stats.shapeStats[shape];
  shapeStats.seen += 1;
  if (result.perfect) shapeStats.perfect += 1;
  if (result.correct) shapeStats.correct += 1;
  if (result.ukeireHasError) shapeStats.ukeireMisses += 1;
  if (result.criticalChangeError) shapeStats.changeMisses += 1;

  if (!stats.review[shape]) {
    stats.review[shape] = { lastCorrectAt: "", intervalDays: 0 };
  }
  const review = stats.review[shape];
  if (result.correct) {
    const previous = review.lastCorrectAt ? Date.parse(review.lastCorrectAt) : NaN;
    review.intervalDays = Number.isFinite(previous)
      ? Math.max(1, Math.floor((now.getTime() - previous) / DAY_MS) + 1)
      : 1;
    review.lastCorrectAt = nowIso;
  } else {
    review.lastCorrectAt = "";
    review.intervalDays = 0;
  }

  stats.history.push({
    timestamp: nowIso,
    date: dateKey(now),
    shape,
    hand: result.problem.hand,
    shapeName: result.problem.shapeName,
    status: result.status,
    correct: result.correct,
    perfect: result.perfect,
    ukeireHasError: result.ukeireHasError,
    criticalChangeError: result.criticalChangeError,
    selectedUkeire: [...state.selectedUkeire].sort(tileSort),
    correctUkeire: result.problem.ukeireTiles,
    selectedChanges: [...state.selectedChanges].sort(tileSort),
    correctChanges: uniqueStrings(result.problem.changes.map((change) => change.draw)).sort(tileSort),
    selectedDiscards: Object.fromEntries(state.selectedDiscards),
    correctDiscards: Object.fromEntries(
      result.discardResults.map((change) => [
        change.draw,
        change.acceptedDiscards?.length ? change.acceptedDiscards.join("/") : change.discard,
      ]),
    ),
  });
}

function loadStats() {
  const fallback = {
    totalQuestions: 0,
    correctQuestions: 0,
    correctAnswers: 0,
    ukeireMisses: 0,
    changeMisses: 0,
    shapeStats: {},
    review: {},
    history: [],
    settings: {
      namedShapeWeightMultiplier: 10,
      includeUnnecessaryTileShapes: false,
    },
  };
  try {
    const raw = localStorage.getItem(STATS_KEY);
    if (!raw) return structuredCloneFallback(fallback);
    const parsed = { ...structuredCloneFallback(fallback), ...JSON.parse(raw) };
    if (parsed.correctAnswers == null) parsed.correctAnswers = parsed.correctQuestions || 0;
    if (!parsed.review) parsed.review = {};
    if (!Array.isArray(parsed.history)) parsed.history = [];
    parsed.settings = { ...fallback.settings, ...(parsed.settings || {}) };
    return parsed;
  } catch {
    return structuredCloneFallback(fallback);
  }
}

function structuredCloneFallback(value) {
  return JSON.parse(JSON.stringify(value));
}

function saveStats() {
  localStorage.setItem(STATS_KEY, JSON.stringify(state.stats));
}

function resetStats() {
  if (!confirm("成績をリセットしますか？この端末のブラウザ内の記録だけが削除されます。")) return;
  localStorage.removeItem(STATS_KEY);
  state.stats = loadStats();
  restoreSettingsToControls();
  renderStats();
}

function renderStats() {
  const stats = state.stats;
  const perfectRate = percent(stats.correctQuestions, stats.totalQuestions);
  const correctRate = percent(stats.correctAnswers || 0, stats.totalQuestions);
  el.statsSummary.innerHTML = `
    <dt>総出題数</dt><dd>${stats.totalQuestions}</dd>
    <dt>完全正解数</dt><dd>${stats.correctQuestions}</dd>
    <dt>正解数</dt><dd>${stats.correctAnswers || 0}</dd>
    <dt>完全正答率</dt><dd>${perfectRate}</dd>
    <dt>正答率</dt><dd>${correctRate}</dd>
    <dt>受け入れミス</dt><dd>${stats.ukeireMisses}</dd>
    <dt>変化ミス</dt><dd>${stats.changeMisses}</dd>
  `;
  renderStatsByName();
  renderDailyAccuracyChart();
}

function renderStatsByName() {
  const rows = aggregateStatsByName();
  if (!rows.length) {
    el.statsByName.innerHTML = "<p class=\"hint\">まだ成績詳細はありません。</p>";
    return;
  }
  el.statsByName.innerHTML = `
    <table class="stats-table">
      <thead><tr><th>形名</th><th>出題</th><th>正解</th><th>完全</th><th>正答率</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td>${escapeHtml(row.name)}</td>
            <td>${row.total}</td>
            <td>${row.correct}</td>
            <td>${row.perfect}</td>
            <td>${percent(row.correct, row.total)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function aggregateStatsByName() {
  const map = new Map();
  for (const item of state.stats.history) {
    const key = item.shapeName || "未分類";
    if (!map.has(key)) map.set(key, { name: key, total: 0, correct: 0, perfect: 0 });
    const row = map.get(key);
    row.total += 1;
    if (item.correct) row.correct += 1;
    if (item.perfect) row.perfect += 1;
  }
  return [...map.values()].sort((a, b) => b.total - a.total || a.name.localeCompare(b.name, "ja"));
}

function renderDailyAccuracyChart() {
  const canvas = el.dailyAccuracyChart;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  const daily = aggregateDailyStats();
  if (!daily.length) {
    ctx.fillStyle = "#57606a";
    ctx.font = "16px sans-serif";
    ctx.fillText("まだ日付別成績はありません。", 24, 48);
    return;
  }

  const padding = { left: 44, right: 18, top: 18, bottom: 38 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  ctx.strokeStyle = "#d0d7de";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top);
  ctx.lineTo(padding.left, padding.top + plotHeight);
  ctx.lineTo(padding.left + plotWidth, padding.top + plotHeight);
  ctx.stroke();

  ctx.fillStyle = "#57606a";
  ctx.font = "12px sans-serif";
  for (const rate of [0, 50, 100]) {
    const y = padding.top + plotHeight - (rate / 100) * plotHeight;
    ctx.fillText(`${rate}%`, 8, y + 4);
    ctx.strokeStyle = "#eef1f4";
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(padding.left + plotWidth, y);
    ctx.stroke();
  }

  const points = daily.map((row, index) => {
    const x = padding.left + (daily.length === 1 ? plotWidth / 2 : (plotWidth * index) / (daily.length - 1));
    const y = padding.top + plotHeight - row.rate * plotHeight;
    return { ...row, x, y };
  });

  ctx.strokeStyle = "#0969da";
  ctx.lineWidth = 3;
  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();

  ctx.fillStyle = "#0969da";
  for (const point of points) {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.fillStyle = "#24292f";
  for (const point of points) {
    ctx.fillText(`${Math.round(point.rate * 100)}%`, point.x - 12, point.y - 8);
  }
  ctx.fillStyle = "#57606a";
  const first = points[0];
  const last = points[points.length - 1];
  ctx.fillText(first.date.slice(5), first.x - 16, height - 12);
  if (last !== first) ctx.fillText(last.date.slice(5), last.x - 16, height - 12);
}

function aggregateDailyStats() {
  const map = new Map();
  for (const item of state.stats.history) {
    const key = item.date || dateKey(new Date(item.timestamp));
    if (!map.has(key)) map.set(key, { date: key, total: 0, correct: 0 });
    const row = map.get(key);
    row.total += 1;
    if (item.correct) row.correct += 1;
  }
  return [...map.values()]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((row) => ({ ...row, rate: row.total ? row.correct / row.total : 0 }));
}

function percent(numerator, denominator) {
  return denominator ? `${Math.round((numerator / denominator) * 1000) / 10}%` : "0%";
}

function dateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function tileImageSrc(tile) {
  if (tile === "3z") return "pai-images/ji3-66-90-s.png";
  const match = tile.match(/^([1-9])m$/);
  if (!match) return "";
  return `pai-images/man${match[1]}-66-90-s.png`;
}

function tileImagesHtml(tiles) {
  return tiles
    .map((tile) => `<img class="tile-img" src="${tileImageSrc(tile)}" alt="${escapeHtml(tile)}" title="${escapeHtml(tile)}">`)
    .join("");
}

function shapeToHandTiles(shape) {
  return [...shape.replace("m", "")].map((digit) => `${digit}m`).concat(["3z", "3z"]);
}

function uniqueTilesInHand(tiles) {
  return [...new Set(tiles)].sort(tileSort);
}

function uniqueStrings(values) {
  return [...new Set(values)];
}

function intersection(a, b) {
  return [...a].filter((item) => b.has(item)).sort(tileSort);
}

function difference(a, b) {
  return [...a].filter((item) => !b.has(item)).sort(tileSort);
}

function formatTileList(tiles) {
  return tiles.length ? tileImagesHtml(tiles) : "なし";
}

function tileSort(a, b) {
  return tileOrder(a) - tileOrder(b);
}

function tileOrder(tile) {
  if (tile === "3z") return 30;
  const match = tile.match(/^([1-9])m$/);
  return match ? Number(match[1]) : 99;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
