#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy", "numba", "pillow"]
# ///
"""Procedural gruvbox-dark wallpapers -- no image model, just maths.

Usage: procwall.py [--pieces mandel,coral,silk] [--sizes uw,wide,laptop] [--out DIR] [--preview]

Writes <out>/gruvbox-dark-<N>-<size>.png at the native size of each screen
(same size tags as gen_wallpapers.py), so `wallpaper-pick` rotates them in with
the generated ones. Each piece keeps the same composition rule as the prompts --
quiet centre band for the terminal, detail at the left and right edges -- but
gets it from the maths rather than from a mask:

  20 mandel  Mandelbrot "bookends": the image is folded at the centre seam, so
             the middle is the black interior of the main cardioid and the
             seahorse-valley filigree sits at both edges, mirror images.
  21 coral   Gray-Scott reaction-diffusion with feed/kill rates that vary with
             distance from the centre: labyrinth coral at the edges breaks up
             into mitosis spots and dies out entirely in the middle.
  22 silk    Two Clifford strange attractors, ~2.4e9 orbit points, log-density
             rendered and two-tone by local speed, bleeding in from either side.

Needs no venv: `uv run` reads the dependency block above.
"""
import argparse, math, pathlib, sys, time

import numpy as np
from numba import njit, prange
from PIL import Image

SIZES = {"uw": (3440, 1440), "wide": (2560, 1440), "laptop": (2560, 1600)}
PIECES = {"mandel": 20, "coral": 21, "silk": 22}

