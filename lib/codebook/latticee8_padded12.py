"""
E8 2 bit, or E8P.

D8^ = D8 + 1/2 intersected with ball of radius sqrt(10)
|D8^| has 227 entries
We then add 29 entries from the set of vectors with 5 3/2 and 3 1/2
The total codebook is all 2^7 flips of these 256 entries (2^15) +- 1/4
which makes 2^16 entries.
This corresponds to a subset of E8 + 1/4
"""
import itertools
import math
from functools import cache

import quiptools_cuda
import torch
from torch import nn

from lib.utils.matmul_had import matmul_hadU_cuda, matmul_hadUt_cuda

_E8P_CODESZ = 8


def get_norm12():
    # 29 elements of norm 12 in E8 + 1/4
    return torch.tensor([
        [3, 1, 1, 1, 3, 3, 3, 3],
        [1, 3, 1, 1, 3, 3, 3, 3],
        [1, 1, 3, 1, 3, 3, 3, 3],
        [1, 1, 1, 3, 3, 3, 3, 3],
        [3, 3, 3, 1, 3, 3, 1, 1],
        [3, 3, 3, 1, 3, 1, 3, 1],
        [3, 3, 3, 1, 1, 3, 3, 1],
        [3, 3, 3, 1, 3, 1, 1, 3],
        [3, 3, 3, 1, 1, 3, 1, 3],
        [3, 3, 3, 1, 1, 1, 3, 3],
        [3, 3, 1, 3, 3, 3, 1, 1],
        [3, 3, 1, 3, 3, 1, 3, 1],
        [3, 3, 1, 3, 1, 3, 3, 1],
        [3, 3, 1, 3, 3, 1, 1, 3],
        [3, 3, 1, 3, 1, 3, 1, 3],
        [3, 3, 1, 3, 1, 1, 3, 3],
        [3, 1, 3, 3, 3, 3, 1, 1],
        [3, 1, 3, 3, 3, 1, 3, 1],
        [3, 1, 3, 3, 1, 3, 3, 1],
        [3, 1, 3, 3, 3, 1, 1, 3],
        [3, 1, 3, 3, 1, 3, 1, 3],
        [1, 3, 3, 3, 1, 1, 3, 3],
        [1, 3, 3, 3, 3, 3, 1, 1],
        [1, 3, 3, 3, 3, 1, 3, 1],
        [1, 3, 3, 3, 1, 3, 3, 1],
        [1, 3, 3, 3, 3, 1, 1, 3],
        [1, 3, 3, 3, 1, 3, 1, 3],
        [1, 1, 3, 3, 1, 3, 3, 3],
        [3, 3, 1, 1, 3, 3, 3, 1],
    ]) / 2


def get_packed_abs_grid():
    intr = torch.arange(-4, 4)
    d8 = torch.cartesian_prod(*[intr] * 8).float() + 1 / 2 # 8**8 elements with size 8
    d8m2 = (d8.sum(dim=-1) % 2 == 0) # mask for even sum vectors Z^8
    d8n = d8.norm(dim=-1)**2 <= 10 # first group d8n, norm 10 mask
    d8abs = torch.unique(d8[sorted(torch.where(d8m2 * d8n)[0])].abs(), dim=0) # abs unique
    norm12 = get_norm12() # magic
    cba = torch.concat([d8abs, norm12], dim=0)
    cba = cba[:, [0, 2, 4, 6, 1, 3, 5, 7]] # Why shuffle?
    cba[:, 7] *= (1 - 2 * (cba.sum(1) % 2)) # even flip *1 or odd flip *-1, make the base abs vectors all have even sum. all positive numbers, thus flip cause no duplicate
    cba = cba * 2 + 8 # -4 ~ 3 -> 0~2**4
    cba = cba.to(torch.int32)
    acc = cba[:, 0]
    for i in range(7):
        acc = acc | (cba[:, (i + 1)] << ((i + 1) * 4)) # 8 numbers each occupy 4 bits
    return acc # D8


def get_abs_grid():
    intr = torch.arange(-4, 4)
    d8 = torch.cartesian_prod(*[intr] * _E8P_CODESZ).float() + 1 / 2
    d8m2 = (d8.sum(dim=-1) % 2 == 0)
    d8n = d8.norm(dim=-1)**2 <= 10
    d8abs = torch.unique(d8[sorted(torch.where(d8m2 * d8n)[0])].abs(), dim=0)
    norm12 = get_norm12()
    cba = torch.concat([d8abs, norm12], dim=0)
    return cba # 256 x 8 not packed not flipped


