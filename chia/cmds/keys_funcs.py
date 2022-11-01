import json
import logging
import os
import sys

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.cmds.passphrase_funcs import obtain_current_passphrase
from chia.daemon.client import connect_to_daemon_and_validate
from chia.daemon.keychain_proxy import KeychainProxy, connect_to_keychain_and_validate, wrap_local_keychain
from chia.util.bech32m import encode_puzzle_hash
from chia.util.errors import KeychainNotSet
from chia.util.config import load_config
from chia.util.errors import KeychainException
from chia.util.file_keyring import MAX_LABEL_LENGTH
from chia.util.ints import uint32
from chia.util.keychain import Keychain, bytes_to_mnemonic, generate_mnemonic, mnemonic_to_seed
from chia.util.keyring_wrapper import KeyringWrapper
from chia.wallet.derive_keys import (
    master_sk_to_farmer_sk,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk,
    master_sk_to_wallet_sk_unhardened,
)


def unlock_keyring() -> None:
    """
    Used to unlock the keyring interactively, if necessary
    """

    try:
        if KeyringWrapper.get_shared_instance().has_master_passphrase():
            obtain_current_passphrase(use_passphrase_cache=True)
    except Exception as e:
        print(f"Unable to unlock the keyring: {e}")
        sys.exit(1)


def generate_and_print():
    """
    Generates a seed for a private key, and prints the mnemonic to the terminal.
    """

    mnemonic = generate_mnemonic()
    print("Generating private key. Mnemonic (24 secret words):")
    print(mnemonic)
    print("Note that this key has not been added to the keychain. Run chia keys add")
    return mnemonic


def generate_and_add(label: Optional[str]):
    """
    Generates a seed for a private key, prints the mnemonic to the terminal, and adds the key to the keyring.
    """
    unlock_keyring()
    print("Generating private key")
    query_and_add_private_key_seed(mnemonic=generate_mnemonic(), label=label)


def query_and_add_private_key_seed(mnemonic: Optional[str], label: Optional[str] = None):
    unlock_keyring()
    if mnemonic is None:
        mnemonic = input("Enter the mnemonic you want to use: ")
    if label is None:
        label = input("Enter the label you want to assign to this key (Press Enter to skip): ")
    if len(label) == 0:
        label = None
    add_private_key_seed(mnemonic, label)


def add_private_key_seed(mnemonic: str, label: Optional[str]):
    """
    Add a private key seed to the keyring, with the given mnemonic and an optional label.
    """
    unlock_keyring()
    try:
        sk = Keychain().add_private_key(mnemonic, label)
        fingerprint = sk.get_g1().get_fingerprint()
        print(f"Added private key with public key fingerprint {fingerprint}")

    except (ValueError, KeychainException) as e:
        print(e)


def show_all_key_labels() -> None:
    unlock_keyring()
    fingerprint_width = 11

    def print_line(fingerprint: str, label: str) -> None:
        fingerprint_text = ("{0:<" + str(fingerprint_width) + "}").format(fingerprint)
        label_text = ("{0:<" + str(MAX_LABEL_LENGTH) + "}").format(label)
        print("| " + fingerprint_text + " | " + label_text + " |")

    keys = Keychain().get_keys()

    if len(keys) == 0:
        sys.exit("No keys are present in the keychain. Generate them with 'chia keys generate'")

    print_line("fingerprint", "label")
    print_line("-" * fingerprint_width, "-" * MAX_LABEL_LENGTH)

    for key_data in keys:
        print_line(str(key_data.fingerprint), key_data.label or "No label assigned")


def set_key_label(fingerprint: int, label: str) -> None:
    unlock_keyring()
    try:
        Keychain().set_label(fingerprint, label)
        print(f"label {label!r} assigned to {fingerprint!r}")
    except Exception as e:
        sys.exit(f"Error: {e}")


