"""
Provides a helper to access the legacy keyring which was supported up to version 1.6.1 of chia-blockchain. To use this
helper it's required to install the `legacy_keyring` extra dependency which can be done via the install-option `-l`.
"""

from __future__ import annotations

import sys
from typing import Callable, List, Union, cast

import click
from blspy import G1Element
from keyring.backends.macOS import Keyring as MacKeyring
from keyring.backends.Windows import WinVaultKeyring as WinKeyring

try:
    from keyrings.cryptfile.cryptfile import CryptFileKeyring
except ImportError:
    if sys.platform == "linux":
        sys.exit("Use `install.sh -l` to install the legacy_keyring dependency.")
    CryptFileKeyring = None


from chia.util.errors import KeychainUserNotFound
from chia.util.keychain import KeyData, KeyDataSecrets, get_private_key_user
from chia.util.misc import prompt_yes_no

LegacyKeyring = Union[MacKeyring, WinKeyring, CryptFileKeyring]


CURRENT_KEY_VERSION = "1.8"
DEFAULT_USER = f"user-chia-{CURRENT_KEY_VERSION}"  # e.g. user-chia-1.8
DEFAULT_SERVICE = f"chia-{DEFAULT_USER}"  # e.g. chia-user-chia-1.8
MAX_KEYS = 100


# casting to compensate for a combination of mypy and keyring issues
# https://github.com/python/mypy/issues/9025
# https://github.com/jaraco/keyring/issues/437
def create_legacy_keyring() -> LegacyKeyring:
    if sys.platform == "darwin":
        return cast(Callable[[], LegacyKeyring], MacKeyring)()
    elif sys.platform == "win32" or sys.platform == "cygwin":
        return cast(Callable[[], LegacyKeyring], WinKeyring)()
    elif sys.platform == "linux":
        keyring: CryptFileKeyring = CryptFileKeyring()
        keyring.keyring_key = "your keyring password"
        return keyring
    raise click.ClickException(f"platform '{sys.platform}' not supported.")


def generate_and_add(keyring: LegacyKeyring) -> KeyData:
    key = KeyData.generate()
    index = 0
    while True:
        try:
            get_key_data(keyring, index)
            index += 1
        except KeychainUserNotFound:
            keyring.set_password(
                DEFAULT_SERVICE,
                get_private_key_user(DEFAULT_USER, index),
                bytes(key.public_key).hex() + key.entropy.hex(),
            )
            return key


def get_key_data(keyring: LegacyKeyring, index: int) -> KeyData:
    user = get_private_key_user(DEFAULT_USER, index)
    read_str = keyring.get_password(DEFAULT_SERVICE, user)
    if read_str is None or len(read_str) == 0:
        raise KeychainUserNotFound(DEFAULT_SERVICE, user)
    str_bytes = bytes.fromhex(read_str)

    public_key = G1Element.from_bytes(str_bytes[: G1Element.SIZE])
    fingerprint = public_key.get_fingerprint()
    entropy = str_bytes[G1Element.SIZE : G1Element.SIZE + 32]

    return KeyData(
        fingerprint=fingerprint,
        public_key=public_key,
        label=None,
        secrets=KeyDataSecrets.from_entropy(entropy),
    )


def get_keys(keyring: LegacyKeyring) -> List[KeyData]:
    keys: List[KeyData] = []
    for index in range(MAX_KEYS + 1):
        try:
            keys.append(get_key_data(keyring, index))
        except KeychainUserNotFound:
            pass
    return keys


def print_key(key: KeyData) -> None:
    print(f"fingerprint: {key.fingerprint}, mnemonic: {key.mnemonic_str()}")


def print_keys(keyring: LegacyKeyring) -> None:
    keys = get_keys(keyring)

    if len(keys) == 0:
        raise click.ClickException("No keys found in the legacy keyring.")

    for key in keys:
        print_key(key)


def remove_keys(keyring: LegacyKeyring) -> None:
    removed = 0
    for index in range(MAX_KEYS + 1):
        try:
            keyring.delete_password(DEFAULT_SERVICE, get_private_key_user(DEFAULT_USER, index))
            removed += 1
        except Exception:
            pass

    print(f"{removed} key{'s' if removed != 1 else ''} removed.")


@click.group(help="Manage the keys in the legacy keyring.")
def legacy_keyring() -> None:
    pass


@legacy_keyring.command(help="Generate and add a random key (for testing)", hidden=True)
def generate() -> None:
    keyring = create_legacy_keyring()
    key = generate_and_add(keyring)
    print_key(key)


@legacy_keyring.command(help="Show all available keys")
def show() -> None:
    print_keys(create_legacy_keyring())


@legacy_keyring.command(help="Remove all keys")
def clear() -> None:
    keyring = create_legacy_keyring()

    print_keys(keyring)

    if not prompt_yes_no("\nDo you really want to remove all the keys from the legacy keyring? This can't be undone."):
        raise click.ClickException("Aborted!")

    remove_keys(keyring)


if __name__ == "__main__":
    legacy_keyring()
