import io
import os
import pathlib
import sys
from typing import TextIO

import click
import yaml

start_tag = "# START GENERATED"
end_tag = "# END GENERATED"


@click.command()
@click.option("--pre-commit-yaml", type=click.File(mode="w", encoding="utf-8", atomic=True), required=True)
@click.option("--fail-on-change/--no-fail-on-change", help="Return a non-zero exit code if the file is modified.")
def main(pre_commit_yaml: TextIO, fail_on_change: bool) -> None:
    # for importing setup, not pretty
    sys.path.insert(0, os.getcwd())
    import setup

    generated_anchors_dict = {
        "generated_anchors": {
            "mypy_dependencies": [
                *setup.dependencies,
                *setup.dev_dependencies,
            ],
        },
    }

    anchor_keys = ["mypy_dependencies"]

    generation_string_io = io.StringIO()
    yaml.safe_dump(data=generated_anchors_dict, stream=generation_string_io)

    # It would be really nice to find a clean way to do this within the PyYAML library
    # instead of hacking it on in text.
    generated_anchors_lines = []
    generation_string_io.seek(0)
    for line in generation_string_io:
        line = line.rstrip()
        maybe_anchor_key = line.strip().rstrip(":")
        if maybe_anchor_key in anchor_keys:
            line = f"{line} &{maybe_anchor_key}"

        generated_anchors_lines.append(line)

    generated_anchors_string = "\n".join(generated_anchors_lines)

    pre_commit_path = pathlib.Path(pre_commit_yaml.name)

    output_string_io = io.StringIO()

    input_string = pre_commit_path.read_text(encoding="utf-8")
    input_lines_iter = iter(input_string.splitlines(keepends=True))

    for line in input_lines_iter:
        if line.rstrip() != start_tag:
            output_string_io.write(line)
        else:
            output_string_io.write(start_tag + "\n")
            output_string_io.write("# This section is generated, do not edit.\n")
            output_string_io.write(generated_anchors_string + "\n")
            output_string_io.write(end_tag + "\n")

            for generated_line in input_lines_iter:
                if generated_line.rstrip() == end_tag:
                    break

    output_string = output_string_io.getvalue().strip() + "\n"

    pre_commit_yaml.write(output_string)

    if fail_on_change:
        if output_string != input_string:
            sys.exit(1)


main()  # pylint: disable=no-value-for-parameter