def delete_key_label(fingerprint: int) -> None:
    unlock_keyring()
    try:
        Keychain().delete_label(fingerprint)
        print(f"label removed for {fingerprint!r}")
    except Exception as e:
        sys.exit(f"Error: {e}")


def show_all_keys(root_path: Path, show_mnemonic: bool, non_observer_derivation: bool, json_output: bool):
    """
    Prints all keys and mnemonics (if available).
    """
    unlock_keyring()
    config = load_config(root_path, "config.yaml")
    all_keys = Keychain().get_keys(True)
    selected = config["selected_network"]
    prefix = config["network_overrides"]["config"][selected]["address_prefix"]

    if len(all_keys) == 0:
        if json_output:
            print(json.dumps({"keys": []}))
        else:
            print("There are no saved private keys")
        return None

    if not json_output:
        msg = "Showing all public keys derived from your master seed and private key:"
        if show_mnemonic:
            msg = "Showing all public and private keys"
        print(msg)

    def process_key_data(key_data):
        key = {}
        sk = key_data.private_key
        if key_data.label is not None:
            key["label"] = key_data.label

        key["fingerprint"] = key_data.fingerprint
        key["master_pk"] = bytes(key_data.public_key).hex()
        key["farmer_pk"] = bytes(master_sk_to_farmer_sk(sk).get_g1()).hex()
        key["pool_pk"] = bytes(master_sk_to_pool_sk(sk).get_g1()).hex()
        first_wallet_sk: PrivateKey = (
            master_sk_to_wallet_sk(sk, uint32(0))
            if non_observer_derivation
            else master_sk_to_wallet_sk_unhardened(sk, uint32(0))
        )
        wallet_address: str = encode_puzzle_hash(create_puzzlehash_for_pk(first_wallet_sk.get_g1()), prefix)
        key["wallet_address"] = wallet_address
        key["non_observer"] = non_observer_derivation

        if show_mnemonic:
            key["master_sk"] = bytes(sk).hex()
            key["wallet_sk"] = bytes(master_sk_to_wallet_sk(sk, uint32(0))).hex()
            key["mnemonic"] = bytes_to_mnemonic(key_data.entropy)
        return key

    keys = map(process_key_data, all_keys)

    if json_output:
        print(json.dumps({"keys": list(keys)}))
    else:
        for key in keys:
            print("")
            if "label" in key:
                print("Label:", key["label"])
            print("Fingerprint:", key["fingerprint"])
            print("Master public key (m):", key["master_pk"])
            print("Farmer public key (m/12381/8444/0/0):", key["farmer_pk"])
            print("Pool public key (m/12381/8444/1/0):", key["pool_pk"])
            print(f"First wallet address{' (non-observer)' if key['non_observer'] else ''}: {key['wallet_address']}")
            if show_mnemonic:
                print("Master private key (m):", key["master_sk"])
                print("First wallet secret key (m/12381/8444/2/0):", key["wallet_sk"])
                print("  Mnemonic seed (24 secret words):")
                print(key["mnemonic"])


def delete(fingerprint: int):
    """
    Delete a key by its public key fingerprint (which is an integer).
    """
    unlock_keyring()
    print(f"Deleting private_key with fingerprint {fingerprint}")
    Keychain().delete_key_by_fingerprint(fingerprint)


