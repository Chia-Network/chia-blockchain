#!/usr/bin/env python3

import click
import colorama
import yaml

from chia.cmds.passphrase_funcs import prompt_for_passphrase, read_passphrase_from_file
from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH
from chia.util.file_keyring import FileKeyringContent
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, KeyringWrapper
from cryptography.exceptions import InvalidTag
from io import TextIOWrapper
from pathlib import Path
from typing import Optional

DEFAULT_KEYRING_YAML = DEFAULT_KEYS_ROOT_PATH / "keyring.yaml"


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

    print(f"Attempting to dump contents of keyring file: {keyring_file}\n")

    if passphrase_file is not None:
        passphrase = read_passphrase_from_file(passphrase_file)

    keyring_path = Path(keyring_file)
    file_content = FileKeyringContent.create_from_path(keyring_path)
    file_content_dict = file_content.to_dict()

    for i in range(5):
        try:
            data_dict = file_content.get_decrypted_data_dict(passphrase)
            if full_payload:
                dump_content = file_content_dict
                dump_content["data"] = data_dict
            else:
                dump_content = data_dict

            if pretty_print:
                dump_content = yaml.dump(dump_content)

            print(dump_content)
            break
        except (ValueError, InvalidTag):
            passphrase = prompt_for_passphrase(prompt)
        except Exception as e:
            print(f"Unhandled exception: {e}")
            break


def main():
    colorama.init()
    dump()  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    main()
