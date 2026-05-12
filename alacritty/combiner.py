# /// script
# requires-python = ">=3.11"
# dependencies = ["tomli_w", "pyyaml"]
# ///
import os
import sys

import tomli_w
import yaml

dotfiles_dir = os.path.expanduser("~/dotfiles")
overlay_path = os.path.expanduser("~/.config/alacritty/active-palette.toml")

mode = sys.argv[1]
palette = sys.argv[2] if len(sys.argv) > 2 else "selenized"

with open(f"{dotfiles_dir}/alacritty/{palette}-{mode}.yml", "r") as infile:
    color_config = yaml.safe_load(infile)

os.makedirs(os.path.dirname(overlay_path), exist_ok=True)
with open(overlay_path, "wb") as outfile:
    tomli_w.dump(color_config, outfile)