def get_full_grid(packed_abs_grid):
    synth_codebook = torch.zeros(1 << 16, 8) # 2**kd x d, k=2, d=8
    parity_idx = []
    shuffle_map = [0, 4, 1, 5, 2, 6, 3, 7] # this is how it was packed
    for c in range(1 << 16):
        signs = c & 255 # mod 2 ** 8, 8 sign bits
        abs = c >> 8 # floordiv 2 ** 8, 8 codebook bits
        parity = 0
        for i in range(8):
            parity = parity ^ ((signs >> i) & 1) # if even num of 1s, then 0.
        signs = signs ^ parity # flip the last bit of sign if odd 1s, force to be all even parity. For odd parity abs base, it already flipped in base abs.
        abs_code = packed_abs_grid[abs].item() # int32 contains 8 numbers with 4 bits
        for i in range(8):
            ii = shuffle_map[i]
            synth_codebook[c, i] = (((abs_code >> (4 * ii)) & 15) - 8) * 0.5 # original code *2+8 already
            if ((signs >> ii) & 1):
                synth_codebook[c, i] *= -1
        if parity:
            synth_codebook[c, :] -= 0.25 # D8-1/4, parity has been flipped in sign variable, thus last bit now just a flag for the same code bits, and same signs.
            parity_idx.append(c)
        else:
            synth_codebook[c, :] += 0.25 # D8+1/4
    return synth_codebook, torch.arange(1 << 16), parity_idx # E8+1/4


_E8P_PACKED_ABS_CACHED = get_packed_abs_grid()
_E8P_GRID, _E8P_GRID_IDX, _PARITY_IDX = get_full_grid(_E8P_PACKED_ABS_CACHED)