def derive_sk_from_hd_path(master_sk: PrivateKey, hd_path_root: str) -> Tuple[PrivateKey, str]:
    """
    Derive a private key from the provided HD path. Takes a master key and HD path as input,
    and returns the derived key and the HD path that was used to derive it.
    """

    from chia.wallet.derive_keys import _derive_path, _derive_path_unhardened

    class DerivationType(Enum):
        NONOBSERVER = 0
        OBSERVER = 1

    path: List[str] = hd_path_root.split("/")
    if len(path) == 0 or path[0] != "m":
        raise ValueError("Invalid HD path. Must start with 'm'")

    path = path[1:]  # Skip "m"

    if len(path) > 0 and path[-1] == "":  # remove trailing slash
        path = path[:-1]

    index_and_derivation_types: List[Tuple[int, DerivationType]] = []

    # Validate path
    for current_index_str in path:
        if len(current_index_str) == 0:
            raise ValueError("Invalid HD path. Empty index")

        non_observer: bool = current_index_str[-1] == "n"
        current_index: int = int(current_index_str[:-1]) if non_observer else int(current_index_str)

        index_and_derivation_types.append(
            (current_index, DerivationType.NONOBSERVER if non_observer else DerivationType.OBSERVER)
        )

    current_sk: PrivateKey = master_sk

    # Derive keys along the path
    for (current_index, derivation_type) in index_and_derivation_types:
        if derivation_type == DerivationType.NONOBSERVER:
            current_sk = _derive_path(current_sk, [current_index])
        elif derivation_type == DerivationType.OBSERVER:
            current_sk = _derive_path_unhardened(current_sk, [current_index])
        else:
            raise ValueError(f"Unhandled derivation type: {derivation_type}")

    return (current_sk, "m/" + "/".join(path) + "/")


def sign(message: str, private_key: PrivateKey, hd_path: str, as_bytes: bool):
    sk: PrivateKey = derive_sk_from_hd_path(private_key, hd_path)[0]
    data = bytes.fromhex(message) if as_bytes else bytes(message, "utf-8")
    print("Public key:", sk.get_g1())
    print("Signature:", AugSchemeMPL.sign(sk, data))


def verify(message: str, public_key: str, signature: str):
    messageBytes = bytes(message, "utf-8")
    public_key = G1Element.from_bytes(bytes.fromhex(public_key))
    signature = G2Element.from_bytes(bytes.fromhex(signature))
    print(AugSchemeMPL.verify(public_key, messageBytes, signature))


async def migrate_keys(root_path: Path, forced: bool = False) -> bool:
    from chia.util.keyring_wrapper import KeyringWrapper
    from chia.util.misc import prompt_yes_no

    deprecation_message = (
        "\nLegacy keyring support is deprecated and will be removed in an upcoming version. "
        "You need to migrate your keyring to continue using Chia.\n"
    )

    # Check if the keyring needs a full migration (i.e. if it's using the old keyring)
    if Keychain.needs_migration():
        print(deprecation_message)
        return await KeyringWrapper.get_shared_instance().migrate_legacy_keyring_interactive()
    else:
        already_checked_marker = KeyringWrapper.get_shared_instance().keys_root_path / ".checked_legacy_migration"
        if forced and already_checked_marker.exists():
            return True

        log = logging.getLogger("migrate_keys")
        config = load_config(root_path, "config.yaml")
        # Connect to the daemon here first to see if ts running since `connect_to_keychain_and_validate` just tries to
        # connect forever if it's not up.
        keychain_proxy: Optional[KeychainProxy] = None
        daemon = await connect_to_daemon_and_validate(root_path, config, quiet=True)
        if daemon is not None:
            await daemon.close()
            keychain_proxy = await connect_to_keychain_and_validate(root_path, log)
        if keychain_proxy is None:
            keychain_proxy = wrap_local_keychain(Keychain(), log=log)

        try:
            legacy_keyring = Keychain(force_legacy=True)
            all_sks = await keychain_proxy.get_all_private_keys()
            all_legacy_sks = legacy_keyring.get_all_private_keys()
            set_legacy_sks = {str(x[0]) for x in all_legacy_sks}
            set_sks = {str(x[0]) for x in all_sks}
            missing_legacy_keys = set_legacy_sks - set_sks
            keys_to_migrate = [x for x in all_legacy_sks if str(x[0]) in missing_legacy_keys]
        except KeychainNotSet:
            keys_to_migrate = []

        if len(keys_to_migrate) > 0:
            print(deprecation_message)
            print(f"Found {len(keys_to_migrate)} key(s) that need migration:")
            for key, _ in keys_to_migrate:
                print(f"Fingerprint: {key.get_g1().get_fingerprint()}")

            print()
            if not prompt_yes_no("Migrate these keys?"):
                await keychain_proxy.close()
                print("Migration aborted, can't run any chia commands.")
                return False

            for sk, seed_bytes in keys_to_migrate:
                mnemonic = bytes_to_mnemonic(seed_bytes)
                await keychain_proxy.add_private_key(mnemonic)
                fingerprint = sk.get_g1().get_fingerprint()
                print(f"Added private key with public key fingerprint {fingerprint}")

            print(f"Migrated {len(keys_to_migrate)} key(s)")

            print("Verifying migration results...", end="")
            all_sks = await keychain_proxy.get_all_private_keys()
            await keychain_proxy.close()
            set_sks = {str(x[0]) for x in all_sks}
            keys_present = set_sks.issuperset(set(map(lambda x: str(x[0]), keys_to_migrate)))
            if keys_present:
                print(" Verified")
                print()
                response = prompt_yes_no("Remove key(s) from old keyring (recommended)?")
                if response:
                    legacy_keyring.delete_keys(keys_to_migrate)
                    print(f"Removed {len(keys_to_migrate)} key(s) from old keyring")
                print("Migration complete")
            else:
                print(" Failed")
                return False
            return True
        elif not forced:
            print("No keys need migration")
        if already_checked_marker.parent.exists():
            already_checked_marker.touch()
        await keychain_proxy.close()
    return True


