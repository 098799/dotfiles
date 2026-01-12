import os
import sys

import toml

alacritty_toml = os.path.expanduser("~/dotfiles/alacritty-pkg/.alacritty.toml")

with open(alacritty_toml, "r") as infile:
    main_config = toml.load(infile)

main_config["font"]["size"] = int(sys.argv[1])

with open(alacritty_toml, "w") as outfile:
    toml.dump(main_config, outfile)
