# Reader History, Summary, and Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make lossless history branching, visible plot summaries, and current-view Markdown export fully usable from the StoryFlow reader.

**Architecture:** Add small presentation helpers for reader history and summary data, strengthen the existing repository fork transaction, and run best-effort rolling-summary maintenance after a scene commit. Extend export with an explicit branch ID while preserving the existing default behavior, then wire all three capabilities into the server-rendered reader and its existing JavaScript controller.

**Tech Stack:** Python 3.9+, FastAPI, Pydantic 2, SQLite, Jinja2, vanilla JavaScript/CSS, pytest.

## Global Constraints

- A history rollback always preserves the original route and creates a new branch.
- Rolling summaries run after scene commit at scene 5, 10, 15, and later positive multiples of 5.
- Summary failure must never roll back committed prose or block later generation.
- Export must target the branch currently shown in the reader and must not include sibling-branch prose or hidden choice effects.
- No new database tables, account system, frontend framework, or third-party dependency.
- All user-facing errors and controls added by this work use Chinese text.

---

### Task 1: Reader presentation data for history and summaries

**Files:**
- Create: `src/storyflow/services/reader_view.py`
- Modify: `src/storyflow/api/routes/web.py`
- Test: `tests/unit/test_reader_view.py`

**Interfaces:**
- Produces: `HistoryChoice` dataclass with `choice_id: UUID`, `segment_id: UUID`, and `selected_text: str`.
- Produces: `build_history_choices(repository: StoryRepository, segments: Sequence[StorySegment]) -> dict[UUID, HistoryChoice]`.
- Produces: `build_visible_summary(snapshot: MemorySnapshot | None, segments: Sequence[StorySegment]) -> tuple[str, Literal["rolling", "stage", "empty"]]`.
- Reader template context gains `history_choices`, `visible_summary`, and `summary_source`.

- [ ] **Step 1: Write failing unit tests for visible history and summary fallback**

Add tests proving that selected preset and custom actions become user-visible history entries, hidden effects are absent, a non-empty rolling summary wins, ordered scene summaries form the stage fallback, and an empty path returns the empty state.

```python
def test_visible_summary_prefers_persisted_rolling_summary():
    snapshot = MemorySnapshot(story_id=uuid4(), branch_id=uuid4(), rolling_summary="五幕以来，李云已进入主控舱。")
    text, source = build_visible_summary(snapshot, [_segment(1, "旧短摘要")])
    assert (text, source) == ("五幕以来，李云已进入主控舱。", "rolling")

def test_visible_summary_uses_ordered_scene_summaries_before_first_rollup():
    text, source = build_visible_summary(None, [_segment(2, "发现密门"), _segment(1, "进入基地")])
    assert text == "进入基地\n\n发现密门"
    assert source == "stage"
```

- [ ] **Step 2: Run the unit tests and verify RED**

Run: `uv run pytest tests/unit/test_reader_view.py -q`

Expected: collection fails because `storyflow.services.reader_view` does not exist.

- [ ] **Step 3: Implement the presentation helpers**

Create a focused service that resolves selected option/custom-action text without returning effects and builds the summary tuple. Ignore blank scene summaries and sort by `sequence`.

- [ ] **Step 4: Run the unit tests and verify GREEN**

Run: `uv run pytest tests/unit/test_reader_view.py -q`

Expected: all new unit tests pass.

- [ ] **Step 5: Write a failing web-route context test**

Add a focused test that renders `reader_page` with a selected historical choice and a saved rolling summary, using a temporary Jinja template that prints `history_choices`, `visible_summary`, and `summary_source` from its context.

Run: `uv run pytest tests/unit/test_reader_view.py -q`

Expected: the response lacks those values because `web.py` does not yet pass the additional context.

- [ ] **Step 6: Supply reader context from the web route**

In `reader_page`, load the current branch snapshot, call both helpers, and pass their outputs for success, 404, and 503 template paths with empty defaults.

- [ ] **Step 7: Run focused tests**

Run: `uv run pytest tests/unit/test_reader_view.py -q`

