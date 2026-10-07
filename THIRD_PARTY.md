# Third-party software and media

The MIT license covers our orchestration and synthetic examples. There is no
blanket MIT grant for a complete installed model stack or a processed film.

| Component | Source and terms | Repository treatment |
| --- | --- | --- |
| CMNET2 | [dan64/cmnet2](https://github.com/dan64/cmnet2), pinned to `e0d51432d224476769babfbff5e90f531a454939`; its README inherits ColorMNet terms | External checkout; no neural source or weights vendored |
| ColorMNet | [Official README](https://github.com/yyang181/colormnet#license) states CC BY-NC-SA 4.0, mixed component licenses and academic research use | Review original terms before use; do not assume a commercial grant |
| DINOv3 | [Meta DINOv3 license](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md) | Separate custom terms; acknowledge use; weights remain external |
| ResNet / PyTorch / torchvision | [PyTorch](https://github.com/pytorch/pytorch), [torchvision](https://github.com/pytorch/vision) | Installed externally; official model files verified against recorded hashes |
| FFmpeg | [License and build configuration](https://ffmpeg.org/legal.html) | User-installed executable; redistribution terms depend on build |
| NumPy, Pillow, OpenCV, transformers and other Python dependencies | Their respective distribution licenses | Installed from their own packages |
| Optional SAM 2 experiments | [facebookresearch/sam2](https://github.com/facebookresearch/sam2) | Optional historical mask assistance, not required by the core; no source or checkpoints shipped |
| Feynman lecture recordings and restored source | [Official viewing page](https://www.feynmanlectures.caltech.edu/messenger.html) | No recordings, audio, film stills or generated film guides included |

The small PyTorch correlation adapter is our implementation of the mathematical
operation used by the model. Its test compares against explicit spatial-offset
loops. It is not a copy of the upstream compiled extension and does not claim
bit-identical agreement with that unavailable binary.

The model dependency terms need separate evaluation before commercial use or
redistribution of model modifications. Film permission is a separate question;
permission to use software does not grant rights in input footage. This project
does not determine whether every third-party term attaches to every output.

Checked 7 October 2026. Follow the linked authoritative terms if they change.
