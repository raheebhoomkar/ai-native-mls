# Sprint 9: Photo redaction (Module 5)

**Status: done (2026-11-17).** All four chunks are finished. Staged, not committed.

Branch: `feature/s6-media-jobs` (the developer may cut `feature/s9-redaction` from it). Claude does not commit or push; the developer does.

Scope (from the approved plan and INSTRUCTIONS.md Module 5): detector interface; OpenCV face detection; Gemini-located licence plates, phone numbers, watermarks and promotional signage; a blurred derivative stored apart from the original; reviewer approve or reject; what was detected, redacted and by which method and version is recorded; limitations shown, never a claim of perfect detection.

## Design decisions (reversible; made 2026-11-17)

- **Policy** (`app/modules/ai/redaction.py`, `POLICY_VERSION = "1"`): redact `face`, `licence_plate`, `phone_number`, `watermark` and `signage` (promotional or contact signs). Every detection in these categories is blurred. One fixed policy in code for now; per-organisation policies are out of scope.
- **Detectors** (`app/modules/ai/detectors.py`):
  - Faces: OpenCV Haar cascades (frontal and profile, both directions), run locally; no photo leaves the system for this step. Haar gives no calibrated score, so face regions have `confidence = null` ("no score").
  - Plates, phone numbers, watermarks, signage: Gemini (`GeminiRegionLocator`, same key, model, timeout and error types as the extraction adapter), sent the metadata-free copy from `media.without_metadata`. Gemini is told not to copy the text it sees, so phone numbers are not stored.
  - No Gemini key: the demo locator finds nothing and the run records those four categories as **not checked** (and `is_demo`), rather than pretending.
  - `opencv-python-headless` is pinned below 5: OpenCV 5 removed the Haar cascades.
- **Run record**: an `AgentRun` with `agent = "redaction"`, one per photo. `output` holds the policy version, the image size, every region (category, box as fractions of the image, confidence, detector, uncertain flag, a short note), which detectors ran (name and version) and which categories were not checked and why, plus the derivative's ID.
- **Partial failure**: if the Gemini step still fails after the job's retries (or is refused), the run still succeeds with faces only, and the four categories are listed as not checked with the reason. The reviewer sees that warning.
- **Derivative**: a new media `kind = "redacted"` row pointing at the original (migration widens `ck_media_assets_kind`). JPEG from pixels only (no EXIF or GPS), longest side at most 2048 px. Blur is pixelation then Gaussian blur over each region plus a margin. The original is never changed; removing the original removes its derivatives (existing media cascade).
- **Review**: every succeeded run opens a `ReviewTask` (`subject_type = "redaction"`, one item, `item_key = None`), including runs that found nothing, because finding nothing is not proof there is nothing. Decision `accepted` (shown as "Approved") or `rejected`, optional note. Editors of the listing decide (same rule as Sprint 8), audited as `ai.redaction_decided`. An approved derivative is the version later sprints must use when a photo leaves the organisation (public pages, syndication).
- **Low confidence**: regions under 0.6 are marked uncertain; they are still blurred. The UI highlights uncertain regions and anything not checked.

## How to resume

1. `git status` and `git log --oneline | head -3`.
2. `docker compose up -d --wait` (Postgres). Seed if empty: `cd services/api && .venv/bin/python -m app.seed`.
3. `cd services/api && .venv/bin/pip install -e '.[dev]'` (new dependency: `opencv-python-headless`).
4. Do the first unchecked chunk below. Run the checks, tick the chunk, add a line under "Log", stage.

## Chunks

