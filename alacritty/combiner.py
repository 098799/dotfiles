import os
import sys

import toml
import yaml

dotfiles_dir = os.path.expanduser("~/dotfiles")
alacritty_toml = f"{dotfiles_dir}/alacritty-pkg/.alacritty.toml"

with open(alacritty_toml, "r") as infile:
    main_config = toml.load(infile)


# theme_type = "solarized"
# theme_type = "selenized"
theme_type = sys.argv[2] if len(sys.argv) > 2 else "selenized"


with open(f"{dotfiles_dir}/alacritty/{theme_type}-{sys.argv[1]}.yml", "r") as infile:
    color_config = yaml.safe_load(infile)

applied_config = main_config | color_config


with open(alacritty_toml, "w") as outfile:
    toml.dump(applied_config, outfile)
