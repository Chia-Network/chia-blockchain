from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Set, TextIO, Tuple, final

import click
import lxml.etree


@final
@dataclass(frozen=True, order=True)
class Result:
    file_path: Path
    test_path: Tuple[str, ...]
    label: str
    line: int = field(compare=False)
    durations: Tuple[float, ...] = field(compare=False)

    def marshal(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path.as_posix(),
            "test_path": self.test_path,
            "label": self.label,
            "duration": {
                "all": self.durations,
                "min": min(self.durations),
                "max": max(self.durations),
                "mean": mean(self.durations),
            },
        }

    def link(self, prefix: str, line_separator: str) -> str:
        return f"{prefix}{self.file_path.as_posix()}{line_separator}{self.line}"


def sub(matchobj: re.Match[str]) -> str:
    result = ""

    if matchobj.group("start") == "[":
        result += "["

    if matchobj.group("start") == matchobj.group("end") == "-":
        result += "-"

    if matchobj.group("end") == "]":
        result += "]"

    return result


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

    # raw_durations: defaultdict[Tuple[str, ...], List[Result]] = defaultdict(list)

    cases_by_test_path: defaultdict[Tuple[str, ...], List[lxml.etree.Element]] = defaultdict(list)
    for case in benchmarks.findall("testcase"):
        failure = case.find("failure")
        if failure is not None:
            # TODO: let's get all the data, just dealing with this later
            continue

        raw_name = case.attrib["name"]
        name = re.sub(r"(?P<start>[-\[])benchmark_repeat\d{3}(?P<end>[-\])])", sub, raw_name)
        # TODO: seems to duplicate the class and function name, though not the parametrizations
        test_path = (
            *case.attrib["classname"].split("."),
            name,
        )
        cases_by_test_path[test_path].append(case)

    results: List[Result] = []
    for test_path, cases in cases_by_test_path.items():
        labels: Set[str] = set()
        for case in cases:
            properties = case.find("properties")
            labels.update(property.attrib["name"].partition(":")[2] for property in properties)

        for label in labels:
            query = "properties/property[@name='{property}:{label}']"

            durations = [
                float(property.attrib["value"])
                for case in cases
                for property in case.xpath(query.format(label=label, property="duration"))
            ]

            a_case = cases[0]

            file_path: Path
            [file_path] = [
                Path(property.attrib["value"]) for property in a_case.xpath(query.format(label=label, property="path"))
            ]

            line: int
            [line] = [
                int(property.attrib["value"]) for property in a_case.xpath(query.format(label=label, property="line"))
            ]

            results.append(
                Result(
                    file_path=file_path,
                    test_path=test_path,
                    line=line,
                    label=label,
                    durations=tuple(durations),
                )
            )

    for result in results:
        print(result.link(prefix=link_prefix, line_separator=link_line_separator), json.dumps(result.marshal()))


if __name__ == "__main__":
    main()