- [x] **1. Detection and derivative (backend).** `detectors.py` (interfaces, OpenCV faces, Gemini locator, demo locator), `redaction.py` (policy, blur, `request_redaction`, `ai.redact` job, `decide`), schemas, `media.service.add_derivative` (thumbnail code reuses it), migration for the `redacted` kind. Tests: synthetic face is found and blurred, original unchanged, derivative has no metadata, Gemini failure leaves categories unchecked, demo marks unchecked, review task opened, decision rules (editor only, once, other organisation 404).
- [x] **2. API.** `POST /api/v1/media/{asset_id}/redactions` (202, editors, audited `ai.redaction_requested`), `GET /api/v1/listings/{id}/redactions`, `POST /api/v1/ai/redactions/{run_id}/decision` (201, editors, audited `ai.redaction_decided`). Router tests. `pnpm gen:api`.
- [x] **3. Web.** "Privacy redaction" panel under the photos: per photo, "Check for sensitive content", progress, errors with retry; preview of the original with outlined regions beside the redacted copy; region list with category, detector, confidence, "Uncertain" and "Not checked" warnings; limitations text; Approve and Reject with an optional note; the decision once made. Read-only users see everything without buttons. Vitest tests.
- [x] **4. Browser check and docs.** Chrome: run on a seeded photo (demo) and, if possible, with Gemini; approve one, reject one; narrow layout. Docs: RBAC matrix, README, ADR if needed, closing sections of this note.

## Conventions to follow (already in the codebase)

- Another AI task: a new `agent` on `AgentRun`, a Pydantic output schema, a job handler (see `docs/modules/s7-ai-extraction.md`, "Shared pieces").
- Approvals: `review.service` (see `docs/modules/s8-ai-review.md`, "Shared pieces"); the AI module checks permissions and applies the effect.
- Derivatives: new `kind`, never overwrite an original (`docs/modules/s6-media-jobs.md`).
- Photos sent outside: `media.without_metadata` only.

## Checks

