import sys
import io
import typing


class FloraIOWrapper(io.TextIOWrapper):

    def __init__(
            self,
            buffer: typing.IO[bytes],
            rewrite: typing.Dict,
            encoding=None,
            errors=None,
            newline=None,
            line_buffering=False,
            write_through=False,
    ) -> None:
        super().__init__(
            buffer,
            encoding=encoding,
            errors=errors,
            newline=newline,
            line_buffering=line_buffering,
            write_through=write_through
        )
        self.rewrite = rewrite

    def write(
            self, __s: str
    ) -> int:
        s: str = __s

        for old, new in self.rewrite.items():
            s = s.replace(
                old,
                new
            )

        self.buffer.write(
            s
        )

        return len(__s)

    def writelines(
            self,
            __lines: typing.Iterable[str]
    ) -> None:

        lines = []

        for line in __lines:
            s = line

            for old, new in self.rewrite.items():
                s = s.replace(
                    old,
                    new
                )

            lines.append(s)

        self.buffer.writelines(
            lines
        )


sys.stdout = FloraIOWrapper(
    buffer=sys.__stdout__,
    rewrite={
        "chia": "flora",
        "Chia": "Flora",
        "CHIA": "FLORA",
        "XCH": "XFL",
        "xch": "xfl"
    }
)

sys.stderr = FloraIOWrapper(
    buffer=sys.__stderr__,
    rewrite={
        "chia": "flora",
        "Chia": "Flora",
        "CHIA": "FLORA",
        "XCH": "XFL",
        "xch": "xfl"
    }
)
