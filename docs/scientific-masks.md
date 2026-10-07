# Scientific-image protection protocol

In a reviewed shot census, mark colorized scenes containing projected scientific
images with `scientific_screen_scene_id` and `scientific_screen_mask_ready`.
The latter is the path to that scene's readiness record. Do this before project
initialization; adding/removing a scientific scene changes the frozen plan.
Keep the scene ID when rendering its additional dissolve context.

The matte is a native-dimension, native-cadence, **binary FFV1 gray video**:
255 preserves original scientific-source UV; 0 uses predicted foreground/stage
UV. It must include all frames of the scene hypothesis, including reviewed
dissolve handles. Exclude the lecturer, pointer, fingers and clothing. A shadow
cast on a projected photograph belongs to the projected surface. Exact pixel
checks cannot decide these semantic boundaries for you.

The record shape is illustrated below; pending values cannot enter delivery.
After independent native source-mask review, the review status is
`local_source_mask_pass`, bound to `scene_id` and `mask_sha256`. The readiness
status can then become `source_mask_native_review_pass` with the actual review
path/hash. These are assertions about completed work, not flags to flip merely
to unblock a queue.

```json
{
  "schema_version": 1,
  "status": "pending",
  "scene_id": "shot_000240",
  "source_sha256": "REPLACE_WITH_SOURCE_SHA256",
  "width": 960,
  "height": 720,
  "fps_num": 24000,
  "fps_den": 1001,
  "start_frame": 240,
  "end_frame": 720,
  "mask_path": "REPLACE_WITH_PRIVATE_MASK_PATH",
  "mask_sha256": "REPLACE_WITH_MASK_SHA256",
  "pixel_format": "gray",
  "mask_semantics": "255=source scientific UV, 0=predicted foreground/stage UV",
  "foreground_exclusions_included": false,
  "native_visual_review_pass": false,
  "review_receipt": "REPLACE_WITH_COMPLETED_REVIEW_PATH",
  "review_receipt_sha256": "REPLACE_WITH_REVIEW_SHA256"
}
```

`scientific_mask.load()` checks identity, geometry, coverage and the independent
review binding. Trial masks are accepted only in explicit diagnostic calls and
cannot enter normal delivery. The engine verifies complete original Y, source
UV inside mask255 and prediction UV outside it. These claims apply to that
scene hypothesis. It must be protected before composing a source dissolve;
they do not automatically describe the final blended frame's spatial mask.

Batch assembly also requires an independently written scope record at
`PROJECT/scenes/qc/projection_masks/BATCH_delivery_ready.json`. It contains the
original `source_sha256`, exact `selected_output_sha256` map for **all selected
shots**, status `scientific_scope_review_pass`, and
`scene_hypothesis_masks_reviewed: true` and
`source_dissolve_composites_reviewed: true`. State the actual reviewed scientific
scope in the evidence rather than implying every unrelated scene was inspected.

For full assembly the scope is `full`, so the corresponding marker is
`full_delivery_ready.json`. The delivery watcher writes a request containing
the required current output hashes, releases its CPU lock and waits/returns.
Never copy an earlier scope marker if selected content has changed.

Manual masks or external segmentation can generate candidates. Historical SAM 2
proposal code is retained under the case study for adaptation, but its output
still requires source review and bounded corrections. You can use manual masks
without installing that optional model.
