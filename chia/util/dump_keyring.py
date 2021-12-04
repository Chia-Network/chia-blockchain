#!/usr/bin/env python3

import click
import colorama
import threading
import yaml

from chia.cmds.passphrase_funcs import prompt_for_passphrase, read_passphrase_from_file
from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH
from chia.util.file_keyring import FileKeyring
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, KeyringWrapper
from cryptography.exceptions import InvalidTag
from io import TextIOWrapper
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_KEYRING_YAML = DEFAULT_KEYS_ROOT_PATH / "keyring.yaml"


class DumpKeyring(FileKeyring):  # lgtm [py/missing-call-to-init]
    def __init__(self, keyring_file: Path):
        self.keyring_path = keyring_file
        self.payload_cache = {}
        self.load_keyring_lock = threading.RLock()
        # We don't call super().__init__() to avoid side-effects


def get_passphrase_prompt(keyring_file: str) -> str:
    prompt = (
        colorama.Fore.YELLOW
        + colorama.Style.BRIGHT
        + "(Unlock Keyring: "
        + colorama.Fore.MAGENTA
        + keyring_file
        + colorama.Style.RESET_ALL
        + colorama.Fore.YELLOW
        + colorama.Style.BRIGHT
        + ")"
        + colorama.Style.RESET_ALL
        + " Passphrase: "
    )  # noqa: E501
    return prompt


@click.command()
@click.argument("keyring_file", nargs=1, default=DEFAULT_KEYRING_YAML)
@click.option(
    "--full-payload", is_flag=True, default=False, help="Print the full keyring contents, including plaintext"
)
@click.option("--passphrase-file", type=click.File("r"), help="File or descriptor to read the passphrase from")
@click.option("--pretty-print", is_flag=True, default=False)
def dump(keyring_file, full_payload: bool, passphrase_file: Optional[TextIOWrapper], pretty_print: bool):
    saved_passphrase: Optional[str] = KeyringWrapper.get_shared_instance().get_master_passphrase_from_credential_store()
    passphrase: str = saved_passphrase or DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
    prompt: str = get_passphrase_prompt(str(keyring_file))
    data: Dict[str, Any] = {}

    print(f"Attempting to dump contents of keyring file: {keyring_file}\n")

    if passphrase_file is not None:
        passphrase = read_passphrase_from_file(passphrase_file)

    keyring = DumpKeyring(Path(keyring_file))

    if full_payload:
        keyring.load_outer_payload()
        data = keyring.outer_payload_cache

    for i in range(5):
        try:
            keyring.load_keyring(passphrase)
            if len(data) > 0:
                data["data"] = keyring.payload_cache
            else:
                data = keyring.payload_cache

            if pretty_print:
                print(yaml.dump(data))
            else:
                print(data)
            break
        except (ValueError, InvalidTag):
            passphrase = prompt_for_passphrase(prompt)
        except Exception as e:
            print(f"Unhandled exception: {e}")
            break


def dump_to_string(
    keyring_file, full_payload: bool, passphrase_file: Optional[TextIOWrapper], pretty_print: bool
) -> str:
    saved_passphrase: Optional[str] = KeyringWrapper.get_shared_instance().get_master_passphrase_from_credential_store()
    passphrase: str = saved_passphrase or DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
    prompt: str = get_passphrase_prompt(str(keyring_file))
    data: Dict[str, Any] = {}

    print(f"Attempting to dump contents of keyring file: {keyring_file}\n")

    if passphrase_file is not None:
        passphrase = read_passphrase_from_file(passphrase_file)

    keyring = DumpKeyring(Path(keyring_file))

    if full_payload:
        keyring.load_outer_payload()
        data = keyring.outer_payload_cache

    s: str = ""
    for i in range(5):
        try:
            keyring.load_keyring(passphrase)
            if len(data) > 0:
                data["data"] = keyring.payload_cache
            else:
                data = keyring.payload_cache

            if pretty_print:
                s = yaml.dump(data)
            else:
                s = str(data)
            break
        except (ValueError, InvalidTag):
            passphrase = prompt_for_passphrase(prompt)
        except Exception as e:
            print(f"Unhandled exception: {e}")
            break
    return s


def main():
    colorama.init()
    dump()  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    main()
