#!/usr/bin/env python
"""Generate themed wallpapers with Gemini.

Usage: gen_wallpapers.py [--sizes uw,wide,laptop] [--styles 10,11] [--themes gruvbox-dark,...]

Writes ~/Pictures/wallpapers/<palette>-<mode>-<N>-<size>.png, one file per size.
`wallpaper-pick` globs <palette>-<mode>-* and keeps the closest aspect, so each
style needs a file per screen shape: uw = 3440x1440 (21:9 DisplayPort),
wide = 2560x1440 (16:9 HDMI / work screen), laptop = 2560x1600 (16:10 eDP panel).
Gemini has no 16:10 ratio, so laptop is generated at 3:2 and cropped top and
bottom -- the detail sits at the left and right edges, which a crop keeps.

Gemini does not hold to the palette (the ukiyo-e waves came back navy), so every
image is palette-locked after the resize: dithered remap onto ramps of the
palette colours, blended back over the original at --lock percent so gradients
stay smooth. `--relock FILE...` applies only that step to existing files.

`--provider gpt` uses OpenAI's gpt-image-2.5-sunburst instead (~$0.21 an image,
key OPENAI_API_KEY from the environment or ~/bin/.env; the one in p340's
~/imagine/.env is known to have Sunburst access). It takes any WxH in multiples
of 16 up to 3840 on the long edge, so it renders every size natively -- no
upscale, no 3:2-and-crop -- and on 1 Oct 2026 it beat Gemini on every style it
was tried on (Gemini put frames and letterbox bars on the 16:9/16:10 ones).
Files get a `-gpt` suffix, so both providers can sit in the rotation.
API key comes from ~/haircut-studio/backend/.env (GEMINI_API_KEY).
Run with ~/haircut-studio/backend/.venv/bin/python.
"""
import argparse, base64, json, os, pathlib, re, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HOME = pathlib.Path.home()
OUT = HOME / "Pictures" / "wallpapers"
ENV = HOME / "haircut-studio" / "backend" / ".env"
MODELS = ["gemini-3-pro-image", "gemini-3.1-flash-image", "gemini-3-pro-image-preview"]

PALETTES = {
    "gruvbox-dark": dict(
        bg="#282828", fg="#ebdbb2",
        accents="#cc241d red, #98971a green, #d79921 yellow, #458588 blue, "
                "#b16286 magenta, #689d6a aqua, #fb4934 bright red, #fabd2f bright yellow, "
                "#83a598 bright blue, #8ec07c bright aqua, #928374 grey",
        mood="warm retro-terminal dusk, low saturation, slightly grainy like old film"),
    "gruvbox-light": dict(
        bg="#fbf1c7", fg="#3c3836",
        accents="#9d0006 deep red, #79740e olive, #b57614 ochre, #076678 teal-blue, "
                "#8f3f71 plum, #427b58 pine, #7c6f64 warm grey",
        mood="warm cream paper, ink-and-wash, soft aged-parchment light"),
    "selenized-dark": dict(
        bg="#103c48", fg="#adbcbc",
        accents="#fa5750 coral red, #75b938 green, #dbb32d amber, #4695f7 blue, "
                "#f275be pink, #41c7b9 turquoise, #ed8649 orange, #2d5b69 slate",
        mood="deep teal underwater dusk, cool and calm, luminous accents"),
    "selenized-light": dict(
        bg="#fbf3db", fg="#53676d",
        accents="#d2212d red, #489100 green, #ad8900 gold, #0072d4 blue, "
                "#ca4898 magenta, #009c8f teal, #d5cdb6 sand",
        mood="pale sand paper, clean daylight, crisp printed-poster feel"),
}

