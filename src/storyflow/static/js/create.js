(function () {
  "use strict";

  const form = document.querySelector("#create-story-form");
  if (!form) return;

  const steps = Array.from(form.querySelectorAll("[data-step]"));
  const indicators = Array.from(document.querySelectorAll("[data-step-indicator]"));
  const error = form.querySelector("[role='alert']");
  let currentStep = 0;

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

  form.elements.session_id.value = sessionId();
  form.addEventListener("click", (event) => {
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
