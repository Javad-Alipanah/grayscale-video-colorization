# Publish a reviewed reference set

The simplest path accepts native RGB PNGs you have already reviewed. Keep source
captures, generated/artistic guides, review notes and revisions in private storage.
No paid image service or particular editor is required by the protocol.

1. Extract the selected source frame at its exact decoded global frame number.
   In FFmpeg use `select=eq(n\,FRAME)` rather than approximate time seeking.
2. Create color guidance and inspect geometry, palette and the source-luminance
   recombination described in [references and QA](references-and-quality.md).
3. Save the final native-sized RGB PNG as `ref_000012.png`, where 12 is the frame
   index **relative to this shot**, not relative to the batch or full video.
4. Write the JSON below beside the guides, replacing values with actual identities
   and observations. Start pending. Change the status/check flags only after the
   stated visual checks have really been performed. Use the source SHA from the
   initialized project's manifest and PNG SHA256 from a checksum tool.

```json
{
  "status": "pending",
  "shot_id": "shot_000240",
  "source_sha256": "REPLACE_WITH_ACTUAL_SOURCE_SHA256",
  "approved_by": "REPLACE_WITH_REVIEWER",
  "approved_at": "REPLACE_WITH_REVIEW_TIME",
  "notes": "REPLACE_WITH_OBSERVATIONS_AND_LIMITATIONS",
  "geometry_checked": false,
  "palette_checked": false,
  "source_y_recombined_checked": false,
  "references": [{
    "path": "ref_000012.png",
    "sha256": "REPLACE_WITH_ACTUAL_PNG_SHA256",
    "source_frame": 252,
    "view": "REPLACE_WITH_COMPATIBLE_CAMERA_VIEW",
    "materials": ["REPLACE_WITH_REVIEWED_MATERIAL_PALETTE"]
  }]
}
```

```powershell
python scripts/publish_reference_set.py --project work/projects/film --review-file D:/PrivateGuides/review.json
```

Only `approved` with all three checks true can publish readiness. The script
checks the source identity, shot scope, source-frame/name correspondence, native
dimensions, PNG content hashes and required review attribution. It copies into a
new versioned set and atomically publishes its readiness receipt under the shared
GPU lock. It does **not** inspect the image for you.

For a guide revision, use a new private PNG/review version, leave old files intact,
and publish the new set. The new content hashes invalidate affected inference
fingerprints; unrelated completed shots can resume. Explicitly revise a rejected
batch through the CLI before rerendering. Never edit the frozen shot census to
make a reference change.

## Advanced source-RGB recombination recipe

`engine/prepare_references.py` also retains the original batch guide-preparation
method. It consumes `reference_candidates` in the initial census and approved
`reference-jobs/*.json`, creates recombined RGB guides, and requires a separate
hash-bound review file before marking them ready. The RGB guide's luminance is
an image-space approximation; the final lossless master independently copies
the exact native source Y plane.

## After rendering

The engine stores `render/SHOT/attempt_NNN/attempt.json`. Review the actual
source-Y recombined samples/motion, then submit an attributed `accepted` or
`rejected` record with `shot_id`, `attempt`, `output_sha256`, `reviewed_by`,
`reviewed_at` and `notes`:

```powershell
$env:COLOR_PROJECT = (Resolve-Path 'work/projects/film').Path
python engine/production.py review --attempt-file work/projects/film/render/shot_000240/attempt_001/attempt.json --review-file D:/PrivateGuides/shot-review.json
```

The batch delivery and subsequent batch review are distinct. The lossless batch
master needs assembled-join review and technical preservation checks; accepting
an individual prediction does not complete those checks. Refer to `pipeline.py
review --help` for the batch receipt command.
