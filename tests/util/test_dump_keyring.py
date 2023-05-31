from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Sequence

from click.testing import CliRunner

from chia.util.dump_keyring import dump
from chia.util.keychain import Keychain
from tests.util.misc import Marks, datacases

output_prefix = """Attempting to dump contents of keyring file: {path}

"""


@dataclass
class KeyringCase:
    args: Sequence[str]
    regex: str
    id: str
    marks: Marks = ()


@datacases(
    KeyringCase(
        id="empty",
        args=[],
        regex="\\{\\}\n",
    ),
    KeyringCase(
        id="empty, pretty",
        args=["--pretty-print"],
        regex="\\{\\}\n\n",
    ),
    KeyringCase(
        id="empty, full",
        args=["--full-payload"],
        regex=(
            "\\{'version': 1, 'salt': '[0-9a-f]{32}', 'nonce': '[0-9a-f]{24}', 'data': \\{\\},"
            " 'passphrase_hint': None\\}\n"
        ),
    ),
    KeyringCase(
        id="empty, full, pretty",
        args=["--full-payload", "--pretty-print"],
        regex="data: \\{\\}\nnonce: [0-9a-f]{24}\npassphrase_hint: null\nsalt: [0-9a-f]{32}\nversion: 1\n\n",
    ),
)
def test_keyring_dump_empty(empty_keyring: Keychain, case: KeyringCase) -> None:
    keyring_path = empty_keyring.keyring_wrapper.keyring.keyring_path
    runner = CliRunner()
    result = runner.invoke(dump, [*case.args, os.fspath(keyring_path)])

    regex = re.escape(output_prefix.format(path=keyring_path)) + case.regex

    assert re.fullmatch(regex, result.output) is not None
    assert result.exit_code == 0
