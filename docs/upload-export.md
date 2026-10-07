# ProRes MOV upload export

Keep the verified lossless master as the preservation artifact. This upload recipe
encodes ProRes 4444 without alpha and copies its original PCM audio. ProRes is
lossy: exact original-Y equality applies to the lossless master, not this MOV.
This is an export recipe, not permission to publish the underlying film.

The tested input is native 960×720, square pixels, 24000/1001 fps, limited range
with the `bt470bg` matrix. Retain that matrix and range; leave unknown primaries
and transfer characteristics unknown. Do not relabel this source BT.709 or invent
a gamma/gamut conversion. Verify another source's metadata before adapting it.

## Encode to a staging file

Use a new destination; `-n` refuses overwrite. These arguments reproduce the
actual export, with generic paths and title. No resize, frame interpolation,
audio filtering, `-shortest`, or audio-duration trim is applied.

```powershell
$ffmpeg = 'ffmpeg' # Or your configured executable
$master = 'D:/Media/verified-lossless.mkv'
$staged = 'D:/Work/upload-staged.mov'
$progress = 'D:/Work/upload-progress.txt'
$title = 'Lecture title - Colorized'
$exportArgs = @(
  '-hide_banner', '-nostdin', '-v', 'warning', '-n', '-threads', '4',
  '-i', $master, '-map', '0:v:0', '-map', '0:a:0',
  '-map_metadata', '-1', '-map_chapters', '-1',
  '-vf', 'format=yuv444p10le,setsar=1',
  '-c:v', 'prores_ks', '-profile:v', '4', '-alpha_bits', '0',
  '-threads:v', '16', '-pix_fmt', 'yuv444p10le',
  '-color_range', 'tv', '-colorspace', 'bt470bg',
  '-color_primaries', 'unknown', '-color_trc', 'unknown',
  '-fps_mode', 'passthrough', '-enc_time_base:v', '1001/24000',
  '-video_track_timescale', '24000', '-c:a', 'copy',
  '-write_tmcd', '0', '-use_editlist', '0',
  '-movflags', '+faststart+write_colr', '-metadata', "title=$title",
  '-metadata', 'comment=Interpretive colorization; native framing and cadence; original PCM audio.',
  '-progress', $progress, '-nostats', $staged
)
& $ffmpeg @exportArgs
if ($LASTEXITCODE -ne 0) { throw 'Export failed; do not publish the staging file.' }
```

The canonical frame interval is **1001/24000 seconds**. The encoder time base
and MOV track timescale recover that grid from the master's rounded Matroska
timestamps. Use this only after confirming every source timestamp is within
0.5 ms of that grid, with no missing/duplicate frames; independently check every
output timestamp afterward. Do not use cadence recovery to conceal VFR or gaps.
The encoder input is 10-bit 4:4:4; a ProRes 4444 decoder may report 12-bit output.
That does not add detail to the original 8-bit source.

## Budget and verify before publication

A short representative encode projected roughly 40–45 GB for the full lecture
(45.4 GB decimal forecast); the closed Lecture 1 MOV is 38.26 GB decimal. Forecast from
measured bytes per frame × total frames, check free space on the staging volume,
and retain at least an additional 8 GiB reserve. Allow for a second full copy if
the final destination is on another volume.

After the encoder closes successfully, hash the staged file and perform a full
decode through natural EOF with errors treated as failures. Check native size,
frame count, range/matrix, every video timestamp against the canonical grid,
audio channel/rate metadata, and the complete decoded PCM bytes and audio sample
clock against the lossless master. Include the audio tail; it may outlast video.
Only then move the checked staged file to its final name and record its hash,
command, source hash, metadata and verification results. Visual review is separate.

See the [validation record](validation.md). The existing exact-Y preservation
verifier is intended for lossless masters and must not be used to claim original-Y
equality for this lossy ProRes export or the platform's subsequent transcode.

The archived [Lecture 1 upload verifier](../case_studies/feynman/recipes/upload/verify_prores_upload.py)
preserves the actual finite checks, including every-frame compression comparison.
It is **Lecture 1 only**: it requires the exact delivered master hash, 80,026
frames, 160,210,944 audio samples per channel, stereo 48 kHz and native 960×720
geometry. Adapt and independently establish new source limits before using the
method for another lecture. It records technical results, not visual acceptance.
FFmpeg tools resolve from `COLOR_FFMPEG`/`COLOR_FFPROBE` or PATH. Run without
Python optimization, since the historical recipe uses assertions as checks.

```powershell
# Only for the exact source-bound Lecture 1 lossless master and its derivative:
python case_studies/feynman/recipes/upload/verify_prores_upload.py `
  --master D:/Media/Lecture_01_Colorized_Lossless.mkv `
  --export D:/Work/upload-staged.mov --profile 4444 `
  --receipt D:/Work/upload-technical-receipt.json
```
