(function () {
  "use strict";

  const form = document.querySelector("#create-story-form");
  if (!form) return;

  const steps = Array.from(form.querySelectorAll("[data-step]"));
  const indicators = Array.from(document.querySelectorAll("[data-step-indicator]"));
  const error = form.querySelector("[role='alert']");
  const improvableFields = Array.from(form.querySelectorAll("[data-improvable-field]"));
  let currentStep = 0;
  let improvementBusy = false;

  function sessionId() {
    let value = window.localStorage.getItem("storyflow-session-id");
    if (!value) {
      value = window.crypto.randomUUID();
      window.localStorage.setItem("storyflow-session-id", value);
    }
    return value;
  }

  function showStep(index) {
    currentStep = Math.max(0, Math.min(index, steps.length - 1));
    steps.forEach((step, position) => {
      step.hidden = position !== currentStep;
    });
    indicators.forEach((indicator, position) => {
      indicator.classList.toggle("is-active", position === currentStep);
      indicator.classList.toggle("is-complete", position < currentStep);
    });
    steps[currentStep].querySelector("input:not([type='hidden']), textarea, select")?.focus();
  }

  function validateStep() {
    const controls = Array.from(steps[currentStep].querySelectorAll("input, textarea, select"));
    const invalid = controls.find((control) => !control.checkValidity());
    if (invalid) {
      invalid.reportValidity();
      return false;
    }
    const punctuationOnly = controls.find((control) =>
      control.required && typeof control.value === "string" &&
      !/[\u3400-\u9fffA-Za-z0-9]/.test(control.value)
    );
    if (punctuationOnly) {
      punctuationOnly.setCustomValidity("请填写实际内容，不能只输入标点符号。");
      punctuationOnly.reportValidity();
      punctuationOnly.addEventListener("input", () => punctuationOnly.setCustomValidity(""), { once: true });
      return false;
    }
    return true;
  }

  function textLength(data) {
    const names = [
      "genre",
      "structure",
      "world_background",
      "protagonist_desc",
      "important_supporting_characters",
      "style",
      "required_elements",
      "forbidden_elements",
      "ending_tendency",
    ];
    return names.reduce((total, name) => total + String(data.get(name) || "").length, 0);
  }

  function isIncomplete(value) {
    return (String(value).match(/[\u3400-\u9fffA-Za-z0-9]/g) || []).length < 6;
  }

  function fieldControl(container) {
    return container.querySelector("input, textarea");
  }

  function showIncompleteHint(container) {
    const hint = container.querySelector("[data-incomplete-hint]");
    const control = fieldControl(container);
    hint.hidden = !isIncomplete(control.value);
  }

  function setImprovementBusy(busy, activeContainer) {
    improvementBusy = busy;
    improvableFields.forEach((container) => {
      const button = container.querySelector("[data-improve-field]");
      button.disabled = busy;
      button.textContent = busy && container === activeContainer ? "正在完善…" : "AI 完善";
    });
  }

  function improvementContext() {
    return Object.fromEntries(improvableFields.map((container) => [
      container.dataset.improvableField,
      fieldControl(container).value,
    ]));
  }

  function hideImprovement(container) {
    container.querySelector("[data-improvement-preview]").hidden = true;
    container.querySelector("[data-improvement-text]").textContent = "";
  }

  function setImprovementStatus(container, message, isError) {
    const status = container.querySelector("[data-improvement-status]");
    status.textContent = message;
    status.classList.toggle("is-error", Boolean(isError));
  }

  async function requestImprovement(container) {
    if (improvementBusy) return;
    error.hidden = true;
    setImprovementBusy(true, container);
    setImprovementStatus(container, "正在生成建议…", false);
    const field = container.dataset.improvableField;
    try {
      const response = await window.storyflowApi.improveField({
        field,
        value: fieldControl(container).value,
        context: improvementContext(),
      });
      if (response.field !== field || typeof response.suggestion !== "string") {
        throw new Error("invalid improvement response");
      }
      container.querySelector("[data-improvement-text]").textContent = response.suggestion;
      container.querySelector("[data-improvement-preview]").hidden = false;
      setImprovementStatus(container, "建议已生成，请预览后决定是否采用。", false);
    } catch (_requestError) {
      error.textContent = "AI 完善暂时不可用，请稍后重试；你仍可手动填写。";
      error.hidden = false;
      setImprovementStatus(container, "完善失败，请稍后重试。", true);
    } finally {
      setImprovementBusy(false, container);
    }
  }

  improvableFields.forEach((container) => {
    fieldControl(container).addEventListener("blur", () => showIncompleteHint(container));
  });

  form.elements.session_id.value = sessionId();
  form.addEventListener("click", (event) => {
    const improvementContainer = event.target.closest("[data-improvable-field]");
    if (improvementContainer && event.target.closest("[data-improve-field]")) {
      requestImprovement(improvementContainer);
      return;
    }
    if (improvementContainer && event.target.closest("[data-adopt-improvement]")) {
      const control = fieldControl(improvementContainer);
      control.value = improvementContainer.querySelector("[data-improvement-text]").textContent;
      control.dispatchEvent(new Event("input", { bubbles: true }));
      hideImprovement(improvementContainer);
      showIncompleteHint(improvementContainer);
      setImprovementStatus(improvementContainer, "已采用 AI 建议。", false);
      return;
    }
    if (improvementContainer && event.target.closest("[data-regenerate-improvement]")) {
      requestImprovement(improvementContainer);
      return;
    }
    if (improvementContainer && event.target.closest("[data-cancel-improvement]")) {
      hideImprovement(improvementContainer);
      setImprovementStatus(improvementContainer, "", false);
      return;
    }
    if (event.target.closest("[data-next-step]") && validateStep()) {
      showStep(currentStep + 1);
    }
    if (event.target.closest("[data-prev-step]")) {
      showStep(currentStep - 1);
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    if (!validateStep()) return;

    const data = new FormData(form);
    if (textLength(data) > Number(form.dataset.totalMaxlength)) {
      error.textContent = "创作设定合计不能超过 6,000 字。";
      error.hidden = false;
      return;
    }

    const submit = form.querySelector("button[type='submit']");
    submit.disabled = true;
    submit.textContent = "正在生成故事圣经…";
    const optional = (name) => String(data.get(name) || "").trim() || null;
    const payload = {
      session_id: data.get("session_id"),
      title: String(data.get("title") || "").trim() || "Untitled",
      config: {
        genre: data.get("genre"),
        structure: data.get("structure"),
        world_background: data.get("world_background"),
        protagonist_desc: data.get("protagonist_desc"),
        important_supporting_characters: optional("important_supporting_characters"),
        style: data.get("style"),
        choice_frequency: data.get("choice_frequency"),
        required_elements: optional("required_elements"),
        forbidden_elements: optional("forbidden_elements"),
        ending_tendency: optional("ending_tendency"),
      },
    };

    try {
      const story = await window.storyflowApi.createStory(payload);
      await window.storyflowApi.generateBible(story.id);
      window.location.assign(`/stories/${story.id}`);
    } catch (requestError) {
      error.textContent = requestError.message;
      error.hidden = false;
      submit.disabled = false;
      submit.textContent = "生成故事圣经";
    }
  });
})();
