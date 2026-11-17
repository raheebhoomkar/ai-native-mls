# ADR 0004: Gemini as the first vision provider, with a labelled demo mode

- **Date:** 2026-11-17
- **Status:** Accepted.

## Context

Sprint 7 (Module 4) reads listing photos and suggests observable features (room type, flooring, appliances and so on) for an editor to review. The project has no budget, so the provider must have a usable free tier. The demo must also work for anyone who clones the repository without an API key, and reviewers must never mistake made-up output for a model's answer.

## Decision

**One interface.** `VisionProvider.extract(photos) -> ProviderResult` in `app/modules/ai/providers.py`. Callers never see a provider's request format. Errors are typed (`ProviderUnavailable`, `ProviderTimeout`, `RateLimited`, `MalformedOutput`, `ProviderRejected`), and each says whether trying again can help.

**Gemini first.** `GeminiVisionProvider` (`app/modules/ai/gemini.py`) calls the REST API with the standard library, so there is no new dependency. It sends the photos inline and asks for JSON that matches a response schema. Pydantic checks every answer again (`Extraction`) before anything is stored. The model is set by `GEMINI_MODEL`.

**Demo mode.** With no `GEMINI_API_KEY`, `get_provider()` returns `DemoVisionProvider`. Its values start with `[Demo] `, are all marked uncertain, and its runs have `provider = "demo"`, which the API exposes as `is_demo`. There is no separate on/off setting: the key decides.

**Runs, not fields.** Each extraction is an `AgentRun` row: who asked, the provider, model and model version, the photos sent (asset ID and SHA-256), status, attempts, the validated output and any error. The work runs as an `ai.extract` job (ADR 0003). Output stays on the run. Nothing is written to listing fields until an editor accepts a suggestion (Sprint 8).

## What is sent to Google

- At most 10 of the listing's ready photos (the newest ones), and a fixed instruction. Each photo is re-encoded as a JPEG of at most 1600 px from its pixels only (`media.service.without_metadata`). Originals keep their EXIF data, including any GPS position and camera model, so they are never sent as they are.
- Not sent: listing text, addresses, prices, user names or emails, other organisations' photos.
- The fixed instruction holds no user-supplied text. Untrusted content never goes into the system instruction.
- The API key goes in the `x-goog-api-key` header. It is never logged and never stored in a fixture.

## Free-tier data terms

Google's free tier for the Gemini API may use submitted content to improve its products, and people may review it. Check Google's current terms before relying on this summary. For this project that means:

- Send demo photos only (seeded drawings or photos the team owns and is happy to share).
- Never send a real client's listing photos on a free-tier key. Production use needs a paid tier or another provider whose terms exclude training on customer data.
- The key used during development was shared in a chat. Rotate it before any public demo.

## Why

- A free tier that accepts images and returns schema-constrained JSON.
- The interface keeps the rest of the code provider-neutral. Adding another provider is one adapter plus its contract tests.
- Demo mode keeps the app usable without secrets. The labels keep it honest.

## Trade-offs and when to revisit

- Latency is high: the live check took about 50 s for two photos. Runs are background jobs, so requests do not wait.
- Gemini models change names and availability often. While building, `gemini-2.5-flash` was closed to new keys and the configured model answered 404 or 503 at times. Retries through the job backoff cover short outages; `GEMINI_MODEL` covers renames.
- Gemini refused the full Pydantic schema ("too many states"), so the request carries a simpler copy and Pydantic enforces the limits afterwards.
- The job backoff ignores `Retry-After` on 429. Revisit if rate limits become common.
- Revisit the provider before handling real client photos (see the data terms above).
