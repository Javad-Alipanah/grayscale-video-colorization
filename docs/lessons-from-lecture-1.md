# What Lecture 1 taught us

The slowest work was correcting and reviewing references, moving boundaries and
material behavior. Reusing those methods should reduce rework; it does not make
future lectures automatic or guarantee the same colors are historically correct.

| Pitfall | Consequence | Practice carried forward |
| --- | --- | --- |
| Reference changes a hand/face while looking attractive | Chroma no longer follows source geometry | Review native source-Y recombination before rendering |
| Empty-board guide used after lecturer re-enters | Missing skin/suit guidance | Add view-compatible human/pose references |
| Memory reset inside a continuous zoom | Palette discontinuity | Keep a continuous shot continuous; freeze crop mapping |
| Held endpoint colors through a moving dissolve | Colored ghosts | Per-frame scene hypotheses and measured source alpha |
| Generic transition duration | Wrong blend support | Measure each original transition |
| Screen mask applied after compositing | Lecturer or hand becomes gray | Protect each hypothesis first, then blend |
| Raw segmentation treated as truth | Shadows, fingers and cloth mislabeled | Dense source review plus bounded contour fixes |
| Coarse board tracking across viewport entry | Rails, gaps or curtain colored as board | Source-supported physical boundaries and conservative insets |
| Broad hue rectangles or convex mask fills | Changed unrelated material | Restrict both spatial and temporal support; keep uncertain edges |
| Brightness preservation treated as quality proof | Color defects still visible | Separate technical and visual acceptance |
| Mutable approval timestamps in cache keys | Needless rerenders | Fingerprint content and settings |
| Readiness published before its images | Queue consumes partial references | Atomic files first, readiness receipt last |
| Windows reader temporarily locks a checkpoint | Incomplete status update | Fsync, bounded rename retry, retain recoverable old state |
| Later queue holds lock while waiting | Ready work blocked | Release shared delivery lock during waits |
| Old rejection lost when selection changes | Rejected chroma returns | Bind rejection and selection to exact payload hashes |
| Repeated decode from frame zero | Slow preparation | Reusable native frame-indexed batch caches |
| Range checks decode the rest of a lecture after the requested interval | Long avoidable QA scans | Cap decoded output frames; any seek optimization must prove exact alignment |
| Video duration used to truncate audio | Natural audio EOF lost | Verify complete original decoded PCM, including tail |
| Cleanup changes container identity | Review provenance becomes stale | Keep replacement/hash receipts and dependency evidence |
| Whole-lecture estimates mix GPU with human review | Misleading finish times | Report render, corrections, encode and QA separately |
| Reviewer capacity failures repeatedly retried | Long idle delays | Persist finite assigned scopes and switch available workers when authorized |

## Speed improvements that preserve the standard

Preflight all guides and motion boundaries for one batch before inference.
Reuse the environment, approved material palette, cached source and tools.
Render difficult short trials before committing long shots. Divide QA into
non-overlapping, hash-bound scopes; do not ask two reviewers to inspect the same
frames by accident. Overlap CPU preparation/encoding with independent review
where memory, disk and locking permit it. Freeze each accepted batch and carry
its outgoing context to the next day's work.

## Case-study limits

Tested material: the Caltech-served restored version of Feynman's first 1964
Messenger Lecture, 960×720, 24000/1001 fps, 80,026 frames (55:37.751).
All first-pass footage and planned localized corrections have been produced.
The assembled lossless master passed independent full Y, PCM, timestamp and
immutable-pilot checks. Full continuous viewing is assigned to the owner;
no whole-lecture playback pass is claimed. The public repository port has its
own validation record and is not assumed equivalent merely because the original
production ran successfully.

Colors are inferred. Fine blurred actor edges and uncertain material boundaries
sometimes deliberately keep a conservative rim. The exact private guides and
human decisions remain necessary to reproduce the same artistic result.
