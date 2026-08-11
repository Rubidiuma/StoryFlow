(function () {
  "use strict";

  async function requestJson(path, options) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options && options.headers) },
      ...options,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const message = body && body.detail && (body.detail.message || body.detail.code);
      throw new Error(message || "请求未能完成，请稍后重试。");
    }
    return body;
  }

  window.storyflowApi = {
    createStory(payload) {
      return requestJson("/stories", { method: "POST", body: JSON.stringify(payload) });
    },
    generateBible(storyId) {
      return requestJson(`/stories/${storyId}/bible/generate`, { method: "POST" });
    },
    confirmBible(storyId) {
      return requestJson(`/stories/${storyId}/bible/confirm`, { method: "POST" });
    },
  };

  async function runStoryAction(button, action) {
    const page = button.closest("[data-story-id]");
    const error = page.querySelector("[role='alert']");
    button.disabled = true;
    error.hidden = true;
    try {
      await action(page.dataset.storyId);
      window.location.reload();
    } catch (requestError) {
      error.textContent = requestError.message;
      error.hidden = false;
      button.disabled = false;
    }
  }

  document.addEventListener("click", (event) => {
    const confirmButton = event.target.closest("[data-confirm-bible]");
    const generateButton = event.target.closest("[data-generate-bible]");
    if (confirmButton) {
      runStoryAction(confirmButton, window.storyflowApi.confirmBible);
    } else if (generateButton) {
      runStoryAction(generateButton, window.storyflowApi.generateBible);
    }
  });
})();