def _clear_line_part(n: int):
    # Move backward, overwrite with spaces, then move backward again
    sys.stdout.write("\b" * n)
    sys.stdout.write(" " * n)
    sys.stdout.write("\b" * n)


def _search_derived(
    current_sk: PrivateKey,
    search_terms: Tuple[str, ...],
    path: str,
    path_indices: Optional[List[int]],
    limit: int,
    non_observer_derivation: bool,
    show_progress: bool,
    search_public_key: bool,
    search_private_key: bool,
    search_address: bool,
    prefix: str,
) -> List[str]:  # Return a subset of search_terms that were found
    """
    Performs a shallow search of keys derived from the current sk for items matching
    the provided search terms.
    """

    from chia.wallet.derive_keys import _derive_path, _derive_path_unhardened

    class DerivedSearchResultType(Enum):
        PUBLIC_KEY = "public key"
        PRIVATE_KEY = "private key"
        WALLET_ADDRESS = "wallet address"

    remaining_search_terms: Dict[str, None] = dict.fromkeys(search_terms)
    current_path: str = path
    current_path_indices: List[int] = path_indices if path_indices is not None else []
    found_search_terms: List[str] = []

    for index in range(limit):
        found_items: List[Tuple[str, str, DerivedSearchResultType]] = []
        printed_match: bool = False
        current_index_str = str(index) + ("n" if non_observer_derivation else "")
        current_path += f"{current_index_str}"
        current_path_indices.append(index)
        if show_progress:
            # Output just the current index e.g. "25" or "25n"
            sys.stdout.write(f"{current_index_str}")
            sys.stdout.flush()

        # Derive the private key
        if non_observer_derivation:
            child_sk = _derive_path(current_sk, current_path_indices)
        else:
            child_sk = _derive_path_unhardened(current_sk, current_path_indices)

        child_pk: Optional[G1Element] = None

        # Public key is needed for searching against wallet addresses or public keys
        if search_public_key or search_address:
            child_pk = child_sk.get_g1()

        address: Optional[str] = None

        if search_address:
            # Generate a wallet address using the standard p2_delegated_puzzle_or_hidden_puzzle puzzle
            # TODO: consider generating addresses using other puzzles
            address = encode_puzzle_hash(create_puzzlehash_for_pk(child_pk), prefix)

        for term in remaining_search_terms:
            found_item: Any = None
            found_item_type: Optional[DerivedSearchResultType] = None

            if search_private_key and term in str(child_sk):
                found_item = private_key_string_repr(child_sk)
                found_item_type = DerivedSearchResultType.PRIVATE_KEY
            elif search_public_key and child_pk is not None and term in str(child_pk):
                found_item = child_pk
                found_item_type = DerivedSearchResultType.PUBLIC_KEY
            elif search_address and address is not None and term in address:
                found_item = address
                found_item_type = DerivedSearchResultType.WALLET_ADDRESS

            if found_item is not None and found_item_type is not None:
                found_items.append((term, found_item, found_item_type))

        if len(found_items) > 0 and show_progress:
            print()

        for (term, found_item, found_item_type) in found_items:
            # Update remaining_search_terms and found_search_terms
            del remaining_search_terms[term]
            found_search_terms.append(term)

            print(
                f"Found {found_item_type.value}: {found_item} (HD path: {current_path})"
            )  # lgtm [py/clear-text-logging-sensitive-data]

            printed_match = True

        if len(remaining_search_terms) == 0:
            break

        # Remove the last index from the path
        current_path = current_path[: -len(str(current_index_str))]
        current_path_indices = current_path_indices[:-1]

        if show_progress:
            if printed_match:
                # Write the path (without current_index_str) since we printed out a match
                # e.g. m/12381/8444/2/
                sys.stdout.write(f"{current_path}")  # lgtm [py/clear-text-logging-sensitive-data]
            # Remove the last index from the output
            else:
                _clear_line_part(len(current_index_str))

    return found_search_terms


