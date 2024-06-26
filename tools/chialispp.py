from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# A simple class for separating a line into code and comment
class Line:
    def __init__(self, code: List[bytes], comment: Optional[List[bytes]]):
        self.code = code
        self.comment = comment


# Remove all whitespace from the beginning of a byte array
def trim_ascii_start(line: List[bytes]) -> List[bytes]:
    first_non_ws: int = 0
    got_one: bool = False

    for i, ch in enumerate(line):
        if not (ch.decode("ascii").isspace()):
            got_one = True
            first_non_ws = i
            break

    if not got_one:
        return []
    else:
        return line[first_non_ws:]


# Remove all whitespace from the end of a byte array
def trim_ascii_end(line: List[bytes]) -> List[bytes]:
    last_non_ws: int = 0
    got_one: bool = False

    for i, ch in enumerate(line):
        if (not ch.decode("ascii").isspace()) and ch[0] <= 127:
            got_one = True
            last_non_ws = i

    if not got_one:
        return []
    else:
        return line[0 : last_non_ws + 1]


class Formatter:
    def __init__(self) -> None:
        self.start_paren_level: int = 0
        self.paren_level: int = 0
        self.out_col: int = 0  # The colum we are at while outputting a line
        self.cur_line: int = 0
        self.line: List[bytes] = []
        self.comment: Optional[List[bytes]] = None
        self.lines: List[List[bytes]] = []
        self.work_lines: List[Line] = []
        self.getting_form_name: int = 0
        self.got_form_on_line: int = 0
        self.form_name: List[bytes] = []
        self.reset_form_indent: bool = False
        # self.def_started = False
        self.result_line: List[bytes] = []
        # self.definition_starts = []
        # self.extra_def_lines = []
        self.indent_stack: List[int] = []
        self.result: List[List[bytes]] = []
        self.config: Dict[str, Any] = {
            "gnu_comment_conventions": False,
        }

    # Add a character of source, breaking the source into lines as we go
    def run_char(self, ch: bytes) -> None:
        if ch == b"\n":
            self.finish_line()
        else:
            self.line.append(ch)

    # Process a single character and add it to the final result
    def output_char(self, ch: bytes) -> None:
        if ch == b"\n":
            self.work_lines.append(Line(self.result_line, self.comment))
            self.result_line = []
            self.comment = None
            self.out_col = 0
        else:
            self.result_line.append(ch)
            self.out_col += 1

    # Process a line and add it to the work_lines array
    def output_line(self) -> None:
        line_indent = self.get_cur_indent()
        max_paren_level = self.paren_level
        self.start_paren_level = self.paren_level
        starting_indent_len = len(self.indent_stack)

        if not self.line:
            self.output_char(b"\n")
            return

        # Get a line from the unprocessed lines
        line = trim_ascii_end(self.line)
        line = trim_ascii_start(line)
        self.line.clear()

        # Some variables to be aware of whether or not we're in a string literal
        in_string = None
        string_bs = False  # bs == backslash

        # Some variables to be aware of whether or not we're in a comment
        semis = 0  # number of semi colons starting a comment
        semi_off = 0  # the column where the comment starts
        comment = []  # The comment byte array

        # Main loop to format the line
        for i, ch in enumerate(line):
            # Track the form name
            if self.getting_form_name > 0:
                self.reset_form_indent = False
                if self.getting_form_name == 1 and not (ch == b" "):
                    self.getting_form_name = 2
                    self.form_name.append(ch)
                elif self.getting_form_name == 2 and ch in (b" ", b"(", b")"):
                    self.getting_form_name = 0
                    self.got_form_on_line = self.cur_line
                else:
                    self.form_name.append(ch)

            # if self.start_paren_level == 1 and not self.def_started:
            #     self.def_started = True
            #     self.definition_starts.append(len(self.work_lines))

            # Special indentation rules for `if`
            should_reset_indent = (
                self.getting_form_name == 0
                and self.form_name == [b"i", b"f"]
                and not (ch == b" ")
                and not self.reset_form_indent
            )

            # Be sure to not format string literals as code
            if string_bs:
                string_bs = False
                continue
            if in_string is not None:
                if ch == b"\\":
                    string_bs = True
                if ch == in_string:
                    in_string = None
                continue

            if semis == 0:
                # We've entered a string, stop processing
                if ch == b"'" or ch == b'"':
                    in_string = ch
                    continue
                elif ch == b"(":
                    self.paren_level += 1
                    max_paren_level = max(max_paren_level, self.paren_level)

                    if should_reset_indent:
                        self.reset_indent(line_indent + i)
                        self.reset_form_indent = True
                    self.indent_paren()

                    self.form_name.clear()
                    self.got_form_on_line = 0
                    self.getting_form_name = 1
                    continue
                elif ch == b")":
                    indentation_diff: int = (self.indent_stack[-1] if len(self.indent_stack) > 0 else 0) - (
                        self.indent_stack[-2] if len(self.indent_stack) > 1 else 0
                    )
                    self.retire_indent()
                    if self.paren_level <= self.start_paren_level:
                        line_indent -= indentation_diff
                    self.paren_level -= 1
                    continue
                elif should_reset_indent:
                    self.reset_indent(line_indent + i)
                    self.reset_form_indent = True

            if ch == b";":
                if semis == 0:
                    semi_off = i
                semis += 1
            elif semis > 0:
                comment = line[i:]
                line = trim_ascii_end(line[:semi_off])
                break

        if semis + semi_off == len(line):
            line = trim_ascii_end(line[:semi_off])

        line = trim_ascii_end(line)

        if semis == 1 and not line and self.config["gnu_comment_conventions"]:
            semis = 0
            self.comment = comment
            comment = []
        else:
            self.comment = None

        if semis > 0:
            if semis < 3 or not self.config["gnu_comment_conventions"]:
                self.indent(line_indent)
            if line and not self.config["gnu_comment_conventions"]:
                for co in line:
                    self.output_char(co)
                self.output_char(b" ")
                self.output_char(b" ")
            for _i in range(semis):
                self.output_char(b";")
            for co in comment:
                self.output_char(co)
            if line and self.config["gnu_comment_conventions"]:
                # Code after comment in this scenario
                self.output_char(b"\n")
                self.indent(line_indent)
                for co in line:
                    self.output_char(co)
        elif line != []:
            self.indent(line_indent)
            for co in line:
                self.output_char(co)

        self.output_char(b"\n")

        # We never want the next line to be more indented than us + 1 unit
        if len(self.indent_stack) > starting_indent_len + 1:
            for i in range(starting_indent_len + 1, len(self.indent_stack)):
                self.indent_stack[i] = self.indent_stack[starting_indent_len + 1]

        # if max_paren_level > 1 and self.paren_level == 1:
        #     self.def_started = False
        #     self.extra_def_lines.append(len(self.work_lines))

    # Add our current line to our lines array and reset the line
    def finish_line(self) -> None:
        self.lines.append(self.line.copy())
        self.line.clear()
        self.comment = None

    def finish(self) -> None:
        if self.line:
            self.finish_line()

        for i in range(len(self.lines)):
            self.line = self.lines[i]
            self.cur_line = i
            self.output_line()

        next_handle_line = 0
        for i in range(len(self.work_lines)):
            if i < next_handle_line:
                continue

            # Find the max comment spacing needed and output the group.
            # Skip if already handled.
            comment = self.work_lines[i].comment
            if comment is not None:
                comment_offset = len(self.work_lines[i].code)
                comments = [comment]
                for j in range(i + 1, len(self.lines)):
                    comment = self.work_lines[j].comment
                    if comment is not None:
                        comments.append(comment)
                        comment_offset = max(comment_offset, len(self.work_lines[j].code))
                    else:
                        next_handle_line = j
                        break

                for j, comment in enumerate(comments):
                    line = self.work_lines[i + j].code.copy()
                    while len(line) < comment_offset:
                        line.append(b" ")
                    line.append(b" ")
                    line.append(b";")
                    line += comment[:]
                    self.result.append(line)
            else:
                self.result.append(self.work_lines[i].code.copy())

        # el_idx = 0
        # inserted = 0
        #
        # for ds in self.definition_starts[0:len(self.definition_starts)]:
        #     while el_idx < len(self.extra_def_lines) and self.extra_def_lines[el_idx] < ds:
        #         el_idx += 1
        #
        #     if el_idx >= len(self.extra_def_lines):
        #         break
        #
        #     el = self.extra_def_lines[el_idx]
        #     if el <= ds + 1:
        #         insert_at = el + inserted
        #         self.result.insert(insert_at, [])
        #         inserted += 1

    # We maintain a stack of indentation levels
    # The following functions maintain that stack
    def indent(self, cur_indent: int) -> None:
        while self.out_col < cur_indent:
            self.output_char(b" ")

    def get_cur_indent(self) -> int:
        if self.indent_stack:
            return self.indent_stack[-1]
        else:
            return 0

    def reset_indent(self, i: int) -> None:
        if self.indent_stack:
            self.indent_stack[-1] = i

    def indent_paren(self) -> None:
        current_indent = self.indent_stack[-1] if self.indent_stack else 0
        self.indent_stack.append(current_indent + 2)

    def retire_indent(self) -> None:
        if self.indent_stack:
            self.indent_stack.pop()


def concat_byte_array(bs: List[bytes]) -> bytes:
    return b"".join(bs)


def main() -> None:
    for arg in sys.argv[1:]:
        path = Path(arg)
        if path.is_dir():
            all_paths = [*path.rglob("*.clsp"), *path.rglob("*.clib")]
        else:
            all_paths = [path]

        for filename in all_paths:
            with open(filename, "rb") as f:
                filedata = f.read()

            formatter = Formatter()

            for ch in filedata:
                formatter.run_char(bytes([ch]))

            formatter.finish()

            with open(filename, "wb") as f:
                for i, line in enumerate(formatter.result):
                    f.write(concat_byte_array(line))
                    f.write(b"\n")


if __name__ == "__main__":
    main()
