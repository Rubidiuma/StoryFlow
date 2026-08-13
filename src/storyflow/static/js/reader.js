(function () {
  "use strict";

  const page = document.querySelector("main[data-story-id]");
  if (!page) return;

  const storyId = page.dataset.storyId;
  const generateUrl = page.dataset.generateUrl;
  const streamArea = page.querySelector(".segment-stream");
  const errorBanner = page.querySelector(".reader-error");
  let activeRequest = false;
  let sceneCount = page.querySelectorAll(".segment").length;

  const summaryToggle = page.querySelector("[data-summary-toggle]");
  const summaryPanel = page.querySelector("[data-view='story-summary']");
  if (summaryToggle && summaryPanel) {
    summaryToggle.addEventListener("click", () => {
      const expanded = summaryToggle.getAttribute("aria-expanded") === "true";
      summaryToggle.setAttribute("aria-expanded", String(!expanded));
      summaryPanel.hidden = expanded;
    });
  }

  page.addEventListener("click", async (event) => {
    const branchButton = event.target.closest("[data-create-branch]");
    if (!branchButton || branchButton.disabled) return;
    const suggested = `新路线 ${new Date().toLocaleString("zh-CN", { hour12: false })}`;
    const entered = window.prompt("为新路线命名（原路线会完整保留）", suggested);
    if (entered === null) return;
    branchButton.disabled = true;
    _clearError();
    try {
      const response = await fetch(`/api/choices/${branchButton.dataset.choiceId}/branch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: entered.trim() || suggested }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body) {
        _showError("无法创建新路线，请稍后重试。");
        branchButton.disabled = false;
        return;
      }
      window.location.assign(`/stories/${storyId}/reader?branch=${body.branch_id}`);
    } catch {
      _showError("网络错误，无法创建新路线。");
      branchButton.disabled = false;
    }
  });

  // Inject a live "generating" indicator just before reader-controls
  const genIndicator = document.createElement("div");
  genIndicator.className = "reader-generating";
  genIndicator.hidden = true;
  genIndicator.innerHTML = '<span class="spinner"></span><span>正在生成…</span>';
  const controls = page.querySelector(".reader-controls");
  if (controls) controls.before(genIndicator);

  function _setGenerating(on) {
    if (genIndicator) genIndicator.hidden = !on;
  }

  // ── Auto-generate on IDLE ─────────────────────────────────────────────────
  if (page.dataset.autogenerate === "true") {
    setTimeout(() => startGeneration(_nextKey()), 300);
  }

  // ── Generation ────────────────────────────────────────────────────────────
  function _nextKey() {
    return `reader-${storyId}-${Date.now()}`;
  }

  async function startGeneration(key) {
    if (activeRequest) return;
    activeRequest = true;
    _clearError();
    _setGenerating(true);

    let buffer = "";
    let segmentId = null;

    try {
      const resp = await fetch(generateUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          branch_id: page.dataset.branchId,
          generation_key: key,
          context: _buildContext(),
        }),
      });

      if (!resp.ok) {
        _setGenerating(false);
        _showError("生成请求失败，请重试。");
        activeRequest = false;
        return;
      }

      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let partial = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        partial += dec.decode(value, { stream: true });
        const blocks = partial.split("\n\n");
        partial = blocks.pop() || "";
        for (const block of blocks) {
          const dataLine = block.split("\n").find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          let envelope;
          try { envelope = JSON.parse(dataLine.slice(5).trim()); } catch { continue; }
          _handleEvent(envelope, {
            onDelta(text) { buffer += text; if (streamArea) streamArea.textContent = buffer; },
            onCommitted(sid) { segmentId = sid; },
            onContinue() {
              _setGenerating(false);
              _flushBuffer(buffer);
              buffer = "";
              activeRequest = false;
              sceneCount += 1;
              setTimeout(() => startGeneration(_nextKey()), 1000);
            },
            onChoice() { _setGenerating(false); activeRequest = false; location.reload(); },
            onPaused() { _setGenerating(false); activeRequest = false; location.reload(); },
            onError() { _setGenerating(false); _flushBuffer(buffer); buffer = ""; activeRequest = false; _showError("生成出错。"); },
          });
        }
      }
    } catch (err) {
      _setGenerating(false);
      activeRequest = false;
      _showError("网络错误，请检查连接。");
    }
  }

  function _handleEvent(env, handlers) {
    const name = env.event;
    const data = env.data || {};
    if (name === "delta") handlers.onDelta(data.text || "");
    else if (name === "committed") handlers.onCommitted(data.segment_id);
    else if (name === "continue") handlers.onContinue();
    else if (name === "choice") handlers.onChoice();
    else if (name === "paused") handlers.onPaused();
    else if (name === "error") handlers.onError();
  }

  function _flushBuffer(text) {
    if (!text || !streamArea) return;
    const article = document.createElement("article");
    article.className = "segment";
    article.dataset.sequence = String(sceneCount + 1);
    const p = document.createElement("p");
    p.textContent = text;
    article.appendChild(p);
    streamArea.before(article);
    streamArea.textContent = "";
  }

  function _buildContext() {
    return { story_id: storyId, branch_id: page.dataset.branchId };
  }

  // ── Choices ───────────────────────────────────────────────────────────────
  const choicePanel = page.querySelector("[data-view='choice-panel']");
  if (choicePanel) {
    const choiceId = choicePanel.dataset.choiceId;
    const choiceVersion = parseInt(choicePanel.dataset.choiceVersion, 10);
    const customInput = choicePanel.querySelector("input[name='custom_action']");
    let submitting = false;

    choicePanel.addEventListener("click", async (e) => {
      if (submitting) return;
      const btn = e.target.closest("[data-choice-option-id]");
      if (btn) {
        submitting = true;
        btn.disabled = true;
        await _submitChoice(choiceId, choiceVersion, { option_id: btn.dataset.choiceOptionId });
        submitting = false;
        btn.disabled = false;
        return;
      }
      const customBtn = e.target.closest("[data-submit-custom]");
      if (customBtn && customInput) {
        const text = customInput.value.trim();
        if (!text) return;
        submitting = true;
        customBtn.disabled = true;
        await _submitChoice(choiceId, choiceVersion, { custom_action: text });
        submitting = false;
        customBtn.disabled = false;
      }
    });
  }

  async function _submitChoice(choiceId, version, payload) {
    _clearError();
    try {
      const resp = await fetch(`/api/choices/${choiceId}/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice_version: version, ...payload }),
      });
      if (!resp.ok) { _showError("提交选择失败，请重试。"); return; }
      location.reload();
    } catch { _showError("网络错误，请重试。"); }
  }

  // ── Pause / Resume ────────────────────────────────────────────────────────
  const pauseBtn = page.querySelector("[data-pause]");
  const resumeBtn = page.querySelector("[data-resume]");

  if (resumeBtn) {
    resumeBtn.addEventListener("click", () => location.reload());
  }

  if (pauseBtn) {
    pauseBtn.addEventListener("click", async () => {
      pauseBtn.disabled = true;
      try {
        await fetch(`/api/stories/${storyId}/pause`, { method: "POST" });
      } catch {}
      location.reload();
    });
  }

  // ── Retry ─────────────────────────────────────────────────────────────────
  const retryBtn = page.querySelector("[data-retry]");
  if (retryBtn) {
    retryBtn.addEventListener("click", () => {
      activeRequest = false;
      startGeneration(_nextKey());
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function _showError(msg) {
    if (errorBanner) { errorBanner.textContent = msg; errorBanner.hidden = false; }
  }
  function _clearError() {
    if (errorBanner) { errorBanner.hidden = true; errorBanner.textContent = ""; }
  }
})();