class E8P12_codebook(nn.Module):

    def __init__(self, inference=False):
        super(E8P12_codebook, self).__init__()
        self.opt_scale = 1.03
        self.codesz = _E8P_CODESZ
        self.idx_dtype = torch.int64
        self.packsz = 4
        self.pack_out = False
        self.version = 1

        self.register_buffer('grid_packed_abs', _E8P_PACKED_ABS_CACHED) # 256 x 8

        if not inference:
            self.register_buffer('grid', _E8P_GRID) # 2 ** 16 x 8, E8+1/4
            self.register_buffer('grid_norm', _E8P_GRID.norm(dim=-1)**2) # sum of square, 2**16
            grid_part = _E8P_GRID[_PARITY_IDX] + 0.25 # parity number: 2**15, D8-1/4+1/4
            grid_part = grid_part[ # TODO D8 not considering last number, at most 1 neg, and it >=-0.5
                torch.where(
                    ((grid_part[:, :7] < 0).sum(dim=-1) <= 1) * \
                    (grid_part[:, :7].min(dim=-1).values >= -0.5)
                )[0]]
            self.register_buffer('grid_part', grid_part)
            self.register_buffer('grid_part_norm', grid_part.norm(dim=-1)**2)
            abs_grid = get_abs_grid()
            self.register_buffer('grid_abs_odd', abs_grid.sum(dim=-1) % 2 == 1)
            self.register_buffer(
                'part_abs_map', # nearest neighbors of part (1366 elements out of 2**15) from grid abs 256 elements
                self.round(grid_part.abs(), abs_grid,
                           abs_grid.norm(dim=-1)**2)[1])
            self.register_buffer('bit_map', 2**torch.arange(8)) # [1, 2, 4, ... 128]
            '''
            self.to('cuda')
            samples = torch.distributions.multivariate_normal.MultivariateNormal(torch.zeros(8), torch.eye(8)).rsample([2000000]).cuda()
            for s in torch.arange(0.8, 1.2, 0.01):
                print(s, ((self.quantize(samples*s, False)/s - samples).norm(dim=-1)**2).mean())
            exit()
            '''

    def round(self, X, grid, grid_norm):
        assert X.shape[-1] == self.codesz
        Xqidx = (2 * X @ grid.T - grid_norm).argmax(-1) # Euclidean distance
        return grid[Xqidx], Xqidx # X.shape[0] x 8, X.shape[0]

    def fast_quantize_part(self, X, parity):
        X_part = torch.abs(X)
        X_odd = torch.where((X < 0).sum(dim=-1) % 2 != 0)[0]
        X_part[X_odd, 7] = -X_part[X_odd, 7] # flip last el
        mask = 1 - 2 * (X < 0).to(torch.float32) # neg, pos -> -1, +1
        mask[X_odd, 7] = -mask[X_odd, 7] # flip last mask
        roundout, Xqidx = self.round(X_part, self.grid_part,
                                     self.grid_part_norm) # RTN VQ
        vals = roundout * mask # final val
        err = (X - vals).norm(dim=-1)
        abs_idx = self.part_abs_map[Xqidx]
        sign_mask = (((roundout < 0) ^ (mask < 0))[:,
                                                   [0, 2, 4, 6, 1, 3, 5, 7]]) # just sign
        sign_mask[:, 7] = sign_mask[:, 7] ^ self.grid_abs_odd[abs_idx] # 256 flag, whether abs are odd parity
        sign_mask[:, 0] = sign_mask[:, 0] ^ parity
        mask_idx = (sign_mask * self.bit_map).sum(dim=-1).int() # bit_map: 1, 2, ...128, means right shifts for packing
        idx = (abs_idx << 8) + mask_idx
        return vals, idx, err # rounded val, idx in full grid, quant error

    def quantize(self, X, return_idx=True, **kwargs):
        X_plus = X + 1 / 4  # quantize X to D8^ - 1/4
        X_minus = X - 1 / 4  # quantize X to D8^ + 1/4

        plus_vals, plus_idx, plus_err = self.fast_quantize_part(X_plus, True)
        minus_vals, minus_idx, minus_err = self.fast_quantize_part(
            X_minus, False)

        which = plus_err < minus_err
        final_vals = torch.where(which.unsqueeze(-1), plus_vals - 1 / 4, # minus 1/4 back
                                 minus_vals + 1 / 4)
        final_idx = torch.where(which, plus_idx, minus_idx)

        if return_idx:
            return final_vals, final_idx # mxg, m

        return final_vals

    def maybe_pack_idxs(self, idxs): # mxn/8, 16bit each
        m, n = idxs.shape
        idxs = idxs.view(m // 2, 2, (n * 8) // 16,
                         2).transpose(1, 2).contiguous() # m/2, n/16, 2, 2, int64

        abs32 = (idxs[:, :, 0, 0] >> 8) + \
            ((idxs[:, :, 1, 0] >> 8) << 8) + \
            ((idxs[:, :, 0, 1] >> 8) << 16) + \
            ((idxs[:, :, 1, 1] >> 8) << 24) # 2x2 as a group and don't record sign, m/2xn/16

        sign32 = torch.zeros(abs32.shape,
                             dtype=abs32.dtype,
                             device=abs32.device) # m/2xn/16
        for i in range(4):
            wt = idxs[:, :, i % 2, i // 2]
            for j in range(8):
                sign32 += ((wt >> j) & 1) << (4 * j + i)

        output = (sign32 << 32) + abs32 # sign: 4bits for 8 numbers, etc. abs: 4 8bit numbers
        output = output.reshape(m // 16, 8, n // 8,
                                4).transpose(1, 2).contiguous() # block 8x4
        return output.view(m, n // 4) # 16bit -> 64bit

    def by_idxs(self, idxs, **kwargs):
        m, n = idxs.shape
        W_decompressed = quiptools_cuda.decompress_packed_e8p(
            idxs.view(m // 16, n // 2, 8, 4), self.grid_packed_abs)
        return W_decompressed


class QuantizedE8P12Linear(nn.Module):

    def __init__(self, device):
        super().__init__()
        self.codebook = E8P12_codebook(inference=True).to(
            torch.float16).to(device)
        self.scale = 32

    def maybe_unpack_idxs(self, idxs):
        return (idxs, )

    def cache_WH(self, n, m, Qidxs_list, had_left, had_right, K_left, K_right,
                 **kwargs):
        self.W = matmul_hadU_cuda(
            matmul_hadU_cuda(
                quiptools_cuda.decompress_packed_e8p(
                    Qidxs_list[0].view(m // 16, n // 64, 8, 4),
                    self.codebook.grid_packed_abs).float() / self.scale,
                had_left, K_left).T,
            had_right,
            K_right,
        ).to(torch.float16)

    def forward(self,
                input,
                Qidxs_list,
                SU,
                SV,
                had_left,
                had_right,
                K_left,
                K_right,
                rank=-1,
                A=None,
                B=None,
                rescale_WH=False,
                scaleWH=None,
                train_mode=False,
                **kwargs):
        n, m = len(SU), len(SV)
        x = input.view(-1, n).to(torch.float32)
        if rescale_WH:
            x /= scaleWH
        x = x * SU

        if train_mode:
            x = (x.to(torch.float16) @ self.W).float()
        else:
            x = matmul_hadUt_cuda(x, had_left, K_left) / self.scale

            if rank > 0:
                Bx = x @ B.t().to(torch.float32)
                ABx = Bx @ A.t().to(torch.float32)

            if x.size(0) == 1:
                x = quiptools_cuda.decode_matvec_e8p(
                    x[0].to(torch.float16),
                    Qidxs_list[0].view(m // 16, n // 64, 8, 4),
                    self.codebook.grid_packed_abs).to(torch.float32)
            else:
                W_decompressed = quiptools_cuda.decompress_packed_e8p(
                    Qidxs_list[0].view(m // 16, n // 64, 8, 4),
                    self.codebook.grid_packed_abs)
                x = (x.to(torch.float16) @ W_decompressed.T).to(torch.float32)

            if rank > 0:
                x = x + ABx.to(torch.float32)

            x = matmul_hadU_cuda(x, had_right, K_right)

        x = x * SV * self.scale

        output = x.view(*input.shape[:-1], m)
        return output
