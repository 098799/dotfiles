import sys

import toml
import yaml


with open("dotfiles/.alacritty.toml", "r") as infile:
    main_config = toml.load(infile)


# theme_type = "solarized"
# theme_type = "selenized"
theme_type = sys.argv[2]


with open(f"dotfiles/alacritty/{theme_type}-{sys.argv[1]}.yml", "r") as infile:
    color_config = yaml.safe_load(infile)


applied_config = main_config | color_config


with open("dotfiles/.alacritty.toml", "w") as outfile:
    toml.dump(applied_config, outfile)