Expected: helper and route-context tests pass.

- [ ] **Step 8: Commit the presentation service**

```bash
git add src/storyflow/services/reader_view.py src/storyflow/api/routes/web.py tests/unit/test_reader_view.py
git commit -m "feat: prepare reader history and summary data"
```

---

### Task 2: Lossless branch creation that resumes at the historical choice

**Files:**
- Modify: `src/storyflow/db/repositories.py`
- Modify: `src/storyflow/api/routes/choices.py`
- Test: `tests/e2e/test_reader_choices.py`
- Test: `tests/integration/test_branching.py`

**Interfaces:**
- `StoryRepository.fork_at_choice(choice_id: UUID, branch_name: str = "新路线") -> tuple[Branch, MemorySnapshot, ChoicePoint]` returns the new branch, copied pre-choice snapshot, and new pending choice.
- `CreateBranchResponse` adds `choice_id: UUID` and keeps existing response fields.
- On success, the story has `current_branch_id == new_branch.id` and `status == StoryStatus.WAITING_CHOICE`.

- [ ] **Step 1: Write a failing repository integration test**

Create a selected choice with later prose, fork it, and assert:

```python
new_branch, snapshot, pending_choice = repo.fork_at_choice(choice.id, "另一种选择")
original_path = repo.list_branch_path(original_branch.id)
fork_path = repo.list_branch_path(new_branch.id)
updated_story = repo.get_story(story.id)
assert [item.id for item in original_path] == original_ids
assert [item.id for item in fork_path] == [choice_segment.id]
assert pending_choice.status == "pending"
assert pending_choice.selected_option_id is None
assert updated_story.current_branch_id == new_branch.id
assert updated_story.status is StoryStatus.WAITING_CHOICE
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/integration/test_branching.py -q`

Expected: tuple unpacking or state assertions fail because the current fork does not produce a pending branch-local choice and does not switch story state.

- [ ] **Step 3: Implement one atomic fork transaction**

Inside the existing transaction:

- Retain the original branch and choice unchanged.
- Create a branch headed at the historical segment.
- Copy the pre-choice snapshot with new IDs and the new branch ID.
- Clone the historical choice and its options with new IDs, `status="pending"`, no selected action/effects, and version `1`.
- Persist the cloned choice/options on the shared historical segment and set `Branch.fork_choice_id` to the first cloned option ID. This existing field and schema trigger provide an unambiguous link from the fork branch to its pending choice without a schema change.
- Update both the stories table `current_branch_id` column and serialized story payload to `WAITING_CHOICE` in the same transaction.

Add `StoryRepository.get_current_choice_for_branch(branch_id: UUID) -> ChoicePoint | None`: when the branch has `fork_choice_id` and its head equals `fork_segment_id`, resolve the choice through `choice_options.choice_point_id`; otherwise use the existing head-segment lookup for a normal generated choice. Change `web.reader_page` to call this method for `WAITING_CHOICE`.

- [ ] **Step 4: Run repository tests and verify GREEN**

Run: `uv run pytest tests/integration/test_branching.py tests/integration/test_repositories.py -q`

Expected: all pass and the original route remains unchanged.

- [ ] **Step 5: Write a failing API response test**

Update the branch API test to assert `choice_id`, the new current branch, `WAITING_CHOICE`, and that loading `reader?branch=<new id>` can resolve the pending choice.

Run: `uv run pytest tests/e2e/test_reader_choices.py::test_branch_fork_api_returns_new_branch_id -q`

Expected: response lacks `choice_id` or the pending state.

- [ ] **Step 6: Extend the branch API response**

Return the cloned pending choice ID and map repository conflicts to the existing stable JSON error envelope. Preserve `branch_id`, `story_id`, `fork_segment_id`, and `memory_snapshot_id` for compatibility.

- [ ] **Step 7: Run focused branch tests**

Run: `uv run pytest tests/integration/test_branching.py tests/e2e/test_reader_choices.py -q`

Expected: all pass.

