# AI Field Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users request and explicitly adopt a Simplified-Chinese AI suggestion for one story-config field at a time.

**Architecture:** Add a field-policy service and a bounded FastAPI endpoint backed by the existing LLM client. Render reusable controls beside supported fields and manage suggestion preview state in `create.js`; the original value changes only on explicit adoption.

**Tech Stack:** Python 3.9+, FastAPI, Pydantic 2, Jinja2, vanilla JavaScript/CSS, pytest.

## Global Constraints

- Never modify a form field before the user clicks “采用”.
- Only the nine documented config fields are accepted.
- Suggestions use Simplified Chinese and respect the target field's existing maximum length.
- AI failure leaves manual creation fully usable.
- No new dependency or database table.

---

### Task 1: Field policy and bounded API

**Files:**
- Create: `src/storyflow/services/field_improvement.py`
- Create: `src/storyflow/prompts/field_improvement.py`
- Create: `src/storyflow/api/routes/field_improvement.py`
- Modify: `src/storyflow/main.py`
- Test: `tests/unit/test_field_improvement.py`
- Test: `tests/integration/test_field_improvement.py`

**Interfaces:**
- `is_incomplete(value: str) -> bool` returns true when meaningful alphanumeric/CJK content has fewer than 6 characters.
- `ImproveFieldRequest(field: str, value: str, context: dict[str, str])` validates whitelist and length.
- `POST /api/story-config/improve-field` returns `{"field": ..., "suggestion": ...}`.

- [ ] Write unit tests for punctuation-only, five meaningful characters, six meaningful characters, and complete prose.
- [ ] Run `uv run python -m pytest tests/unit/test_field_improvement.py -q` and verify missing-module failure.
- [ ] Implement field metadata, meaningful-character counting, context filtering, and suggestion validation.
- [ ] Run unit tests and verify pass.
- [ ] Write API tests for a valid suggestion, unknown field 422, oversized value 422, missing LLM 503, provider failure 502, and punctuation-only output 502.
- [ ] Run API tests and verify RED.
- [ ] Implement the prompt and router; include only whitelisted context and truncate/reject output at the target field limit.
- [ ] Register the router in `create_app` and run API tests to GREEN.
- [ ] Commit with `git commit -m "feat: add bounded AI field improvement API"`.

### Task 2: Creation-page controls and preview workflow

**Files:**
- Modify: `src/storyflow/templates/create.html`
- Modify: `src/storyflow/static/js/create.js`
- Modify: `src/storyflow/static/css/app.css`
- Test: `tests/integration/test_web_pages.py`

**Interfaces:**
- Supported labels contain `data-improvable-field="<field>"`.
- Trigger uses `data-improve-field`; preview uses `data-improvement-preview`.
- Actions use `data-adopt-improvement`, `data-regenerate-improvement`, and `data-cancel-improvement`.

- [ ] Add failing page assertions that all nine supported fields expose controls while title and choice frequency do not.
- [ ] Run the focused page test and verify RED.
- [ ] Render one reusable control structure beside every supported field.
- [ ] Implement incomplete hints on blur and manual improve requests.
- [ ] Implement preview, adopt, regenerate, cancel, busy state, and Chinese error handling; preserve original values until adoption.
- [ ] Add responsive styles using existing tokens and run `node --check src/storyflow/static/js/create.js`.
- [ ] Run page and story-creation tests to GREEN.
- [ ] Commit with `git commit -m "feat: add AI improvement preview to story wizard"`.

### Task 3: Full verification and deployment readiness

**Files:**
- Modify: `README.md`
- Test: complete repository.

- [ ] Document single-field AI completion and explicit adoption in README.
- [ ] Run `uv run python -m pytest -q`.
- [ ] Run `uv run python -m mypy src`.
- [ ] Run JavaScript syntax checks for `create.js` and `reader.js`.
- [ ] Run `uv run python scripts/secret_scan.py src` and `git diff --check`.
- [ ] Commit final documentation and regression adjustments.
