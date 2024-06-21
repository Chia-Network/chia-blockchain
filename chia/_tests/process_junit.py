from __future__ import annotations

import dataclasses
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import StatisticsError, mean, stdev
from typing import Any, Dict, List, Optional, TextIO, Tuple, Type, final

import click
import lxml.etree

from chia._tests.util.misc import BenchmarkData, DataTypeProtocol, TestId
from chia._tests.util.time_out_assert import TimeOutAssertData

supported_data_types: List[Type[DataTypeProtocol]] = [TimeOutAssertData, BenchmarkData]
supported_data_types_by_tag: Dict[str, Type[DataTypeProtocol]] = {cls.tag: cls for cls in supported_data_types}


@final
@dataclass(frozen=True, order=True)
class Result:
    file_path: Path
    test_path: Tuple[str, ...]
    ids: Tuple[str, ...]
    label: str
    line: int = field(compare=False)
    durations: Tuple[float, ...] = field(compare=False)
    limit: float = field(compare=False)

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


@final
@dataclasses.dataclass(frozen=True)
class EventId:
    test_id: TestId
    tag: str
    line: int
    path: Path
    label: str


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--xml",
    "xml_file",
    required=True,
    type=click.File(),
    help="The benchmarks JUnit XML results file",
)
@click.option(
    "--link-prefix",
    default="",
    help="Prefix for output links such as for web links instead of IDE links",
    show_default=True,
)
@click.option(
    "--link-line-separator",
    default=":",
    help="The separator between the path and the line number, such as : for local links and #L on GitHub",
    show_default=True,
)
@click.option(
    "--output",
    default="-",
    type=click.File(mode="w", encoding="utf-8", lazy=True, atomic=True),
    help="Output file, - for stdout",
    show_default=True,
)
# TODO: anything but this pattern for output types
@click.option(
    "--markdown/--no-markdown",
    help="Use markdown as output format",
    show_default=True,
)
@click.option(
    "--percent-margin",
    default=15,
    type=int,
    help="Highlight results with maximums within this percent of the limit",
    show_default=True,
)
@click.option(
    "--randomoji/--determimoji",
    help="🍿",
    show_default=True,
)
# TODO: subcommands?
@click.option(
    "--type",
    "tag",
    type=click.Choice([cls.tag for cls in supported_data_types]),
    help="The type of data to process",
    required=True,
    show_default=True,
)
@click.option(
    "--limit",
    "result_count_limit",
    type=int,
    help="Limit the number of results to output.",
)
def main(
    xml_file: TextIO,
    link_prefix: str,
    link_line_separator: str,
    output: TextIO,
    markdown: bool,
    percent_margin: int,
    randomoji: bool,
    tag: str,
    result_count_limit: Optional[int],
) -> None:
    data_type = supported_data_types_by_tag[tag]

    tree = lxml.etree.parse(xml_file)
    root = tree.getroot()

    cases_by_test_id: defaultdict[TestId, List[lxml.etree.Element]] = defaultdict(list)
    for suite in root.findall("testsuite"):
        for case in suite.findall("testcase"):
            if case.find("skipped") is not None:
                continue
            test_id_property = case.find("properties/property[@name='test_id']")
            test_id = TestId.unmarshal(json.loads(test_id_property.attrib["value"]))
            test_id = dataclasses.replace(
                test_id, ids=tuple(id for id in test_id.ids if not id.startswith(f"{data_type.tag}_repeat"))
            )
            cases_by_test_id[test_id].append(case)

    data_by_event_id: defaultdict[EventId, List[DataTypeProtocol]] = defaultdict(list)
    for test_id, cases in cases_by_test_id.items():
        for case in cases:
            for property in case.findall(f"properties/property[@name='{tag}']"):
                tag = property.attrib["name"]
                data = supported_data_types_by_tag[tag].unmarshal(json.loads(property.attrib["value"]))
                event_id = EventId(test_id=test_id, tag=tag, line=data.line, path=data.path, label=data.label)
                data_by_event_id[event_id].append(data)

    results: List[Result] = []
    for event_id, datas in data_by_event_id.items():
        [limit] = {data.limit for data in datas}
        results.append(
            Result(
                file_path=event_id.path,
                test_path=event_id.test_id.test_path,
                ids=event_id.test_id.ids,
                line=event_id.line,
                durations=tuple(data.duration for data in datas),
                limit=limit,
                label=event_id.label,
            )
        )

    if result_count_limit is not None:
        results = sorted(results, key=lambda result: max(result.durations) / result.limit, reverse=True)
        results = results[:result_count_limit]

    handlers = {
        BenchmarkData.tag: output_benchmark,
        TimeOutAssertData.tag: output_time_out_assert,
    }
    handler = handlers[data_type.tag]
    handler(
        link_line_separator=link_line_separator,
        link_prefix=link_prefix,
        markdown=markdown,
        output=output,
        percent_margin=percent_margin,
        randomoji=randomoji,
        results=results,
    )


