#!/bin/bash

pip install hatch && hatch env create || exit 1

# VSCode doesn't support Hatch.
# The path to the Python interpretter must be statically known, but Hatch generates a path.
# You can't use a wrapper script because VSCode will actually look for other files relative to the
# wrapper instead of asking the wrapped Python what configuration to use.
mkdir ~/.env && ln -s "$(hatch env find)" ~/.env/default || exit 1
