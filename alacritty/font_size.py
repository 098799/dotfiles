import sys

import yaml


with open("dotfiles/.alacritty.yml", "r") as infile:
    main_config = yaml.safe_load(infile)


main_config["font"]["size"] = int(sys.argv[1])


with open("dotfiles/.alacritty.yml", "w") as outfile:
    yaml.dump(main_config, outfile)