def output_benchmark(
    link_line_separator: str,
    link_prefix: str,
    markdown: bool,
    output: TextIO,
    percent_margin: int,
    randomoji: bool,
    results: List[Result],
) -> None:
    if not markdown:
        for result in sorted(results):
            link = result.link(prefix=link_prefix, line_separator=link_line_separator)
            dumped = json.dumps(result.marshal())
            output.write(f"{link} {dumped}\n")
    else:
        output.write("# Benchmark Metrics\n\n")

        output.write("| Test | 🍿 | Mean | Max | 3σ | Limit | Percent |\n")
        output.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        for result in sorted(results):
            link_url = result.link(prefix=link_prefix, line_separator=link_line_separator)

            mean_str = "-"
            three_sigma_str = "-"
            if len(result.durations) > 1:
                durations_mean = mean(result.durations)
                mean_str = f"{durations_mean:.3f} s"

                try:
                    three_sigma_str = f"{durations_mean + 3 * stdev(result.durations):.3f} s"
                except StatisticsError:
                    pass

            durations_max = max(result.durations)
            max_str = f"{durations_max:.3f} s"

            limit_str = f"{result.limit:.3f} s"

            percent = 100 * durations_max / result.limit
            if percent >= 100:
                # intentionally biasing towards 🍄
                choices = "🍄🍄🍎🍅"  # 🌶️🍉🍒🍓
            elif percent >= (100 - percent_margin):
                choices = "🍋🍌"  # 🍍🌽
            else:
                choices = "🫛🍈🍏🍐🥝🥒🥬🥦"

            marker: str
            if randomoji:
                marker = random.choice(choices)
            else:
                marker = choices[0]

            percent_str = f"{percent:.0f} %"

            test_path_str = ".".join(result.test_path[1:])
            if len(result.ids) > 0:
                test_path_str += f"[{'-'.join(result.ids)}]"

            test_link_text: str
            if result.label == "":
                test_link_text = f"`{test_path_str}`"
            else:
                test_link_text = f"`{test_path_str}` - {result.label}"

            output.write(
                f"| [{test_link_text}]({link_url})"
                + f" | {marker}"
                + f" | {mean_str}"
                + f" | {max_str}"
                + f" | {three_sigma_str}"
                + f" | {limit_str}"
                + f" | {percent_str}"
                + " |\n"
            )


def output_time_out_assert(
    link_line_separator: str,
    link_prefix: str,
    markdown: bool,
    output: TextIO,
    percent_margin: int,
    randomoji: bool,
    results: List[Result],
) -> None:
    if not markdown:
        for result in sorted(results):
            link = result.link(prefix=link_prefix, line_separator=link_line_separator)
            dumped = json.dumps(result.marshal())
            output.write(f"{link} {dumped}\n")
    else:
        output.write("# Time Out Assert Metrics\n\n")

        output.write("| Test | 🍿 | Mean | Max | 3σ | Limit | Percent |\n")
        output.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        for result in sorted(results):
            link_url = result.link(prefix=link_prefix, line_separator=link_line_separator)

            mean_str = "-"
            three_sigma_str = "-"
            if len(result.durations) > 1:
                durations_mean = mean(result.durations)
                mean_str = f"{durations_mean:.3f} s"

                try:
                    three_sigma_str = f"{durations_mean + 3 * stdev(result.durations):.3f} s"
                except StatisticsError:
                    pass

            durations_max = max(result.durations)
            max_str = f"{durations_max:.3f} s"

            limit_str = f"{result.limit:.3f} s"

            percent = 100 * durations_max / result.limit
            if percent >= 100:
                # intentionally biasing towards 🍄
                choices = "🍄🍄🍎🍅"  # 🌶️🍉🍒🍓
            elif percent >= (100 - percent_margin):
                choices = "🍋🍌"  # 🍍🌽
            else:
                choices = "🫛🍈🍏🍐🥝🥒🥬🥦"

            marker: str
            if randomoji:
                marker = random.choice(choices)
            else:
                marker = choices[0]

            percent_str = f"{percent:.0f} %"

            test_path_str = ".".join(result.test_path[1:])
            if len(result.ids) > 0:
                test_path_str += f"[{'-'.join(result.ids)}]"

            test_link_text: str
            if result.label == "":
                # TODO: but could be in different files too
                test_link_text = f"`{test_path_str}` - {result.line}"
            else:
                test_link_text = f"`{test_path_str}` - {result.label}"

            output.write(
                f"| [{test_link_text}]({link_url})"
                + f" | {marker}"
                + f" | {mean_str}"
                + f" | {max_str}"
                + f" | {three_sigma_str}"
                + f" | {limit_str}"
                + f" | {percent_str}"
                + " |\n"
            )


if __name__ == "__main__":
    # pylint: disable = no-value-for-parameter
    main()
