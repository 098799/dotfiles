import sys

import yaml


with open("dotfiles/.alacritty.yml", "r") as infile:
    main_config = yaml.safe_load(infile)


with open(f"dotfiles/alacritty/solarized-{sys.argv[1]}.yml", "r") as infile:
    color_config = yaml.safe_load(infile)


applied_config = main_config | color_config


with open("dotfiles/.alacritty.yml", "w") as outfile:
    yaml.dump(applied_config, outfile)
