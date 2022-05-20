import copy
from pathlib import Path

import yaml


here = Path(__file__).parent


def main():
    source_path = here.joinpath("workflow.yml")
    output_path = here.parent.joinpath(".github", "workflows", "test.yml")

    with source_path.open() as file:
        source = yaml.safe_load(stream=file)

    output = copy.deepcopy(source)
    del output["jobs"]["test"]

    os_matrix = source["jobs"]["test"]["strategy"]["matrix"]["os"]

    for os_entry in os_matrix:
        d = copy.deepcopy(source["jobs"]["test"])
        d["strategy"]["matrix"]["os"] = [os_entry]
        output["jobs"][f"test_{os_entry['matrix']}"] = d

    with output_path.open("w") as file:
        yaml.safe_dump(data=output, stream=file)


main()