def search_derive(
    root_path: Path,
    private_key: Optional[PrivateKey],
    search_terms: Tuple[str, ...],
    limit: int,
    non_observer_derivation: bool,
    show_progress: bool,
    search_types: Tuple[str, ...],
    derive_from_hd_path: Optional[str],
    prefix: Optional[str],
) -> bool:
    """
    Searches for items derived from the provided private key, or if not specified,
    search each private key in the keyring.
    """

    from time import perf_counter

    start_time = perf_counter()
    private_keys: List[PrivateKey]
    remaining_search_terms: Dict[str, None] = dict.fromkeys(search_terms)  # poor man's ordered set
    search_address = "address" in search_types
    search_public_key = "public_key" in search_types
    search_private_key = "private_key" in search_types

    if prefix is None:
        config: Dict = load_config(root_path, "config.yaml")
        selected: str = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]

    if "all" in search_types:
        search_address = True
        search_public_key = True
        search_private_key = True

    if private_key is None:
        private_keys = [sk for sk, _ in Keychain().get_all_private_keys()]
    else:
        private_keys = [private_key]

    for sk in private_keys:
        current_path: str = ""
        found_terms: List[str] = []

        if show_progress:
            print(f"Searching keys derived from: {sk.get_g1().get_fingerprint()}")

        # Derive from the provided HD path
        if derive_from_hd_path is not None:
            derivation_root_sk, hd_path_root = derive_sk_from_hd_path(sk, derive_from_hd_path)

            if show_progress:
                sys.stdout.write(hd_path_root)

            # Shallow search under hd_path_root
            found_terms = _search_derived(
                derivation_root_sk,
                tuple(remaining_search_terms.keys()),
                hd_path_root,
                None,
                limit,
                non_observer_derivation,
                show_progress,
                search_public_key,
                search_private_key,
                search_address,
                prefix,
            )

            # Update remaining_search_terms
            for term in found_terms:
                del remaining_search_terms[term]

            if len(remaining_search_terms) == 0:
                # Found everything we were looking for
                break

            current_path = hd_path_root
        # Otherwise derive from well-known derivation paths
        else:
            current_path_indices: List[int] = [12381, 8444]
            path_root: str = "m/"
            for i in [12381, 8444]:
                path_root += f"{i}{'n' if non_observer_derivation else ''}/"

            if show_progress:
                # Print the path root (without last index)
                # e.g. m/12381/8444/
                sys.stdout.write(path_root)

            # 7 account levels for derived keys (0-6):
            # 0 = farmer, 1 = pool, 2 = wallet, 3 = local, 4 = backup key, 5 = singleton, 6 = pooling authentication
            for account in range(7):
                account_str = str(account) + ("n" if non_observer_derivation else "")
                current_path = path_root + f"{account_str}/"
                current_path_indices.append(account)
                if show_progress:
                    # Print the current path index
                    # e.g. 2/ (example full output: m/12381/8444/2/)
                    sys.stdout.write(f"{account_str}/")  # lgtm [py/clear-text-logging-sensitive-data]

                found_terms = _search_derived(
                    sk,
                    tuple(remaining_search_terms.keys()),
                    current_path,
                    list(current_path_indices),  # copy
                    limit,
                    non_observer_derivation,
                    show_progress,
                    search_public_key,
                    search_private_key,
                    search_address,
                    prefix,
                )

                # Update remaining_search_terms
                for found_term in found_terms:
                    del remaining_search_terms[found_term]

                if len(remaining_search_terms) == 0:
                    # Found everything we were looking for
                    break

                if show_progress:
                    # +1 to remove the trailing slash
                    _clear_line_part(1 + len(str(account_str)))

                current_path_indices = current_path_indices[:-1]

        if len(remaining_search_terms) == 0:
            # Found everything we were looking for
            break

        if show_progress:
            # +1 to remove the trailing slash
            _clear_line_part(1 + len(current_path))
            sys.stdout.flush()

    end_time = perf_counter()
    if len(remaining_search_terms) > 0:
        for term in remaining_search_terms:
            print(f"Could not find '{term}'")

    if show_progress:
        print()
        print(f"Search completed in {end_time - start_time} seconds")

    return len(remaining_search_terms) == 0


