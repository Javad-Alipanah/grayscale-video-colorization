# Grayscale Video Colorization

A careful, reference-guided workflow for adding interpretive color to old
grayscale video while retaining source detail and sound. Developed and tested
on the Caltech-restored **Richard Feynman: The Character of Physical Law,
Messenger Lecture 1 (1964)**.

The pipeline propagates reviewed color references with CMNET2, combines predicted
chroma with original native luminance, protects scientific illustrations, and
verifies the lossless master separately from the viewing copy. It includes the
production code and lessons from that restoration. Human reference/mask review
remains essential; colors are not claimed to be historically authentic.

## Work in small, resumable batches

Plan roughly ten minutes at a time, ending at reviewed shot boundaries. Start one
batch when convenient, keep its references and checks, and resume another day.
Rendering never automatically means approval. The pipeline records hashes and
quality holds so a stale or rejected result cannot silently become a final choice.

```powershell
# Install dependencies/models first: docs/setup.md
python pipeline.py init --source D:/Media/source.mkv --shots my-reviewed-shots.json --project work/projects/film --batch-seconds 600
python pipeline.py next --project work/projects/film
python pipeline.py status --project work/projects/film

# After preparing and reviewing this batch's reference sets:
python scripts/publish_reference_set.py --project work/projects/film --review-file D:/PrivateGuides/review.json
python pipeline.py render --project work/projects/film --batch batch_001
python pipeline.py deliver --project work/projects/film --batch batch_001
```

See [setup](docs/setup.md), the [daily runbook](docs/workflow.md),
[references and QA](docs/references-and-quality.md), and
[lessons from Lecture 1](docs/lessons-from-lecture-1.md).
The [reference protocol](docs/reference-protocol.md) explains guide publication
and the separate shot/batch review records required before continuing.
The [scientific-mask guide](docs/scientific-masks.md) covers protected diagrams
and moving foregrounds.
The [ProRes upload recipe](docs/upload-export.md) covers a separately verified
MOV export from the lossless master.

## Included

- Portable production, reference publication, source preparation and delivery code.
- Chroma-only correction, source-timed dissolve and scientific-mask tools.
- Regression checks for resume, stale reviews, queue locks, source preservation
  and audio tails; pinned runtime/model identities.
- Three [synthetic examples](examples/README.md), with their generator.

Full clips, lecture stills, reference images, weights and private run state stay
outside Git. [Model/software licenses](THIRD_PARTY.md) and
[film publication rights](docs/media-rights.md) are separate from this repository's
MIT license. No permission for a public Feynman re-upload is claimed.

## Scope

This is an adaptable workflow, not a one-click solution for every old video.
The tested profile is progressive 8-bit SDR, BT.601 limited range, 960×720 at
24000/1001 fps, with original audio. Other formats need deliberate ingest and
verification work. Exact luminance/audio guarantees apply to verified lossless
masters; they do not apply to lossy MP4s or YouTube re-encodes. See the
[validation record](docs/validation.md) for what the portable repository has
actually been tested to do.

Thanks to the creators of [CMNET2](https://github.com/dan64/cmnet2),
[ColorMNet](https://github.com/yyang181/colormnet), DINOv3, PyTorch and FFmpeg,
and to the [official lecture site](https://www.feynmanlectures.caltech.edu/messenger.html)
for its account of the source restoration. This project is independent and
does not imply endorsement by the BBC, Caltech, Cornell or the Feynman estate.