- [ ] **Step 8: Commit lossless rollback behavior**

```bash
git add src/storyflow/db/repositories.py src/storyflow/api/routes/choices.py tests/integration/test_branching.py tests/e2e/test_reader_choices.py
git commit -m "feat: resume historical choices on new branches"
```

---

### Task 3: Automatic best-effort rolling summaries

**Files:**
- Modify: `src/storyflow/services/generation.py`
- Modify: `src/storyflow/api/routes/generation.py`
- Test: `tests/integration/test_generation_service.py`
- Test: `tests/integration/test_streaming_api.py`

**Interfaces:**
- `GenerationService` gains a private async `_update_rolling_summary(segment: StorySegment) -> None` orchestration method.
- The method uses `MemoryService.should_trigger_rolling_summary`, `MemoryService.update_rolling_summary`, `StoryRepository.get_latest_memory_snapshot`, `StoryRepository.list_branch_path`, and `StoryRepository.save_memory_snapshot`.
- `GenerationResult` and SSE event shapes remain unchanged.

- [ ] **Step 1: Write a failing fifth-scene summary test**

Use a recording fake LLM that returns normal Director/Writer results and `{"rolling_summary": "前五幕压缩摘要"}` for the summary prompt. Generate scene 5 and assert the latest snapshot contains that text and has `segment_id == committed_segment.id`.

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/integration/test_generation_service.py -q`

Expected: no new summary snapshot exists because generation never invokes `MemoryService.update_rolling_summary`.

- [ ] **Step 3: Implement post-commit summary orchestration**

After `commit_generation_bundle` returns, check the committed sequence. For multiples of five, load or initialize the branch snapshot, convert the latest five path segments to `SceneMemory`, call the existing update method, copy the returned snapshot with a new UUID and current segment ID, and save only when its summary changed. Catch and log all summary-specific failures without changing the committed result.

- [ ] **Step 4: Run the fifth-scene test and verify GREEN**

Run: `uv run pytest tests/integration/test_generation_service.py -q`

Expected: summary test and existing generation tests pass.

- [ ] **Step 5: Add failure-degradation and non-trigger tests**

Add tests proving scene 4 does not make a summary request and a summary LLM exception still returns a committed scene with the correct story status.

- [ ] **Step 6: Run generation and streaming suites**

Run: `uv run pytest tests/integration/test_generation_service.py tests/integration/test_streaming_api.py tests/unit/test_memory.py -q`

Expected: all pass; SSE output is unchanged.

- [ ] **Step 7: Commit automatic summaries**

```bash
git add src/storyflow/services/generation.py src/storyflow/api/routes/generation.py tests/integration/test_generation_service.py tests/integration/test_streaming_api.py
git commit -m "feat: maintain rolling summaries after scene commits"
```

---

### Task 4: Explicit branch export

**Files:**
- Modify: `src/storyflow/services/export.py`
- Modify: `src/storyflow/api/routes/export.py`
- Test: `tests/integration/test_export.py`

**Interfaces:**
- `export_branch_markdown(repository: StoryRepository, story: Story, branch_id: UUID | None = None) -> str`.
- `GET /api/stories/{story_id}/export.md?branch=<uuid>` exports that branch; omitted `branch` retains current behavior.

- [ ] **Step 1: Write failing explicit-branch tests**

Assert that exporting a non-current sibling by query parameter contains its prose and excludes current-branch-only prose, and that a branch belonging to another story returns 404.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/integration/test_export.py -q`

Expected: explicit branch query is ignored and cross-story branch is not rejected.

- [ ] **Step 3: Implement explicit target validation and export**

Resolve `target_branch_id = branch or story.current_branch_id`, validate `repository.get_branch(target_branch_id).story_id == story.id`, return 404 on failure, and pass the validated ID to the export service. Keep existing filename and media type.

- [ ] **Step 4: Run export tests and verify GREEN**

Run: `uv run pytest tests/integration/test_export.py -q`

Expected: all explicit and compatibility cases pass.

- [ ] **Step 5: Commit branch-aware export**