def derive_wallet_address(
    root_path: Path,
    private_key: PrivateKey,
    index: int,
    count: int,
    prefix: Optional[str],
    non_observer_derivation: bool,
    show_hd_path: bool,
):
    """
    Generate wallet addresses using keys derived from the provided private key.
    """

    if prefix is None:
        config: Dict = load_config(root_path, "config.yaml")
        selected: str = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]
    path_indices: List[int] = [12381, 8444, 2]
    wallet_hd_path_root: str = "m/"
    for i in path_indices:
        wallet_hd_path_root += f"{i}{'n' if non_observer_derivation else ''}/"
    for i in range(index, index + count):
        if non_observer_derivation:
            sk = master_sk_to_wallet_sk(private_key, uint32(i))
        else:
            sk = master_sk_to_wallet_sk_unhardened(private_key, uint32(i))
        # Generate a wallet address using the standard p2_delegated_puzzle_or_hidden_puzzle puzzle
        # TODO: consider generating addresses using other puzzles
        address = encode_puzzle_hash(create_puzzlehash_for_pk(sk.get_g1()), prefix)
        if show_hd_path:
            print(
                f"Wallet address {i} "
                f"({wallet_hd_path_root + str(i) + ('n' if non_observer_derivation else '')}): {address}"
            )
        else:
            print(f"Wallet address {i}: {address}")


def private_key_string_repr(private_key: PrivateKey):
    """Print a PrivateKey in a human-readable formats"""

    s: str = str(private_key)
    return s[len("<PrivateKey ") : s.rfind(">")] if s.startswith("<PrivateKey ") else s


