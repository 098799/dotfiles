# /// script
# requires-python = ">=3.11"
# dependencies = ["tomli_w", "pyyaml"]
# ///
import os
import sys
import tomllib

import tomli_w
import yaml

dotfiles_dir = os.path.expanduser("~/dotfiles")
alacritty_toml = f"{dotfiles_dir}/alacritty-pkg/.config/alacritty/alacritty.toml"

with open(alacritty_toml, "rb") as infile:
    main_config = tomllib.load(infile)

theme_type = sys.argv[2] if len(sys.argv) > 2 else "selenized"

with open(f"{dotfiles_dir}/alacritty/{theme_type}-{sys.argv[1]}.yml", "r") as infile:
    color_config = yaml.safe_load(infile)

applied_config = main_config | color_config

with open(alacritty_toml, "wb") as outfile:
    tomli_w.dump(applied_config, outfile)