```bash
git add src/storyflow/services/export.py src/storyflow/api/routes/export.py tests/integration/test_export.py
git commit -m "feat: export the selected story branch"
```

---

### Task 5: Reader UI and interactions

**Files:**
- Modify: `src/storyflow/templates/reader.html`
- Modify: `src/storyflow/static/js/reader.js`
- Modify: `src/storyflow/static/css/app.css`
- Test: `tests/e2e/test_reader_choices.py`
- Test: `tests/e2e/test_reader_stream.py`

**Interfaces:**
- Summary toggle uses `data-summary-toggle` and panel `data-view="story-summary"`.
- Export anchor uses `/api/stories/{story_id}/export.md?branch={branch_id}`.
- Historical branch buttons use `data-create-branch` and `data-choice-id`.

- [ ] **Step 1: Complete failing page assertions**

Assert reader HTML contains “剧情摘要”, “导出 Markdown”, the exact current branch query, selected action text, and one “从这里重新选择” button beside the matching historical segment. Assert hidden effects never appear.

- [ ] **Step 2: Run page tests and verify RED**

Run: `uv run pytest tests/e2e/test_reader_choices.py tests/e2e/test_reader_stream.py -q`

Expected: new UI text and data hooks are absent.

- [ ] **Step 3: Render the toolbar, summary, and history actions**

Add accessible button/anchor markup in the header, a collapsible summary section with source-specific helper copy, and a historical choice block inside each matching segment article. Use the `history_choices` dictionary keyed by segment ID.

- [ ] **Step 4: Implement browser interactions**

In `reader.js`:

- Toggle the summary panel and `aria-expanded` without a request.
- On a history action, request a branch name with a Chinese default, POST JSON to `/api/choices/{id}/branch`, disable the initiating button while pending, parse the JSON error envelope, and navigate to `/stories/{storyId}/reader?branch={response.branch_id}` on success.
- Keep existing generation, choice, pause, and retry behavior unchanged.

- [ ] **Step 5: Add focused responsive styling**

Style `.reader-tools`, `.story-summary`, and `.history-choice` using existing color tokens. Ensure controls wrap below 720px, history text wraps, and focus-visible behavior inherits the existing rules.

- [ ] **Step 6: Run page tests and verify GREEN**

Run: `uv run pytest tests/e2e/test_reader_choices.py tests/e2e/test_reader_stream.py tests/integration/test_web_pages.py -q`

Expected: all pass.

- [ ] **Step 7: Commit reader UI**

```bash
git add src/storyflow/templates/reader.html src/storyflow/static/js/reader.js src/storyflow/static/css/app.css tests/e2e/test_reader_choices.py tests/e2e/test_reader_stream.py
git commit -m "feat: expose history summary and export in reader"
```

---

### Task 6: Full verification and documentation alignment

**Files:**
- Modify: `README.md`
- Test: all existing test files.

**Interfaces:**
- No new runtime interface; this task validates the complete feature contract.

- [ ] **Step 1: Add a full-journey regression**

Extend `tests/e2e/test_full_journey.py` to assert the reader exposes all three controls, the branch API switches to a pending historical choice without changing original path IDs, and explicit branch export returns the viewed path.

- [ ] **Step 2: Run the full journey**

Run: `uv run pytest tests/e2e/test_full_journey.py -q`

Expected: pass.

- [ ] **Step 3: Align README wording with actual behavior**

State that rollback is accessed from completed historical choices, summaries update every five committed scenes and are visible in the reader, and export downloads the currently viewed branch.

- [ ] **Step 4: Run complete verification**

Run:

```bash
make test
make lint
make typecheck
python scripts/secret_scan.py .
```

Expected: every command exits 0 with no newly introduced warnings or leaked credentials.

- [ ] **Step 5: Inspect the final diff**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended files are modified.

- [ ] **Step 6: Commit final regression and documentation updates**

```bash
git add README.md tests/e2e/test_full_journey.py
git commit -m "test: cover reader history summary and export journey"
```