H = lambda s: np.array([int(s[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64)
BG0 = H("#1d2021"); BG = H("#282828"); BG1 = H("#3c3836"); BG2 = H("#504945")
FG = H("#ebdbb2"); FG2 = H("#d5c4a1"); GREY = H("#928374")
RED = H("#cc241d"); RED2 = H("#fb4934"); GREEN = H("#98971a"); GREEN2 = H("#b8bb26")
YEL = H("#d79921"); YEL2 = H("#fabd2f"); BLUE = H("#458588"); BLUE2 = H("#83a598")
PURP = H("#b16286"); PURP2 = H("#d3869b"); AQUA = H("#689d6a"); AQUA2 = H("#8ec07c")
ORNG = H("#d65d0e"); ORNG2 = H("#fe8019")


def lut(stops, n=1024):
    """Piecewise-linear colour ramp through evenly spaced stops -> (n, 3) float."""
    stops = np.array(stops, dtype=np.float64)
    x = np.linspace(0, len(stops) - 1, n)
    i = np.minimum(x.astype(int), len(stops) - 2)
    f = (x - i)[:, None]
    return stops[i] * (1 - f) + stops[i + 1] * f


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def finish(rgb, seed=1):
    """Film grain (kills banding in the dark gradients), clamp, to uint8."""
    rng = np.random.default_rng(seed)
    rgb = rgb + rng.normal(0, 1.6, rgb.shape)
    return Image.fromarray(np.clip(rgb + 0.5, 0, 255).astype(np.uint8), "RGB")


# --- 20 mandel ---------------------------------------------------------------

# no fastmath here: |dz| overflows to inf for slow escapers deep in the valley,
# and fastmath is allowed to assume that never happens -- it painted them NaN-black.
@njit(parallel=True)
def _mandel(half, h, ss, re0, re1, imc, maxit, hue_lut, out):
    step = (re1 - re0) / half       # signed: the view may run right to left
    scale = abs(step)               # complex units per pixel
    n_lut = hue_lut.shape[0]
    for py in prange(h):
        for px in range(half):
            r = g = b = 0.0
            for sy in range(ss):
                for sx in range(ss):
                    u = px + (sx + 0.5) / ss
                    v = py + (sy + 0.5) / ss
                    cr = re0 + u * step
                    ci = imc + (h / 2 - v) * scale
                    # main cardioid and period-2 bulb: known interior, skip
                    q = (cr - 0.25) ** 2 + ci * ci
                    inside = q * (q + cr - 0.25) <= 0.25 * ci * ci or \
                        (cr + 1) ** 2 + ci * ci <= 0.0625
                    zr = zi = 0.0; dr = di = 0.0
                    it = 0
                    m2 = 0.0
                    if not inside:
                        while it < maxit:
                            # dz = 2 z dz + 1  (for the distance estimate)
                            ndr = 2 * (zr * dr - zi * di) + 1
                            di = 2 * (zr * di + zi * dr)
                            dr = ndr
                            zr, zi = zr * zr - zi * zi + cr, 2 * zr * zi + ci
                            m2 = zr * zr + zi * zi
                            if m2 > 1e8:
                                break
                            it += 1
                    if inside or it >= maxit:
                        cr_, cg_, cb_ = 29.0, 32.0, 33.0      # bg0_h interior
                    else:
                        mz = math.sqrt(m2)
                        # an instant escaper gives nu < 0, and log(nu + 1) of that is NaN
                        nu = max(it + 1 - math.log2(math.log(mz)), 0.0)
                        dz = math.sqrt(dr * dr + di * di)
                        if math.isfinite(dz) and dz > 0:
                            dpx = mz * math.log(mz) / dz / scale   # distance in px
                        else:
                            dpx = 0.0                              # overflowed: on the boundary
                        # filament brightness: 1 on the boundary, gone by ~60 px
                        line = 1 - math.log(dpx + 1) / math.log(60.0)
                        if line < 0: line = 0.0
                        line = line ** 1.6
                        t = math.log(nu + 1) * 0.55
                        t = t - math.floor(t)
                        k = int(t * (n_lut - 1))
                        hr = hue_lut[k, 0]; hg = hue_lut[k, 1]; hb = hue_lut[k, 2]
                        a = 0.08 + 0.62 * line
                        cr_ = 40 * (1 - a) + hr * a
                        cg_ = 40 * (1 - a) + hg * a
                        cb_ = 40 * (1 - a) + hb * a
                        # engraving in the empty valley: equipotential arcs (level
                        # sets of the smooth count, log-spaced so they stay even
                        # across the zoom) and a faint binary decomposition, which
                        # shades every other cell between external rays
                        L = math.log2(nu + 1) * 9.0
                        f = L - math.floor(L)
                        arc = 1 - abs(f - 0.5) * 2
                        arc = arc ** 14 * 0.16 * (1 - line)
                        cr_ = cr_ * (1 - arc) + 213 * arc
                        cg_ = cg_ * (1 - arc) + 196 * arc
                        cb_ = cb_ * (1 - arc) + 161 * arc
                        if zi > 0:
                            cr_ *= 0.94; cg_ *= 0.94; cb_ *= 0.94
                        if dpx < 1.2:                          # hairline highlight
                            w = (1.2 - dpx) / 1.2 * 0.30
                            cr_ = cr_ * (1 - w) + 235 * w
                            cg_ = cg_ * (1 - w) + 219 * w
                            cb_ = cb_ * (1 - w) + 178 * w
                    r += cr_; g += cg_; b += cb_
            n = ss * ss
            out[py, px, 0] = r / n; out[py, px, 1] = g / n; out[py, px, 2] = b / n


def mandel(w, h, preview):
    half = (w + 1) // 2
    hue = lut([BLUE, AQUA, AQUA2, GREEN2, YEL2, ORNG2, RED2, PURP2, BLUE2, BLUE])
    out = np.zeros((h, half, 3))
    # u=0 (the seam, the image centre) is deep inside the main cardioid; moving
    # out crosses its boundary, the seahorse valley, then the period-2 bulb.
    # Fixed horizontal span, so every size shows the same structures and the
    # taller screens simply see more of the valley above and below.
    _mandel(half, h, 1 if preview else 3, -0.703, -0.792, 0.104, 4000, hue, out)
    rgb = np.concatenate([out[:, ::-1], out[:, w % 2:]], axis=1)[:, :w]
    return finish(rgb, 20)


# --- 21 coral ----------------------------------------------------------------

@njit(parallel=True, fastmath=True)
def _gs_steps(u, v, u2, v2, F, K, steps):
    h, w = u.shape
    for _ in range(steps):
        for y in prange(h):
            ym = y - 1 if y > 0 else h - 1
            yp = y + 1 if y < h - 1 else 0
            for x in range(w):
                xm = x - 1 if x > 0 else 0          # reflecting side edges
                xp = x + 1 if x < w - 1 else w - 1
                lu = (0.2 * (u[ym, x] + u[yp, x] + u[y, xm] + u[y, xp])
                      + 0.05 * (u[ym, xm] + u[ym, xp] + u[yp, xm] + u[yp, xp])
                      - u[y, x])
                lv = (0.2 * (v[ym, x] + v[yp, x] + v[y, xm] + v[y, xp])
                      + 0.05 * (v[ym, xm] + v[ym, xp] + v[yp, xm] + v[yp, xp])
                      - v[y, x])
                uvv = u[y, x] * v[y, x] * v[y, x]
                u2[y, x] = u[y, x] + (1.0 * lu - uvv + F[y, x] * (1 - u[y, x]))
                v2[y, x] = v[y, x] + (0.5 * lv + uvv - (F[y, x] + K[y, x]) * v[y, x])
        u, u2 = u2, u
        v, v2 = v2, v
    return u, v


def coral(w, h, preview):
    down = 4 if preview else 2                  # simulate at half size, shade at full
    gw, gh = w // down, h // down
    yy, xx = np.mgrid[0:gh, 0:gw]
    # distance from the centre column, 0 there, 1 at the side edges; corners a bit more
    d = np.abs(xx / (gw - 1) - 0.5) * 2
    d = np.clip(d + 0.18 * (np.abs(yy / (gh - 1) - 0.5) * 2) ** 2, 0, 1)
    s = smoothstep(0.22, 0.95, d)
    # (F, k): dead (v washes out) -> mitosis spots -> coral labyrinth
    F = (0.0300 + s * (0.0545 - 0.0300)).astype(np.float64)
    K = (0.0690 + s * (0.0620 - 0.0690)).astype(np.float64)
    rng = np.random.default_rng(21)
    u = np.ones((gh, gw)); v = np.zeros((gh, gw))
    for _ in range(int(gw * gh / 900)):         # scattered square seeds everywhere
        cx, cy, r = rng.integers(0, gw), rng.integers(0, gh), rng.integers(2, 6)
        u[max(cy - r, 0):cy + r, max(cx - r, 0):cx + r] = 0.5
        v[max(cy - r, 0):cy + r, max(cx - r, 0):cx + r] = 0.25 + 0.1 * rng.random()
    u2, v2 = np.empty_like(u), np.empty_like(v)
    u, v = _gs_steps(u, v, u2, v2, F, K, 2500 if preview else 14000)

    vf = Image.fromarray(v.astype(np.float32), "F").resize((w, h), Image.BICUBIC)
    v = np.asarray(vf, dtype=np.float64)
    v = np.clip(v / 0.35, 0, 1)
    # emboss: light from the upper left over the v height field
    gy, gx = np.gradient(v * (14.0 / down))
    nz = 1 / np.sqrt(gx * gx + gy * gy + 1)
    light = np.clip((-gx * -0.6 + -gy * -0.6 + nz * 0.53) * nz, 0, 1)
    spec = np.clip(light, 0, 1) ** 24
    yyF, xxF = np.mgrid[0:h, 0:w]
    dF = np.abs(xxF / (w - 1) - 0.5) * 2
    # colour drifts along the edge distance: aqua deep inside, yellow at the rims
    body = lut([BG2, BLUE, AQUA, AQUA2, GREEN2, YEL, YEL2], 512)
    t = np.clip(v * 0.45 + 0.55 * smoothstep(0.25, 1.0, dF), 0, 1)
    col = body[(t * 511).astype(int)]
    a = smoothstep(0.08, 0.55, v)[..., None]
    shade = (0.45 + 0.75 * light)[..., None]
    rgb = BG * (1 - a) + col * shade * a + FG * (spec * a[..., 0] * 0.35)[..., None]
    # a thin cream outline where the coral surface crosses v = 0.3
    edge = np.exp(-((v - 0.3) / 0.025) ** 2) * 0.25
    rgb = rgb * (1 - edge[..., None]) + FG2 * edge[..., None]
    return finish(rgb, 21)


# --- 22 silk -----------------------------------------------------------------

@njit(parallel=True, fastmath=True)
def _clifford(a, b, c, d, n_chains, n_iter, w, h, cx, cy, sc, flip, dens, spd):
    for ch in prange(n_chains):
        x = 0.1 + 0.013 * ch
        y = -0.2 + 0.007 * ch
        for i in range(n_iter):
            nx = math.sin(a * y) + c * math.cos(a * x)
            ny = math.sin(b * x) + d * math.cos(b * y)
            s = math.sqrt((nx - x) ** 2 + (ny - y) ** 2)
            x, y = nx, ny
            if i < 100:
                continue
            px = cx + flip * x * sc
            py = cy - y * sc
            ix = int(px); iy = int(py)
            if 0 <= ix < w and 0 <= iy < h:
                # races between chains lose a few counts; invisible at this density
                dens[iy, ix] += 1.0
                spd[iy, ix] += s


def silk(w, h, preview):
    dens = np.zeros((h, w)); spd = np.zeros((h, w))
    n_iter = 4_000_000 if preview else 100_000_000
    # |y| <= 1.7, so a little crops off top and bottom; |x| <= 2, and the width
    # cap keeps the two from meeting in the middle of a 16:9 or 16:10 screen
    sc = min(h * 0.29, w * 0.12)
    for (a, b, c, d), cx, flip in (((-1.4, 1.6, 1.0, 0.7), w * 0.10, 1.0),
                                   ((-1.4, 1.6, 1.0, 0.7), w * 0.90, -1.0)):
        _clifford(a, b, c, d, 24, n_iter // 24 * 12, w, h, cx, h / 2, sc, flip, dens, spd)
    m = dens > 0
    mean_s = np.zeros_like(dens); mean_s[m] = spd[m] / dens[m]
    lo, hi = np.percentile(mean_s[m], [5, 95])
    hue = np.clip((mean_s - lo) / (hi - lo), 0, 1)
    ld = np.log1p(dens)
    ld = ld / np.percentile(ld[m], 99.7)
    bright = np.clip(ld, 0, 1) ** 1.1
    slow = lut([BLUE, BLUE2, AQUA2, FG], 512)     # slow, dense folds: cool
    fast = lut([PURP, RED2, ORNG2, YEL2], 512)    # fast, thin sweeps: warm
    k = (bright * 511).astype(int)
    col = slow[k] * (1 - hue[..., None]) + fast[k] * hue[..., None]
    rgb = BG * (1 - bright[..., None]) + col * bright[..., None]
    return finish(rgb, 22)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pieces", default=",".join(PIECES))
    ap.add_argument("--sizes", default=",".join(SIZES))
    ap.add_argument("--out", default=str(pathlib.Path.home() / "Pictures" / "wallpapers"))
    ap.add_argument("--preview", action="store_true",
                    help="quarter quality, quick look at the composition")
    args = ap.parse_args()
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    fn = {"mandel": mandel, "coral": coral, "silk": silk}
    for piece in args.pieces.split(","):
        for size in args.sizes.split(","):
            w, h = SIZES[size]
            t = time.time()
            img = fn[piece](w, h, args.preview)
            dest = out / f"gruvbox-dark-{PIECES[piece]}-{size}{'-preview' if args.preview else ''}.png"
            img.save(dest, optimize=False)
            print(f"   {dest}  {time.time() - t:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
