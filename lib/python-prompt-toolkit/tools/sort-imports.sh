#/bin/bash

# Use this script to sort the imports. Call it from the root of the repository,
# like:
#     ./tools/sort-imports.sh prompt_toolkit
#     ./tools/sort-imports.sh examples
# If `isort` is not installed. Run `pip install isort`.
isort -m 3 -tc -rc $@
