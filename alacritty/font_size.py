import sys

import toml
import yaml


# with open("dotfiles/.alacritty.yml", "r") as infile:
#     main_config = yaml.safe_load(infile)
with open("dotfiles/.alacritty.toml", "r") as infile:
    main_config = toml.load(infile)


main_config["font"]["size"] = int(sys.argv[1])


# with open("dotfiles/.alacritty.yml", "w") as outfile:
#     yaml.dump(main_config, outfile)
with open("dotfiles/.alacritty.toml", "w") as outfile:
    toml.dump(main_config, outfile)
