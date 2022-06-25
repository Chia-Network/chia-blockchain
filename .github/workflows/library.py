import json
import pathlib
import sys

import yaml

here = pathlib.Path(__file__).parent


def main() -> int:
    with here.joinpath("library-data.yml").open() as file:
        loaded = yaml.safe_load(file)
    print(json.dumps(loaded, indent=4))

    return 0


sys.exit(main())
