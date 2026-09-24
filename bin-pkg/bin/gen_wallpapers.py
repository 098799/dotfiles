#!/usr/bin/env python
"""Generate themed wallpapers with Gemini.

Usage: gen_wallpapers.py [--ultrawide|--wide] [--styles 6,7,8] [--themes gruvbox-dark,...]

Writes ~/Pictures/wallpapers/<palette>-<mode>-<N>.png at the target resolution.
API key comes from ~/haircut-studio/backend/.env (GEMINI_API_KEY).
Run with ~/haircut-studio/backend/.venv/bin/python.
"""
import argparse, os, pathlib, subprocess, sys, tempfile, time

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
}

COMMON = (
    "Desktop wallpaper, {w}x{h} pixels, ultra-wide {ar} aspect ratio, edge to edge "
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


def load_key():
    for line in ENV.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY"):
            return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("GEMINI_API_KEY not found in " + str(ENV))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ultrawide", action="store_true", default=True)
    ap.add_argument("--wide", dest="ultrawide", action="store_false")
    ap.add_argument("--styles", default="6,7,8,9")
    ap.add_argument("--themes", default=",".join(PALETTES))
    ap.add_argument("--suffix", default="")
    ap.add_argument("--model", default="")
    args = ap.parse_args()

    if args.ultrawide:
        w, h, ar = 3440, 1440, "21:9"
    else:
        w, h, ar = 2560, 1440, "16:9"

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=load_key())
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="wall-"))

    for theme in args.themes.split(","):
        p = PALETTES[theme]
        for n in [int(s) for s in args.styles.split(",")]:
            name, style = STYLES[n]
            dest = OUT / f"{theme}-{n}{args.suffix}.png"
            prompt = COMMON.format(w=w, h=h, ar=ar, style=style, **p)
            print(f"-> {dest.name}  ({name})", file=sys.stderr)
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
            raw = tmp / f"{theme}-{n}.raw.png"
            raw.write_bytes(blob)
            subprocess.run(
                ["magick", str(raw), "-filter", "Lanczos",
                 "-resize", f"{w}x{h}^", "-gravity", "center",
                 "-extent", f"{w}x{h}", str(dest)], check=True)
            print(f"   {dest}", file=sys.stderr)
    print(OUT)


if __name__ == "__main__":
    main()