STYLES = {
    6: ("escher-tessellation",
        "An M.C. Escher style regular division of the plane: a single family of "
        "interlocking creature silhouettes (birds becoming fish becoming birds) "
        "tiling the surface with no gaps. The tessellation is dense and crisp along "
        "the far left and far right thirds and dissolves toward a plain, almost empty "
        "field across the middle."),
    7: ("escher-architecture",
        "An M.C. Escher style impossible architecture: pale stone staircases, arches "
        "and balustrades that loop back on themselves, drawn as a clean lithograph "
        "with flat shading. Heavy structure at the left and right edges, opening into "
        "a wide plain sky across the centre."),
    8: ("escher-metamorphosis",
        "An M.C. Escher metamorphosis band running the full width: a grid of simple "
        "cubes at the far left gradually transforming into hexagons, then into "
        "honeycomb, then into insects, then back into abstract blocks at the far "
        "right. The transformation is most detailed at both edges and passes through "
        "its calmest, sparsest stage in the middle."),
    9: ("topographic-flow",
        "Fine topographic contour lines and flow-field streamlines, like a hand-drawn "
        "survey map. Ridges, whorls and dense line clusters crowd the left and right "
        "edges and the corners; the centre relaxes into wide, near-flat spacing with "
        "very few lines."),
    # 1 Oct 2026 cycle (gruvbox-dark only): free subjects, same palette and
    # quiet-centre rule. 6-9 above are retired to wallpapers/retired/2026-10-01/.
    10: ("ukiyo-e-waves",
        "A Japanese ukiyo-e woodblock print: towering curling waves with claw-like "
        "foam crests rise from the far left and far right edges, a small distant "
        "snow-capped volcano low in one corner, tiny fishing boats in the troughs. "
        "Visible woodgrain texture and flat colour areas. The water is printed in the "
        "palette's muted teal-blue and aqua, never navy or ultramarine. The centre is a "
        "calm, empty, softly graded evening sky over still water."),
    11: ("haeckel-plates",
        "A scientific engraving plate in the manner of Ernst Haeckel's Art Forms in "
        "Nature: radially symmetric radiolarians, jellyfish with trailing tentacles, "
        "diatoms and siphonophores, finely hatched, clustered densely along the left "
        "and right edges and in the corners, floating on a dark plate. The centre is "
        "open dark water with only a few tiny drifting specks."),
    12: ("alpine-poster",
        "A vintage Swiss railway travel poster as a flat-colour stone lithograph, with "
        "no lettering at all, seen as an ordinary upright landscape: the ground is at the "
        "bottom, the sky is at the top, nothing is mirrored, inverted or hanging from "
        "the top edge. Jagged alpine peaks with snow fields rise from the bottom-left "
        "and bottom-right, dark pine forests climb their lower slopes, a tiny train "
        "crosses a stone viaduct in the lower-left corner, a chalet with one lit window "
        "sits on a slope at the lower right. Across the centre a wide, calm dusk sky "
        "above a still lake, almost featureless."),
    13: ("celestial-orrery",
        "An antique celestial engraving: a brass orrery with nested unmarked rings and "
        "small planet spheres, an armillary sphere and gear trains, rendered as fine "
        "copperplate line work, clustered at the far left and far right. Thin dotted "
        "orbital ellipses and faint star points trail inward and fade out; the centre "
        "is dark empty sky. No numerals, no zodiac glyphs, no scale markings."),
    14: ("retro-space",
        "A 1970s retro-futurist space concept painting with gouache texture: a huge "
        "ringed gas giant rising out of the lower-left corner, two small moons, a "
        "spindly wheel-shaped space station silhouette near the right edge with a "
        "faint glow from its windows, sparse stars. The middle of the image is deep, "
        "nearly empty space."),
    15: ("art-deco-sunburst",
        "Art Deco ornament in thin gold metallic line work on a dark ground: stepped "
        "ziggurat forms, fan and sunburst motifs and chevron bands rising from the "
        "left and right edges and the corners, like the doors of a 1930s lift lobby. "
        "Precise, symmetric, elegant; the centre is a plain dark field with only one "
        "very faint fine line crossing it."),
}

COMMON = (
    "Desktop wallpaper, {w}x{h} pixels, {ar} aspect ratio, edge to edge "
    "artwork with no borders, frame, margin, watermark, text, letters, numbers, "
    "signature, people, faces or logos.\n"
    "Strict colour palette, use these colours only: background {bg}; primary line and "
    "shape colour {fg}; accents {accents}. Do not introduce any other hue.\n"
    "Mood: {mood}.\n"
    "Composition rule, this is critical: the horizontal middle band of the image must "
    "stay visually quiet, low contrast and close to the background colour, because "
    "terminal windows sit there and text must stay readable. Put all the detail, "
    "contrast and complexity into the left and right thirds and into the four corners, "
    "and let it fade smoothly toward the centre.\n"
    "Subject: {style}"
)


def lock_palette_image(p, path):
    """Write a 1-pixel-high strip of every colour the lock may snap to.

    Flat palette colours alone posterise gradients, so each accent is also
    ramped from the background up to full strength and on toward the
    foreground, and the background is ramped to the foreground in 16 steps.
    """
    hexes = [p["bg"], p["fg"]] + re.findall(r"#[0-9a-fA-F]{6}", p["accents"])
    rgb = lambda c: [int(c[i:i + 2], 16) for i in (1, 3, 5)]
    mix = lambda a, b, t: "#%02x%02x%02x" % tuple(
        round(x * (1 - t) + y * t) for x, y in zip(rgb(a), rgb(b)))
    cols = [mix(p["bg"], p["fg"], i / 16) for i in range(17)]
    for a in hexes[2:]:
        cols += [mix(p["bg"], a, i / 8) for i in range(1, 9)]
        cols += [mix(a, p["fg"], i / 8) for i in (2, 4)]
    cols = list(dict.fromkeys(cols))
    subprocess.run(["magick", *[f"xc:{c}" for c in cols], "+append", str(path)],
                   check=True)


