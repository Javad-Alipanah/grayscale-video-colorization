# References, masks and acceptance

## Make geometry faithful before making color attractive

Extract a native source frame and use it as the reference-edit input. Supply a
palette or previously approved view. Request color only: preserve crop, pose,
face, fingers, chalk, lettering, cast shadows, film texture and all object
boundaries. Inspect the returned reference beside the source, then inspect its
chroma recombined with original Y. Reject changed geometry and invented detail.
Record the tool/model, source frame/hash, output hash, palette revision and review.

Suggested editing brief:

> Add restrained, plausible color using the approved material palette. Preserve
> every source object's shape and placement, expression, typography and framing.
> Keep scientific photographs, diagrams, chalk writing and printed overlays
> neutral unless there is documented reason for color. Do not sharpen, beautify,
> denoise or replace detail. Colors are interpretive, not historically verified.

The repository accepts reviewed reference PNGs from a human artist or an image
editing model. It does not contain a hosted paid image-generation client or
credentials. A vision-language/chat model is useful for reviewing and organizing
references but is not automatically an image generator. The exact model's output
capabilities must be established before using it to create guides.

Use references at changes in view, pose, visible material and lighting. A clean
empty-board reference does not teach the color of a person entering later.
Do not load unrelated camera views into one shot's memory. Avoid uniformly
spaced guides as a substitute for actual coverage. Lecture 1 exported 236 guides
across six packages, including specialized contexts and refinements; this is a
case-study count, not a universal requirement. Similar ten-minute batches may
initially need a few dozen guides, but actual coverage determines the count.

## Default inference profile

CMNET2 DINOv3 p374099, float32, longest chroma-processing side 512 pixels,
`top_k=30`, `mem_every=5`, cuDNN autotuning disabled, proximity bias disabled.
Use a fresh process at each real cut. Native resolution is preserved in the
master; inference detail is color information at the stated processing scale.

On the development RTX 5070 Laptop GPU, a corrected 288-frame pilot rendered at
about 5.745 fps after initialization with about 1.1 GiB peak PyTorch allocation.
Other short trials and initialization peaks differed. This does not include guide
creation, corrections, source caching, review, export or final verification.
At that single measured rate, 14,386 frames is about 42 minutes of propagation;
it is not a complete-batch turnaround estimate. Record fresh timings per batch.

## Scientific content and dissolves

Preserve scientific illustrations as neutral source chroma. A screen polygon
alone is insufficient: exclude the lecturer, hands and pointer while retaining
the cast shadow as part of the screen. Validate moving masks against native
source frames, particularly fingers, pale sleeves and shoulder edges.

For dissolves, protect each outgoing/incoming scene hypothesis **before** applying
the original frame's measured dissolve alpha. Use actual moving per-frame
chroma from both sides, including outgoing handles across a batch boundary.
Applying protection after the blend can erase the lecturer. Holding endpoint
chroma across a moving dissolve produces colored ghosts. Do not assume every
transition lasts six frames or that a hard cut is a dissolve.

## Two different kinds of proof

Technical: complete frame coverage; original decoded Y; source audio sample
count and decoded samples through EOF; every timestamp; exact approved-master
reuse; no decoder errors; source chroma inside protected support and no changed
chroma outside authorized support when those guarantees apply.

Visual: plausible consistent palette; stable faces, hands and clothing; no
colored shadows, flicker, bleed or geometry errors; correct transition behavior.
Technical equality does not imply good color. A visual pass does not imply
sample equality. Receipts must identify which checks were actually performed.

Any reviewer should record the exact output hash, global frame scope, comparison
sources, observation, disposition and known limitation. An assistant's failure
or model-capacity error is not a media-render failure: save the review scope,
use bounded retries and continue with another available reviewer when authorized.
Never manufacture a pass to unblock publication.
