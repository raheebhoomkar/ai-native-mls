# ADR 0005: Photo redaction with local face detection and a vision model for text

- **Date:** 2026-11-17
- **Status:** Accepted.

## Context

Sprint 9 (Module 5) must find faces, licence plates, phone numbers, watermarks and promotional signs in listing photos and make a blurred copy that a person approves. Detection will never be perfect. The original must stay unchanged and protected.

## Decision

**Faces: OpenCV, locally.** `OpenCvFaceDetector` (`app/modules/ai/detectors.py`) runs the Haar cascades bundled with `opencv-python-headless` (frontal faces, and profiles facing either way). No photo leaves the system for this step. The dependency is pinned below 5 because OpenCV 5 removed the Haar cascades. Haar cascades give no calibrated score, so face regions carry no confidence and the UI says "no score".

**Plates, phone numbers, watermarks, signs: a vision model.** `GeminiRegionLocator` (`app/modules/ai/gemini.py`) behind the `RegionLocator` interface. It shares the request code and error types with the extraction adapter (ADR 0004). It returns boxes in Gemini's `box_2d` convention, which Pydantic checks before they are used. Gemini is told not to copy the text it sees, so phone numbers are not stored in our database.

**Demo mode.** Without a key, `DemoRegionLocator` finds nothing, and the run lists those four categories as *not checked* instead of pretending to have looked.

**Partial failure.** If the locator still fails after the job's retries, or refuses the request, the run finishes with faces only and records the missing categories and the reason. Faces are still blurred, and the reviewer sees the warning.

**Every result is reviewed.** Each finished check opens a `ReviewTask` (`subject_type = "redaction"`), including one that found nothing. Approve or reject is one final, audited decision.

**Blurring.** Each region plus a 15 % margin is pixelated (about six blocks across its short side), then Gaussian-blurred. The copy is a new media row (`kind = "redacted"`), a JPEG built from pixels only, at most 2048 px on its longest side. The original is never changed. Removing the original removes its copies.

## What is sent to Google

The same as ADR 0004: one photo at a time, re-encoded from its pixels only (no EXIF or GPS), with a fixed instruction. The free-tier terms in ADR 0004 apply: demo photos only.

## Consequences

- One new dependency (`opencv-python-headless`, about 35 MB of wheels). It needs no system libraries in `python:3.15-slim`.
- Haar cascades miss small, tilted, partly hidden or turned-away faces and sometimes mark patterns as faces. A better detector (for example OpenCV's YuNet, which needs a model file) can replace `OpenCvFaceDetector` without other changes.
- The reviewer cannot move, add or remove a single box; they reject the copy and run the check again.
