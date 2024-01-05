import csv
import datetime as dt
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import *
from datetime import date
from functools import partial
from inspect import stack
from itertools import *
from math import *
from unittest.mock import patch
from uuid import uuid4


try:
    import pandas as pd
except ImportError:
    pass


try:
    import numpy as np
except ImportError:
    pass


try:
    import streamlit as st
except ImportError:
    pass


try:
    import requests
except ImportError:
    pass


try:
    import readline

    readline.parse_and_bind("tab: complete")
except ImportError:
    pass


try:
    from rich import pretty

    pretty.install()

except ImportError:
    pass


# I wish Python had a Path literal but I can get pretty close with this:
# Tiis let me to p/"path/to/file" to get a Path object
from pathlib import Path


try:

    class PathLiteral:
        def __truediv__(self, other):
            try:
                return Path(other.format(**stack()[1][0].f_globals))
            except KeyError as e:
                raise NameError("name {e} is not defined".format(e=e))

        def __call__(self, string):
            return self / string

    p = PathLiteral()
except ImportError:
    pass


# I'm lazy
def now():
    return dt.now()


def today():
    return date.today()


try:
    from rich.pretty import pprint
except ImportError:
    pass