```bash
# from services/api (needs Postgres)
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest -q
# from apps/web (only if the API schema or web code changed)
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

## Log

(one line per finished chunk: date, what was done, anything left open)

- 2026-11-17, chunk 1 done. `detectors.py` (OpenCV Haar faces), `GeminiRegionLocator` in `gemini.py` (the request code is now shared through `GeminiClient`), `DemoRegionLocator`, `redaction.py` (policy, `blur`, `request_redaction`, `list_redactions`, `decide`, job `ai.redact`), schemas, `media.service.add_derivative` (the thumbnail job uses it too), `media.service.get_manageable` made public, migration `74839bf69e55_media_redacted_kind`. Extraction runs are now filtered by agent, so redaction runs never reach the suggestion panel or its decision endpoint. Blur strength was raised after a test showed OpenCV still found the face in a lightly pixelated copy. `tests/test_redaction.py`.
- 2026-11-17, chunk 2 done. `app/modules/ai/redaction_router.py`: the three endpoints, registered in `app/main.py`. 20 redaction tests; 163 backend tests pass. `pnpm gen:api` run.
- 2026-11-17, chunk 3 done. `apps/web/src/ListingRedaction.tsx` under the photo gallery; the gallery hands its photo list to it (`ListingMedia` `onLoaded`), so new photos appear without a reload. `ListingRedaction.test.tsx` (7 tests; 49 web tests pass).
- 2026-11-17, chunk 4 done. Chrome check (below). Gemini answered 503 ("high demand") and then 429 (free-tier quota used up), so the live locator was never seen succeeding; both times the run finished with faces blurred and the four categories marked not checked, as designed. Added an opt-in live test (`pytest -m live`, `test_gemini_locates_a_sign_with_a_phone_number`), not yet run because of the quota. Docker image builds and loads OpenCV. Docs: ADR 0005, RBAC matrix, README.

## What was built

- **Detection**: OpenCV Haar face detection, run locally (`app/modules/ai/detectors.py`). Gemini finds licence plates, phone numbers, watermarks and signs (`GeminiRegionLocator`); without a key the demo locator checks nothing and says so.
- **Redaction run** (`app/modules/ai/redaction.py`): one `AgentRun` (`agent = "redaction"`) per photo, job `ai.redact`. Output records the policy version, image size, every region with its detector and confidence, which detectors ran (name and version) and what was not checked and why.
- **Blurred copy**: media row `kind = "redacted"`, a metadata-free JPEG beside the original. The original never changes.
- **Review**: every finished check needs a person's approval or rejection (`ReviewTask` `subject_type = "redaction"`), audited.
- **API**: `POST /api/v1/media/{asset_id}/redactions`, `GET /api/v1/listings/{id}/redactions`, `POST /api/v1/ai/redactions/{run_id}/decision`.
- **Web**: "Privacy redaction" panel under the photos: per photo check, progress, errors and retry, the original with outlined areas beside the copy, the list of areas, "Uncertain" and "Not checked" warnings, Approve and Reject with a note.

## Shared pieces later sprints must reuse

| Need | Use |
|---|---|
| A photo leaves the organisation (public pages, syndication, Sprint 17+) | The newest redaction run of that photo whose `review_status` is `approved`: its `output.derivative_id` (or `redacted_url`). Without one, do not publish the photo, or ask for a check first. |
| Another detector (better faces, a different text model) | Implement `FaceDetector` (`detectors.py`) or `RegionLocator` (`providers.py`) and return it from `redaction.get_face_detector()` / `get_locator()`. Bump `POLICY_VERSION` if what is blurred changes. |
| Store another derivative | `media.service.add_derivative(session, original, data, kind=...)` plus a migration widening `ck_media_assets_kind`. |
| A second Gemini task with structured output | Subclass `GeminiClient` and call `_generate(system, parts, schema)`, then `_parse(body, Model)`. |
| Tests that touch redaction | Monkeypatch `app.modules.ai.redaction.get_locator` with a fake (see `FakeLocator` in `tests/test_redaction.py`). `scene()` there draws a face OpenCV finds reliably. |

## Acceptance results

- Process a test image and produce a reviewable copy: yes. In Chrome, on "[Demo] 3 BHK apartment near the lake", a drawn room with a face and a "FOR SALE / Call …" sign: the face was outlined on the original and blurred on the copy, and the copy waited for review. Also covered by tests, including that OpenCV no longer finds the face in the copy.
- Original protected and not changed: test compares the original's bytes after the run; the copy is a separate media row and file; access to both follows the listing's read rules.
- Not destructive: yes; rejecting keeps the copy for the record, and a new check can be run.
- Reviewer approves or rejects: yes, both clicked in Chrome (approve on `demo-photo-1.jpg`, reject with a note on the drawn room); decisions are final (409 on a second one) and audited.
- Failed or low-confidence detections routed for review: every finished check goes to review, including "nothing found"; regions under 0.6 are marked uncertain (dashed outline); categories not checked are listed with the reason. Seen live when Gemini returned 503 and 429.
- Permissions: readers and agents who do not own the listing get 403; another organisation 404 (tests).
- Narrow layout: at 390 px (in a frame, as Chrome will not shrink that far) the original and the copy stack, the outlines line up, and nothing scrolls sideways.
- Checks: ruff, mypy, pytest (163 passed); web lint, typecheck, test (49 passed), build; Docker build.

## Known limitations

- The Gemini locator has passed contract tests with recorded-format answers but was not seen working live in this sprint (503, then the free-tier quota). Run `pytest -m live` when the quota resets.
- Haar face detection misses small, tilted, partly hidden or turned-away faces and sometimes marks patterns as faces. It gives no score.
- A reviewer cannot adjust single boxes; they reject and run the check again.
- While a check runs, the panel says "Waiting to check…" until the job ends, because the run's status is saved with the job's single transaction (same as extraction).
- The copy is at most 2048 px on its longest side and re-encoded as JPEG.
- One fixed policy for every organisation (`POLICY_VERSION = "1"`).
- Nothing uses approved copies yet; there is no public page or syndication. Later sprints must (see "Shared pieces").

## Next

Phase B continues with any of Sprint 10 (standardisation and import), 11 (compliance flags), 12 (geospatial) or 13 (semantic search); Sprint 14 needs 13. The plan's shortest path to a full demo goes to Sprint 11 then 13.
