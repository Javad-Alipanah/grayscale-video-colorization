"""PyTorch-only equivalent of the kernel-size-1 sampler used by CMNET2.

For each spatial offset in the patch, output the channel dot product between
input1 at (y, x) and zero-padded input2 at (y+dy, x+dx). All tensor operations
stay on the input device. No learned parameters or model weights are changed.
"""
import torch
from torch import nn
from torch.nn import functional as F


class SpatialCorrelationSampler(nn.Module):
    def __init__(self, kernel_size=1, patch_size=1, stride=1, padding=0,
                 dilation=1, dilation_patch=1):
        super().__init__()
        if (kernel_size, stride, padding, dilation) != (1, 1, 0, 1):
            raise NotImplementedError("Only the exact CMNET2 correlation configuration is supported")
        if patch_size % 2 != 1:
            raise ValueError("Odd patch size required")
        self.patch_size = patch_size
        self.dilation_patch = dilation_patch

    def forward(self, input1, input2):
        if input1.shape != input2.shape or input1.ndim != 4:
            raise ValueError("Expected equal NCHW tensors")
        n, c, h, w = input1.shape
        p = self.patch_size
        unfolded = F.unfold(input2, kernel_size=p, dilation=self.dilation_patch,
                            padding=(p // 2) * self.dilation_patch)
        unfolded = unfolded.reshape(n, c, p * p, h * w)
        values = (input1.reshape(n, c, 1, h * w) * unfolded).sum(dim=1)
        return values.reshape(n, p, p, h, w)