def palette_lock(src, dest, pal_png, strength):
    subprocess.run(
        ["magick", str(src), "(", "+clone", "-dither", "FloydSteinberg",
         "-remap", str(pal_png), ")", "-compose", "blend",
         "-define", f"compose:args={strength}", "-composite", str(dest)],
        check=True)


# size tag -> (width, height, ratio Gemini is asked for)
SIZES = {
    "uw": (3440, 1440, "21:9"),
    "wide": (2560, 1440, "16:9"),
    "laptop": (2560, 1600, "3:2"),
}


def load_key():
    for line in ENV.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY"):
            return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("GEMINI_API_KEY not found in " + str(ENV))


def load_openai_key():
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    for line in (HOME / "bin" / ".env").read_text().splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("OPENAI_API_KEY not set and not in ~/bin/.env")


def gpt_image(key, prompt, w, h):
    body = json.dumps(dict(model="gpt-image-2.5-sunburst", prompt=prompt,
                           size=f"{w}x{h}", n=1, quality="high", moderation="low",
                           output_format="png")).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations", body,
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            resp = json.load(urllib.request.urlopen(req, timeout=900))
            return base64.b64decode(resp["data"][0]["b64_json"])
        except urllib.error.HTTPError as e:
            print(f"   gpt failed (HTTP {e.code} {e.read()[:200]!r}); retry",
                  file=sys.stderr)
            time.sleep(20 * (attempt + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default=",".join(SIZES))
    ap.add_argument("--styles", default="10,11,12,13,14,15")
    ap.add_argument("--themes", default="gruvbox-dark")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--provider", choices=["gemini", "gpt"], default="gemini")
    ap.add_argument("--out", default=str(OUT),
                    help="stage somewhere else first, review, then move in")
    ap.add_argument("--lock", type=int, default=75,
                    help="palette-lock strength in percent, 0 turns it off")
    ap.add_argument("--relock", nargs="+", metavar="FILE",
                    help="only palette-lock these files in place (theme from --themes)")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="wall-"))
    pals = {}
    for t in args.themes.split(","):
        pals[t] = tmp / f"{t}.pal.png"
        lock_palette_image(PALETTES[t], pals[t])

    if args.relock:
        theme = args.themes.split(",")[0]
        for f in args.relock:
            palette_lock(f, f, pals[theme], args.lock)
            print(f"   locked {f}", file=sys.stderr)
        return

    if args.provider == "gpt":
        openai_key = load_openai_key()
    else:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=load_key())
    out.mkdir(parents=True, exist_ok=True)

    jobs = [(t, n, z) for t in args.themes.split(",")
            for n in [int(s) for s in args.styles.split(",")]
            for z in args.sizes.split(",")]
    for theme, n, size in jobs:
        p = PALETTES[theme]
        w, h, ar = SIZES[size]
        name, style = STYLES[n]
        tag = "-gpt" if args.provider == "gpt" else ""
        dest = out / f"{theme}-{n}-{size}{tag}{args.suffix}.png"
        if args.provider == "gpt":
            ar = f"{w}:{h}"                 # native size: no 3:2 stand-in to crop
        prompt = COMMON.format(w=w, h=h, ar=ar, style=style, **p)
        print(f"-> {dest.name}  ({name})", file=sys.stderr)
        if args.provider == "gpt":
            blob = gpt_image(openai_key, prompt, w, h)
            if not blob:
                print("   GIVING UP on this image", file=sys.stderr)
                continue
            dest.write_bytes(blob)
            if args.lock:
                palette_lock(dest, dest, pals[theme], args.lock)
            print(f"   {dest}", file=sys.stderr)
            continue
        models = [args.model] if args.model else MODELS
        resp = None
        for attempt, model in enumerate(models * 3):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                        image_config=types.ImageConfig(
                            aspect_ratio=ar, image_size="4K"),
                    ),
                )
                break
            except Exception as e:
                wait = 15 * (attempt // len(models) + 1)
                print(f"   {model} failed ({str(e)[:90]}); next in {wait}s",
                      file=sys.stderr)
                time.sleep(wait)
        if resp is None:
            print("   GIVING UP on this image", file=sys.stderr)
            continue
        blob = None
        for part in resp.candidates[0].content.parts:
            if getattr(part, "inline_data", None):
                blob = part.inline_data.data
                break
        if not blob:
            print("   no image in response", file=sys.stderr)
            continue
        raw = tmp / f"{theme}-{n}-{size}.raw.png"
        raw.write_bytes(blob)
        subprocess.run(
            ["magick", str(raw), "-filter", "Lanczos",
             "-resize", f"{w}x{h}^", "-gravity", "center",
             "-extent", f"{w}x{h}", str(dest)], check=True)
        if args.lock:
            palette_lock(dest, dest, pals[theme], args.lock)
        print(f"   {dest}", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    main()
