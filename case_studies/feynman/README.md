# Feynman Lecture 1 case study

`lecture01-timeline.json` records public, non-image production facts and the
frame partition of the tested private source. It is **not** an executable approval
manifest and does not supply references, masks, model output or permission to
publish the recording.

`source-inventory.json` identifies original production source before portability
changes. `recipe-inventory.json` hashes the curated historical recipe snapshots.
The portable implementations live in the top-level `engine/`, `inference/` and
`pipeline.py`; their source differs where configuration and validation were added.

## Historical recipes

The `recipes/` files preserve the code for scene census, native-frame sampling,
independent technical proofs, scientific-mask assistance and localized material
corrections that informed this workflow. Their fixed source frame numbers,
960×720 geometry, private input paths and expected receipt schemas belong to
Lecture 1. **Do not run them unchanged on another video or import them as a public
library.** Several run their historical job on import. They are method templates,
not a turnkey reconstruction without the private source, guides and masks.

| Recipe family | Reusable lesson |
| --- | --- |
| `scenes/census.py`, `audit_cuts.py` | Source-first census; audit automatic candidates before accepting cuts |
| `scenes/qc/sample_native.py` | Inspect actual native-Y recombined guides/predictions |
| `verify_merged_y.py`, `verify_batch_master.py`, `verify_immutable_pilot.py` | Independent complete equality and native reuse checks |
| `audit_dissolve_correction.py`, `audit_board_zoom_sol.py` | Verify complete changed support, unchanged pixels and source identity |
| `proposal_temporal_mask_trial.py` | Bounded bidirectional foreground proposal, requiring source review |
| `board_zoom_material_trial/` | Physical board boundaries, conservative actor guards and per-frame chroma support |
| `board_material_trial/` | Source-bound board correction with reviewed back-edge exceptions |
| `podium_material_trial/`, `coat_fringe_trial/` | Narrow source-derived material correction rather than global hue replacement |
| `upload/verify_prores_upload.py` | Source-bound full ProRes decode, native cadence, EOF PCM and finite compression comparison; requires adaptation and new source verification |

Optional SAM 2 trial code requires its separately installed compatible model and
transformers support. The default CMNET2 runtime is not advertised as a complete
SAM 2 installation. Manual reviewed masks can supply the same core interface.

No `record_*`, `finalize_*` or `publish_*` visual-review PASS writers are copied
into this archive. Past reviews never establish approval for new output. Some
files are **proposal generators**: retaining the algorithm is not a claim that
every proposal it generated passed. In particular, sparse/offscreen physical
geometry priors require fresh native source checks and must not become material
masks merely because their JSON exists.

Whole-lecture technical delivery status is maintained locally; the repository
does not contain the copyrighted media or the private review evidence tree.