def derive_child_key(
    master_sk: PrivateKey,
    key_type: Optional[str],
    derive_from_hd_path: Optional[str],
    index: int,
    count: int,
    non_observer_derivation: bool,
    show_private_keys: bool,
    show_hd_path: bool,
):
    """
    Derive child keys from the provided master key.
    """

    from chia.wallet.derive_keys import _derive_path, _derive_path_unhardened

    derivation_root_sk: Optional[PrivateKey] = None
    hd_path_root: Optional[str] = None
    current_sk: Optional[PrivateKey] = None

    # Key type was specified
    if key_type is not None:
        path_indices: List[int] = [12381, 8444]
        path_indices.append(
            {
                "farmer": 0,
                "pool": 1,
                "wallet": 2,
                "local": 3,
                "backup": 4,
                "singleton": 5,
                "pool_auth": 6,
            }[key_type]
        )

        if non_observer_derivation:
            current_sk = _derive_path(master_sk, path_indices)
        else:
            current_sk = _derive_path_unhardened(master_sk, path_indices)

        derivation_root_sk = current_sk
        hd_path_root = "m/"
        for i in path_indices:
            hd_path_root += f"{i}{'n' if non_observer_derivation else ''}/"
    # Arbitrary HD path was specified
    elif derive_from_hd_path is not None:
        derivation_root_sk, hd_path_root = derive_sk_from_hd_path(master_sk, derive_from_hd_path)

    # Derive child keys from derivation_root_sk
    if derivation_root_sk is not None and hd_path_root is not None:
        for i in range(index, index + count):
            if non_observer_derivation:
                sk = _derive_path(derivation_root_sk, [i])
            else:
                sk = _derive_path_unhardened(derivation_root_sk, [i])
            hd_path: str = (
                " (" + hd_path_root + str(i) + ("n" if non_observer_derivation else "") + ")" if show_hd_path else ""
            )
            key_type_str: Optional[str]

            if key_type is not None:
                key_type_str = key_type.capitalize()
            else:
                key_type_str = "Non-Observer" if non_observer_derivation else "Observer"

            print(f"{key_type_str} public key {i}{hd_path}: {sk.get_g1()}")
            if show_private_keys:
                print(f"{key_type_str} private key {i}{hd_path}: {private_key_string_repr(sk)}")


def private_key_for_fingerprint(fingerprint: int) -> Optional[PrivateKey]:
    unlock_keyring()
    private_keys = Keychain().get_all_private_keys()

    for sk, _ in private_keys:
        if sk.get_g1().get_fingerprint() == fingerprint:
            return sk
    return None


def get_private_key_with_fingerprint_or_prompt(fingerprint: Optional[int]):
    """
    Get a private key with the specified fingerprint. If fingerprint is not
    specified, prompt the user to select a key.
    """

    # Return the private key matching the specified fingerprint
    if fingerprint is not None:
        return private_key_for_fingerprint(fingerprint)

    fingerprints: List[int] = [pk.get_fingerprint() for pk in Keychain().get_all_public_keys()]
    while True:
        print("Choose key:")
        for i, fp in enumerate(fingerprints):
            print(f"{i+1}) {fp}")
        val = None
        while val is None:
            val = input("Enter a number to pick or q to quit: ")
            if val == "q":
                return None
            if not val.isdigit():
                val = None
            else:
                index = int(val) - 1
                if index >= len(fingerprints):
                    print("Invalid value")
                    val = None
                    continue
                else:
                    return private_key_for_fingerprint(fingerprints[index])


def private_key_from_mnemonic_seed_file(filename: Path) -> PrivateKey:
    """
    Create a private key from a mnemonic seed file.
    """

    mnemonic = filename.read_text().rstrip()
    seed = mnemonic_to_seed(mnemonic)
    return AugSchemeMPL.key_gen(seed)


def resolve_derivation_master_key(fingerprint_or_filename: Optional[Union[int, str, Path]]) -> PrivateKey:
    """
    Given a key fingerprint of file containing a mnemonic seed, return the private key.
    """

    if fingerprint_or_filename is not None and (
        isinstance(fingerprint_or_filename, str) or isinstance(fingerprint_or_filename, Path)
    ):
        return private_key_from_mnemonic_seed_file(Path(os.fspath(fingerprint_or_filename)))
    else:
        return get_private_key_with_fingerprint_or_prompt(fingerprint_or_filename)
