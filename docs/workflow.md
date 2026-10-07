# One batch at a time

The working unit is a complete, reviewed camera shot. A daily batch groups shots
near ten minutes of source time. It can be longer or shorter: do not create a
new propagation boundary halfway through a continuous pan simply to hit 10:00.
Very long continuous shots need an explicit overlap/state-transfer design and
review; this project does not silently split them. Starting a batch is manual.
There is no timer, scheduler or promise that all work fits in one day.

## Before the first batch of a video

1. Keep the acquired source immutable and outside Git. Record its checksum,
   stream metadata, exact decoded frame count and presentation timestamps. Keep
   the source audio through natural EOF. Obtain any publication rights separately.
2. Review the shot census against the native source. Use half-open global frame
   intervals `[start, end)`, contiguous from zero through the last decoded frame.
   Detect fades/dissolves and their actual support; automatic cut scores alone
   do not establish the boundary. Mark leaders, title cards and neutral material.
3. Establish a palette for recurring physical materials (suit, skin, wood, board,
   walls and curtains). Colors are interpretations. Keep one reference bank per
   video, with source-frame numbers and provenance; reuse only compatible views.
4. Preflight the supported source contract and tools. The initial implementation
   is tuned to progressive 8-bit SDR BT.601 limited-range material. Unsupported
   VFR, interlacing, HDR, other color matrices or nonzero stream offsets need a
   deliberate ingestion/verification path, not a metadata relabeling shortcut.
5. Estimate storage from a small actual encode. Count source caches, RGB
   predictions, YUV masters, audio, trial versions, final copies and overlap
   contexts. Add a measured allowance and free-space reserve before rendering.

## Daily session

1. Read `status` and select `next`; keep the previous batch's reviewed outgoing
   context available. Inspect every pending hold before using a newer attempt.
2. Prepare only this batch's source cache, references, science masks and source
   transition measurements. Finish reference geometry/palette checks before GPU
   inference. For difficult shots, first render a short representative trial.
3. Publish each reference set atomically: image files first, then the hash-bound
   readiness receipt. Reference indices are **shot-local**, even though the
   census and QA notes use global frame indices.
4. Run one GPU queue. A fresh inference process starts at a real camera cut.
   Separate CPU merging can overlap, but a waiting later batch must release the
   delivery lock. Do not allow two workers to select or publish the same scope.
5. Merge predicted chroma with original native Y, then inspect the recombined
   result. A pretty model RGB image is not the preservation master.
6. Review faces/hands, occlusion edges, board shadows, text, podium crests,
   audience views and every transition at native scale. Use dense inspection
   for changed support and explicit margins; sparse contact sheets can miss
   one-frame defects. Play motion samples as well as inspecting still frames.
7. Apply localized corrections, version them, verify their protected regions,
   and bind selection to the exact reviewed output hash. Never replace source
   geometry or neutral scientific content to make an attractive image.
8. Assemble the batch and independently verify native Y, frame coverage/PTS,
   original decoded audio and any immutable reused ranges. Check the assembled
   joins, not just individual shots. A lossy viewing MP4 does not inherit the
   master's pixel/sample equality guarantees.
9. Record actual review scope, remaining limitations and whether continuous
   playback was performed. Mark a batch complete only against its current
   output identity; leave a concise handoff for tomorrow.

## Record review and continue

After the actual assembled-batch checks, save an attributed review JSON outside
Git. Its fields are `status` (`accepted`, `rejected` or `pending`),
`master_sha256`, `reviewed_by`, `reviewed_at` and `notes`. Copy the exact master
hash from the verified artifact; notes should identify the real review scope
and any remaining limits. Then run:

```powershell
python pipeline.py review --project work/projects/film --batch batch_001 --review-file D:/PrivateRun/batch-review.json
python pipeline.py next --project work/projects/film
```

A rejected or otherwise unresolved batch can be deliberately revised:

```powershell
python pipeline.py revise --project work/projects/film --batch batch_001 --reason "Describe the observed defect and planned correction"
```

This preserves previous decisions and requires new attempts before redelivery.
Accepted earlier batches are immutable in this wrapper. Reworking them requires
a new versioned project and renewed review of dependent joins and final output.
When all batches are explicitly accepted:

```powershell
python pipeline.py assemble --project work/projects/film
```

Assembly produces a draft for [independent final verification](validation.md)
and visual review. It does not automatically publish or accept the full video.

## What must survive between sessions

Source/checksum, shot census and time map; palette; approved references and their
receipts; settings and model/runtime hashes; selected masters and correction
receipts; all open rejection/hold decisions; completed technical proofs; neighbor
transition dependencies; a short next-action note. Keep these in the project's
private state directory. Back them up outside Git if media cannot be published.

Do not save browser cookies, access tokens or generated service links in the
repository. Repository code alone cannot reproduce a particular color decision
without the corresponding private references and reviewed masks.

## Stopping, resuming and cleanup

Stop at a completed shot/checkpoint. Resume only when source, code/runtime,
references, settings and completed output hashes still match. Partial encodes
are not reusable completed attempts. A rejection remains binding even if an
old readiness file still exists.

Before deleting an intermediate, prove it is obsolete, its current replacement
exists and verifies, and no active process depends on it. Retain the receipt.
Dry-run a cleanup inventory first and validate every resolved path is inside
the intended work directory. Never clean source media, model caches or another
application to satisfy a guessed space estimate. No automatic deletion ships
with the daily wrapper.

## Series backlog

Lecture 1 is the production case study. Lectures 2–7 are planned. Their actual
shot censuses, masks and references must be reviewed independently; Lecture 1
coordinates are not reusable annotations. The preferred pace is about one
ten-minute batch per working day, with quality holds taking precedence over
that pace. Finish and freeze one batch before moving on; assemble the complete
lecture once all its batches and cross-batch joins pass.
