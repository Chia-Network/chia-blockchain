from __future__ import annotations

import json
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.cmds.passphrase_funcs import obtain_current_passphrase
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.types.signing_mode import SigningMode
from chia.util.bech32m import bech32_encode, convertbits, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.errors import KeychainException
from chia.util.file_keyring import MAX_LABEL_LENGTH
from chia.util.ints import uint32
from chia.util.keychain import (
    Keychain,
    KeyData,
    bytes_to_mnemonic,
    check_mnemonic_validity,
    generate_mnemonic,
    mnemonic_to_seed,
)
from chia.util.keyring_wrapper import KeyringWrapper
from chia.wallet.derive_keys import (
    master_pk_to_wallet_pk_unhardened,
    master_sk_to_farmer_sk,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk,
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


def generate_and_print() -> str:
    """
    Generates a seed for a private key, and prints the mnemonic to the terminal.
    """

    mnemonic = generate_mnemonic()
    print("Generating private key. Mnemonic (24 secret words):")
    print(mnemonic)
    print("Note that this key has not been added to the keychain. Run chia keys add")
    return mnemonic


def generate_and_add(label: Optional[str]) -> None:
    """
    Generates a seed for a private key, prints the mnemonic to the terminal, and adds the key to the keyring.
    """
    unlock_keyring()
    print("Generating private key")
    query_and_add_key_info(mnemonic_or_pk=generate_mnemonic(), label=label)


def query_and_add_key_info(mnemonic_or_pk: Optional[str], label: Optional[str] = None) -> None:
    unlock_keyring()
    if mnemonic_or_pk is None:
        mnemonic_or_pk = input("Enter the mnemonic/observer key you want to use: ")
    if label is None:
        label = input("Enter the label you want to assign to this key (Press Enter to skip): ")
    if len(label) == 0:
        label = None
    add_key_info(mnemonic_or_pk, label)


def add_key_info(mnemonic_or_pk: str, label: Optional[str]) -> None:
    """
    Add a private key seed or public key to the keyring, with the given mnemonic and an optional label.
    """
    unlock_keyring()
    try:
        if check_mnemonic_validity(mnemonic_or_pk):
            sk = Keychain().add_key(mnemonic_or_pk, label, private=True)
            fingerprint = sk.get_g1().get_fingerprint()
            print(f"Added private key with public key fingerprint {fingerprint}")
        else:
            pk = Keychain().add_key(mnemonic_or_pk, label, private=False)
            fingerprint = pk.get_fingerprint()
            print(f"Added public key with fingerprint {fingerprint}")

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


def format_pk_bech32_maybe(prefix: Optional[str], pubkey: str) -> str:
    return pubkey if prefix is None else bech32_encode(prefix, convertbits(list(bytes.fromhex(pubkey)), 8, 5))


def show_keys(
    root_path: Path,
    show_mnemonic: bool,
    non_observer_derivation: bool,
    json_output: bool,
    fingerprint: Optional[int],
    bech32m_prefix: Optional[str],
) -> None:
    """
    Prints all keys and mnemonics (if available).
    """
    unlock_keyring()
    config = load_config(root_path, "config.yaml")
    if fingerprint is None:
        all_keys = Keychain().get_keys(True)
    else:
        all_keys = [Keychain().get_key(fingerprint, True)]
    selected = config["selected_network"]
    prefix = config["network_overrides"]["config"][selected]["address_prefix"]

    if len(all_keys) == 0:
        if json_output:
            print(json.dumps({"keys": []}))
        else:
            print("There are no saved private keys")
        return None

    if not json_output:
        msg = "Showing all public keys derived from your master key:"
        if show_mnemonic:
            msg = "Showing all public and private keys"
        print(msg)

    def process_key_data(key_data: KeyData) -> Dict[str, Any]:
        key: Dict[str, Any] = {}
        sk = key_data.private_key if key_data.secrets is not None else None
        if key_data.label is not None:
            key["label"] = key_data.label

        key["fingerprint"] = key_data.fingerprint
        key["master_pk"] = bytes(key_data.public_key).hex()
        if sk is not None:
            key["farmer_pk"] = bytes(master_sk_to_farmer_sk(sk).get_g1()).hex()
            key["pool_pk"] = bytes(master_sk_to_pool_sk(sk).get_g1()).hex()
        else:
            key["farmer_pk"] = None
            key["pool_pk"] = None

        if non_observer_derivation:
            if sk is None:
                first_wallet_pk: Optional[G1Element] = None
            else:
                first_wallet_pk = master_sk_to_wallet_sk(sk, uint32(0)).get_g1()
        else:
            first_wallet_pk = master_pk_to_wallet_pk_unhardened(key_data.public_key, uint32(0))

        if first_wallet_pk is not None:
            wallet_address: str = encode_puzzle_hash(create_puzzlehash_for_pk(first_wallet_pk), prefix)
            key["wallet_address"] = wallet_address
        else:
            key["wallet_address"] = None

        key["non_observer"] = non_observer_derivation

        if show_mnemonic and sk is not None:
            key["master_sk"] = bytes(sk).hex()
            key["farmer_sk"] = bytes(master_sk_to_farmer_sk(sk)).hex()
            key["wallet_sk"] = bytes(master_sk_to_wallet_sk(sk, uint32(0))).hex()
            key["mnemonic"] = bytes_to_mnemonic(key_data.entropy)
        else:
            key["master_sk"] = None
            key["farmer_sk"] = None
            key["wallet_sk"] = None
            key["mnemonic"] = None

        return key

    keys = [process_key_data(key) for key in all_keys]

    if json_output:
        print(json.dumps({"keys": list(keys)}))
    else:
        for _key in keys:
            key = {k: "N/A" if v is None else v for k, v in _key.items()}
            print("")
            if "label" in key:
                print("Label:", key["label"])
            print("Fingerprint:", key["fingerprint"])
            print("Master public key (m):", format_pk_bech32_maybe(bech32m_prefix, key["master_pk"]))
            print("Farmer public key (m/12381/8444/0/0):", format_pk_bech32_maybe(bech32m_prefix, key["farmer_pk"]))
            print("Pool public key (m/12381/8444/1/0):", format_pk_bech32_maybe(bech32m_prefix, key["pool_pk"]))
            print(f"First wallet address{' (non-observer)' if key['non_observer'] else ''}: {key['wallet_address']}")
            if show_mnemonic:
                print("Master private key (m):", key["master_sk"])
                print("Farmer private key (m/12381/8444/0/0):", key["farmer_sk"])
                print("First wallet secret key (m/12381/8444/2/0):", key["wallet_sk"])
                print("  Mnemonic seed (24 secret words):")
                print(key["mnemonic"])


def delete(fingerprint: int) -> None:
    """
    Delete a key by its public key fingerprint (which is an integer).
    """
    unlock_keyring()
    print(f"Deleting private_key with fingerprint {fingerprint}")
    Keychain().delete_key_by_fingerprint(fingerprint)


def derive_pk_and_sk_from_hd_path(
    master_pk: G1Element, hd_path_root: str, master_sk: Optional[PrivateKey] = None
) -> Tuple[G1Element, Optional[PrivateKey], str]:
    """
    Derive a private key from the provided HD path. Takes a master key and HD path as input,
    and returns the derived key and the HD path that was used to derive it.
    """

    from chia.wallet.derive_keys import _derive_path, _derive_path_unhardened, _derive_pk_unhardened

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
        if non_observer and master_sk is None:
            raise ValueError("Hardened path specified for observer key")
        current_index: int = int(current_index_str[:-1]) if non_observer else int(current_index_str)

        index_and_derivation_types.append(
            (current_index, DerivationType.NONOBSERVER if non_observer else DerivationType.OBSERVER)
        )

    # Derive keys along the path
    if master_sk is not None:
        current_sk: Optional[PrivateKey] = master_sk
        assert current_sk is not None
        for current_index, derivation_type in index_and_derivation_types:
            if derivation_type == DerivationType.NONOBSERVER:
                current_sk = _derive_path(current_sk, [current_index])
            elif derivation_type == DerivationType.OBSERVER:
                current_sk = _derive_path_unhardened(current_sk, [current_index])
            else:
                raise ValueError(f"Unhandled derivation type: {derivation_type}")  # pragma: no cover
        current_pk: G1Element = current_sk.get_g1()
    else:
        current_sk = None
        current_pk = master_pk
        for current_index, _ in index_and_derivation_types:
            current_pk = _derive_pk_unhardened(current_pk, [current_index])

    return (current_pk, current_sk, "m/" + "/".join(path) + "/")


def sign(message: str, private_key: PrivateKey, hd_path: str, as_bytes: bool, json_output: bool) -> None:
    sk = derive_pk_and_sk_from_hd_path(private_key.get_g1(), hd_path, master_sk=private_key)[1]
    assert sk is not None
    data = bytes.fromhex(message) if as_bytes else bytes(message, "utf-8")
    signing_mode: SigningMode = (
        SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT if as_bytes else SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT
    )
    pubkey_hex: str = bytes(sk.get_g1()).hex()
    signature_hex: str = bytes(AugSchemeMPL.sign(sk, data)).hex()
    if json_output:
        print(
            json.dumps(
                {
                    "message": message,
                    "pubkey": pubkey_hex,
                    "signature": signature_hex,
                    "signing_mode": signing_mode.value,
                }
            )
        )
    else:
        print(f"Message: {message}")
        print(f"Public Key: {pubkey_hex}")
        print(f"Signature: {signature_hex}")
        print(f"Signing Mode: {signing_mode.value}")


def verify(message: str, public_key: str, signature: str, as_bytes: bool) -> None:
    data = bytes.fromhex(message) if as_bytes else bytes(message, "utf-8")
    pk = G1Element.from_bytes(bytes.fromhex(public_key))
    sig = G2Element.from_bytes(bytes.fromhex(signature))
    print(AugSchemeMPL.verify(pk, data, sig))


def as_bytes_from_signing_mode(signing_mode_str: str) -> bool:
    if signing_mode_str == SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT.value:
        return True
    else:
        return False


def _clear_line_part(n: int) -> None:
    # Move backward, overwrite with spaces, then move backward again
    sys.stdout.write("\b" * n)
    sys.stdout.write(" " * n)
    sys.stdout.write("\b" * n)


def _search_derived(
    current_pk: G1Element,
    current_sk: Optional[PrivateKey],
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
    Performs a shallow search of keys derived from the current pk/sk for items matching
    the provided search terms.
    """

    from chia.wallet.derive_keys import _derive_path, _derive_path_unhardened, _derive_pk_unhardened

    class DerivedSearchResultType(Enum):
        PUBLIC_KEY = "public key"
        PRIVATE_KEY = "private key"
        WALLET_ADDRESS = "wallet address"

    remaining_search_terms: Dict[str, None] = dict.fromkeys(search_terms)
    current_path: str = path
    current_path_indices: List[int] = path_indices if path_indices is not None else []
    found_search_terms: List[str] = []

    assert not (non_observer_derivation and current_sk is None)

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
            assert current_sk is not None  # semantics above guarantee this
            child_sk = _derive_path(current_sk, current_path_indices)
            if search_public_key or search_address:
                child_pk = child_sk.get_g1()
        else:
            if search_public_key or search_address:
                child_pk = _derive_pk_unhardened(current_pk, current_path_indices)
            else:
                child_pk = None
            if search_private_key and current_sk is not None:
                child_sk = _derive_path_unhardened(current_sk, current_path_indices)
            else:
                child_sk = None

        address: Optional[str] = None

        if search_address:
            # Generate a wallet address using the standard p2_delegated_puzzle_or_hidden_puzzle puzzle
            assert child_pk is not None
            # TODO: consider generating addresses using other puzzles
            address = encode_puzzle_hash(create_puzzlehash_for_pk(child_pk), prefix)

        for term in remaining_search_terms:
            found_item: Any = None
            found_item_type: Optional[DerivedSearchResultType] = None

            if search_private_key and term in str(child_sk):
                assert child_sk is not None  # semantics above guarantee this
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

        for term, found_item, found_item_type in found_items:
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
    fingerprint: Optional[int],
    search_terms: Tuple[str, ...],
    limit: int,
    non_observer_derivation: bool,
    show_progress: bool,
    search_types: Tuple[str, ...],
    derive_from_hd_path: Optional[str],
    prefix: Optional[str],
    private_key: Optional[PrivateKey],
) -> bool:
    """
    Searches for items derived from the provided private key, or if not specified,
    search each private key in the keyring.
    """

    from time import perf_counter

    start_time = perf_counter()
    remaining_search_terms: Dict[str, None] = dict.fromkeys(search_terms)  # poor man's ordered set
    search_address = "address" in search_types
    search_public_key = "public_key" in search_types
    search_private_key = "private_key" in search_types

    if prefix is None:
        config: Dict[str, Any] = load_config(root_path, "config.yaml")
        selected: str = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]

    if "all" in search_types:
        search_address = True
        search_public_key = True
        search_private_key = True

    if fingerprint is None and private_key is None:
        public_keys: List[G1Element] = Keychain().get_all_public_keys()
        private_keys: List[Optional[PrivateKey]] = [
            data.private_key if data.secrets is not None else None for data in Keychain().get_keys(include_secrets=True)
        ]
    elif fingerprint is None:
        assert private_key is not None
        public_keys = [private_key.get_g1()]
        private_keys = [private_key]
    else:
        master_key_data = Keychain().get_key(fingerprint, include_secrets=True)
        public_keys = [master_key_data.public_key]
        private_keys = [master_key_data.private_key if master_key_data.secrets is not None else None]

    for pk, sk in zip(public_keys, private_keys):
        if sk is None and non_observer_derivation:
            continue
        current_path: str = ""
        found_terms: List[str] = []

        if show_progress:
            print(f"Searching keys derived from: {pk.get_fingerprint()}")

        # Derive from the provided HD path
        if derive_from_hd_path is not None:
            derivation_root_pk, derivation_root_sk, hd_path_root = derive_pk_and_sk_from_hd_path(
                pk, derive_from_hd_path, master_sk=sk
            )

            if show_progress:
                sys.stdout.write(hd_path_root)

            # Shallow search under hd_path_root
            found_terms = _search_derived(
                derivation_root_pk,
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
                    pk,
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
    fingerprint: Optional[int],
    index: int,
    count: int,
    prefix: Optional[str],
    non_observer_derivation: bool,
    show_hd_path: bool,
    private_key: Optional[PrivateKey],
) -> None:
    """
    Generate wallet addresses using keys derived from the provided private key.
    """
    if fingerprint is not None:
        key_data: KeyData = Keychain().get_key(fingerprint, include_secrets=non_observer_derivation)
        if non_observer_derivation:
            sk = key_data.private_key
        else:
            sk = None
        pk = key_data.public_key
    else:
        assert private_key is not None
        sk = private_key
        pk = sk.get_g1()

    if prefix is None:
        config: Dict[str, Any] = load_config(root_path, "config.yaml")
        selected: str = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]
    path_indices: List[int] = [12381, 8444, 2]
    wallet_hd_path_root: str = "m/"
    for i in path_indices:
        wallet_hd_path_root += f"{i}{'n' if non_observer_derivation else ''}/"
    for i in range(index, index + count):
        if non_observer_derivation:
            assert sk is not None
            pubkey = master_sk_to_wallet_sk(sk, uint32(i)).get_g1()
        else:
            pubkey = master_pk_to_wallet_pk_unhardened(pk, uint32(i))
        # Generate a wallet address using the standard p2_delegated_puzzle_or_hidden_puzzle puzzle
        # TODO: consider generating addresses using other puzzles
        address = encode_puzzle_hash(create_puzzlehash_for_pk(pubkey), prefix)
        if show_hd_path:
            print(
                f"Wallet address {i} "
                f"({wallet_hd_path_root + str(i) + ('n' if non_observer_derivation else '')}): {address}"
            )
        else:
            print(f"Wallet address {i}: {address}")


def private_key_string_repr(private_key: PrivateKey) -> str:
    """Print a PrivateKey in a human-readable formats"""

    s = str(private_key)
    return s[len("<PrivateKey ") : s.rfind(">")] if s.startswith("<PrivateKey ") else s


def derive_child_key(
    fingerprint: Optional[int],
    key_type: Optional[str],
    derive_from_hd_path: Optional[str],
    index: int,
    count: int,
    non_observer_derivation: bool,
    show_private_keys: bool,
    show_hd_path: bool,
    private_key: Optional[PrivateKey],
    bech32m_prefix: Optional[str],
) -> None:
    """
    Derive child keys from the provided master key.
    """
    from chia.wallet.derive_keys import _derive_path, _derive_path_unhardened, _derive_pk_unhardened

    if fingerprint is not None:
        key_data: KeyData = Keychain().get_key(fingerprint, include_secrets=True)
        current_pk: G1Element = key_data.public_key
        current_sk: Optional[PrivateKey] = key_data.private_key if key_data.secrets is not None else None
    else:
        assert private_key is not None
        current_pk = private_key.get_g1()
        current_sk = private_key

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
            assert current_sk is not None  # semantics above guarantee this
            current_sk = _derive_path(current_sk, path_indices)
        else:
            if current_sk is not None:
                current_sk = _derive_path_unhardened(current_sk, path_indices)
            else:
                current_pk = _derive_pk_unhardened(current_pk, path_indices)

        derivation_root_sk = current_sk
        derivation_root_pk = current_pk
        hd_path_root = "m/"
        for i in path_indices:
            hd_path_root += f"{i}{'n' if non_observer_derivation else ''}/"
    # Arbitrary HD path was specified
    elif derive_from_hd_path is not None:
        derivation_root_pk, derivation_root_sk, hd_path_root = derive_pk_and_sk_from_hd_path(
            current_pk, derive_from_hd_path, master_sk=current_sk
        )
    else:
        raise Exception("Neither key type nor HD path was specified")

    # Derive child keys from derivation_root_sk
    for i in range(index, index + count):
        if non_observer_derivation:
            assert derivation_root_sk is not None  # semantics above guarantee this
            sk = _derive_path(derivation_root_sk, [i])
            pk = sk.get_g1()
        else:
            if derivation_root_sk is not None:
                sk = _derive_path_unhardened(derivation_root_sk, [i])
                pk = sk.get_g1()
            else:
                sk = None
                pk = _derive_pk_unhardened(derivation_root_pk, [i])
        hd_path: str = (
            " (" + hd_path_root + str(i) + ("n" if non_observer_derivation else "") + ")" if show_hd_path else ""
        )
        key_type_str: Optional[str]

        if key_type is not None:
            key_type_str = key_type.capitalize()
        else:
            key_type_str = "Non-Observer" if non_observer_derivation else "Observer"

        print(f"{key_type_str} public key {i}{hd_path}: {format_pk_bech32_maybe(bech32m_prefix, bytes(pk).hex())}")
        if show_private_keys and sk is not None:
            print(f"{key_type_str} private key {i}{hd_path}: {private_key_string_repr(sk)}")


def private_key_for_fingerprint(fingerprint: int) -> Optional[PrivateKey]:
    unlock_keyring()
    private_keys = Keychain().get_all_private_keys()

    for sk, _ in private_keys:
        if sk.get_g1().get_fingerprint() == fingerprint:
            return sk
    return None


def prompt_for_fingerprint() -> Optional[int]:
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
                    return fingerprints[index]


def get_private_key_with_fingerprint_or_prompt(
    fingerprint: Optional[int],
) -> Tuple[Optional[int], Optional[PrivateKey]]:
    """
    Get a private key with the specified fingerprint. If fingerprint is not
    specified, prompt the user to select a key.
    """

    # Return the private key matching the specified fingerprint
    if fingerprint is not None:
        return fingerprint, private_key_for_fingerprint(fingerprint)

    fingerprint_prompt = prompt_for_fingerprint()
    return fingerprint_prompt, None if fingerprint_prompt is None else private_key_for_fingerprint(fingerprint_prompt)


def private_key_from_mnemonic_seed_file(filename: Path) -> PrivateKey:
    """
    Create a private key from a mnemonic seed file.
    """

    mnemonic = filename.read_text().rstrip()
    seed = mnemonic_to_seed(mnemonic)
    return AugSchemeMPL.key_gen(seed)


def resolve_derivation_master_key(
    fingerprint_or_filename: Optional[Union[int, str, Path]]
) -> Tuple[Optional[int], Optional[PrivateKey]]:
    """
    Given a key fingerprint of file containing a mnemonic seed, return the private key.
    """

    if fingerprint_or_filename is not None and (isinstance(fingerprint_or_filename, (str, Path))):
        sk = private_key_from_mnemonic_seed_file(Path(os.fspath(fingerprint_or_filename)))
        return sk.get_g1().get_fingerprint(), sk
    else:
        return get_private_key_with_fingerprint_or_prompt(fingerprint_or_filename)
