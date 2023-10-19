from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, TextIO, Tuple, final

import click
import lxml.etree


@final
@dataclass(frozen=True, order=True)
class Result:
    path: Path
    label: str
    line: int = field(compare=False)
    durations: List[float] = field(compare=False)

    def marshal(self) -> Dict[str, Any]:
        return {
            "path": self.path.as_posix(),
            "label": self.label,
            "duration": {
                "all": self.durations,
                "min": min(self.durations),
                "max": max(self.durations),
                "mean": mean(self.durations),
            },
        }

    def link(self, prefix: str, line_separator: str) -> str:
        return f"{prefix}{self.path.as_posix()}{line_separator}{self.line}"


@click.command
@click.option(
    "--xml",
    "xml_file",
    required=True,
    type=click.File(),
    help="The benchmarks JUnit XML results file",
)
@click.option("--link-prefix", default="", help="Prefix for output links such as for web links instead of IDE links")
@click.option(
    "--link-line-separator",
    default=":",
    help="Such as : for local links and #L on GitHub",
)
def main(xml_file: TextIO, link_prefix: str, link_line_separator: str) -> None:
    tree = lxml.etree.parse(xml_file)
    root = tree.getroot()
    benchmarks = root.find("testsuite[@name='benchmarks']")

    raw_durations: defaultdict[Tuple[str, ...], List[Result]] = defaultdict(list)

    for case in benchmarks:
        path = (
            *case.get("classname").split("."),
            case.get("name"),
        )
        properties = case.find("properties")
        labels = {property.get("name").partition(":")[2] for property in properties}
        for label in labels:
            query = "properties/property[@name='{property}:{label}']"

            durations = [
                float(property.attrib["value"])
                for property in case.xpath(query.format(label=label, property="duration"))
            ]

            file_path: Path
            [file_path] = [
                Path(property.attrib["value"]) for property in case.xpath(query.format(label=label, property="path"))
            ]

            line: int
            [line] = [
                int(property.attrib["value"]) for property in case.xpath(query.format(label=label, property="line"))
            ]

            result = Result(
                path=file_path,
                line=line,
                label=label,
                durations=durations,
            )

            raw_durations[path].append(result)

    sorted_durations: Dict[Tuple[str, ...], List[Result]] = {
        path: sorted(results) for path, results in sorted(raw_durations.items())
    }

    for path, results in sorted_durations.items():
        for result in results:
            print(result.link(prefix=link_prefix, line_separator=link_line_separator), json.dumps(result.marshal()))


if __name__ == "__main__":
    main()
