import sys

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint32
from chia.util.keychain import Keychain, bytes_to_mnemonic, generate_mnemonic, mnemonic_to_seed, unlocks_keyring
from chia.wallet.derive_keys import (
    _derive_path,
    _derive_path_unhardened,
    master_sk_to_farmer_sk,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk,
    master_sk_to_wallet_sk_unhardened,
)

keychain: Keychain = Keychain()


def generate_and_print():
    """
    Generates a seed for a private key, and prints the mnemonic to the terminal.
    """

    mnemonic = generate_mnemonic()
    print("Generating private key. Mnemonic (24 secret words):")
    print(mnemonic)
    print("Note that this key has not been added to the keychain. Run chia keys add")
    return mnemonic


@unlocks_keyring(use_passphrase_cache=True)
def generate_and_add():
    """
    Generates a seed for a private key, prints the mnemonic to the terminal, and adds the key to the keyring.
    """

    mnemonic = generate_mnemonic()
    print("Generating private key")
    add_private_key_seed(mnemonic)


@unlocks_keyring(use_passphrase_cache=True)
def query_and_add_private_key_seed():
    mnemonic = input("Enter the mnemonic you want to use: ")
    add_private_key_seed(mnemonic)


@unlocks_keyring(use_passphrase_cache=True)
def add_private_key_seed(mnemonic: str):
    """
    Add a private key seed to the keyring, with the given mnemonic.
    """

    try:
        passphrase = ""
        sk = keychain.add_private_key(mnemonic, passphrase)
        fingerprint = sk.get_g1().get_fingerprint()
        print(f"Added private key with public key fingerprint {fingerprint}")

    except ValueError as e:
        print(e)
        return None


@unlocks_keyring(use_passphrase_cache=True)
def show_all_keys(show_mnemonic: bool):
    """
    Prints all keys and mnemonics (if available).
    """
    root_path = DEFAULT_ROOT_PATH
    config = load_config(root_path, "config.yaml")
    private_keys = keychain.get_all_private_keys()
    selected = config["selected_network"]
    prefix = config["network_overrides"]["config"][selected]["address_prefix"]
    if len(private_keys) == 0:
        print("There are no saved private keys")
        return None
    msg = "Showing all public keys derived from your master seed and private key:"
    if show_mnemonic:
        msg = "Showing all public and private keys"
    print(msg)
    for sk, seed in private_keys:
        print("")
        print("Fingerprint:", sk.get_g1().get_fingerprint())
        print("Master public key (m):", sk.get_g1())
        print(
            "Farmer public key (m/12381/8444/0/0):",
            master_sk_to_farmer_sk(sk).get_g1(),
        )
        print("Pool public key (m/12381/8444/1/0):", master_sk_to_pool_sk(sk).get_g1())
        print(
            "First wallet address:",
            encode_puzzle_hash(create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(0)).get_g1()), prefix),
        )
        assert seed is not None
        if show_mnemonic:
            print("Master private key (m):", bytes(sk).hex())
            print(
                "First wallet secret key (m/12381/8444/2/0):",
                master_sk_to_wallet_sk(sk, uint32(0)),
            )
            mnemonic = bytes_to_mnemonic(seed)
            print("  Mnemonic seed (24 secret words):")
            print(mnemonic)


@unlocks_keyring(use_passphrase_cache=True)
def delete(fingerprint: int):
    """
    Delete a key by its public key fingerprint (which is an integer).
    """
    print(f"Deleting private_key with fingerprint {fingerprint}")
    keychain.delete_key_by_fingerprint(fingerprint)


@unlocks_keyring(use_passphrase_cache=True)
def sign(message: str, fingerprint: int, hd_path: str, as_bytes: bool):
    k = Keychain()
    private_keys = k.get_all_private_keys()

    path: List[uint32] = [uint32(int(i)) for i in hd_path.split("/") if i != "m"]
    for sk, _ in private_keys:
        if sk.get_g1().get_fingerprint() == fingerprint:
            for c in path:
                sk = AugSchemeMPL.derive_child_sk(sk, c)
            data = bytes.fromhex(message) if as_bytes else bytes(message, "utf-8")
            print("Public key:", sk.get_g1())
            print("Signature:", AugSchemeMPL.sign(sk, data))
            return None
    print(f"Fingerprint {fingerprint} not found in keychain")


def verify(message: str, public_key: str, signature: str):
    messageBytes = bytes(message, "utf-8")
    public_key = G1Element.from_bytes(bytes.fromhex(public_key))
    signature = G2Element.from_bytes(bytes.fromhex(signature))
    print(AugSchemeMPL.verify(public_key, messageBytes, signature))


class DerivedSearchResultType(Enum):
    PUBLIC_KEY = "public key"
    PRIVATE_KEY = "private key"
    WALLET_ADDRESS = "wallet address"


def search_derive(
    root_path: Path,
    private_key: Optional[PrivateKey],
    search_terms: Tuple[str, ...],
    limit: int,
    hardened_derivation: bool,
    no_progress: bool,
) -> bool:
    from time import perf_counter

    start_time = perf_counter()
    show_progress: bool = not no_progress
    private_keys: List[PrivateKey]
    remaining_search_terms: Dict[str, None] = dict.fromkeys(search_terms)
    if private_key is None:
        private_keys = [sk for sk, _ in keychain.get_all_private_keys()]
    else:
        private_keys = [private_key]

    for sk in private_keys:
        if show_progress:
            print(f"Searching keys derived from: {sk.get_g1().get_fingerprint()}")
        current_path: str = ""
        current_path_indices: List[int] = [12381, 8444]
        path_root: str = "m/"
        for i in [12381, 8444]:
            path_root += f"{i}{'h' if hardened_derivation else ''}/"

        if show_progress:
            sys.stdout.write(path_root)

        # 7 account levels for derived keys (0-6):
        # 0, 1, 2, 3, 4, 5, 6 farmer, pool, wallet, local, backup key, singleton, pooling authentication key numbers
        for account in range(7):
            account_str = str(account) + "h" if hardened_derivation else ""
            current_path = path_root + f"{account_str}/"
            current_path_indices.append(account)
            if show_progress:
                sys.stdout.write(f"{account_str}/")

            for index in range(limit):
                found_items: List[str] = []
                printed_match: bool = False
                index_str = str(index) + "h" if hardened_derivation else ""
                current_path += f"{index_str}"
                current_path_indices.append(index)
                if show_progress:
                    sys.stdout.write(f"{index_str}")
                    sys.stdout.flush()
                if hardened_derivation:
                    child_sk = _derive_path(sk, current_path_indices)
                else:
                    child_sk = _derive_path_unhardened(sk, current_path_indices)
                child_pk = child_sk.get_g1()
                address: str = encode_puzzle_hash(create_puzzlehash_for_pk(child_pk), "xch")

                for term in remaining_search_terms:
                    found_item: Any = None
                    found_item_type: Optional[DerivedSearchResultType] = None
                    if term in str(child_pk):
                        found_item = child_pk
                        found_item_type = DerivedSearchResultType.PUBLIC_KEY
                    elif term in str(child_sk):
                        found_item = child_sk
                        found_item_type = DerivedSearchResultType.PRIVATE_KEY
                    elif term in address:
                        found_item = address
                        found_item_type = DerivedSearchResultType.WALLET_ADDRESS

                    if found_item is not None and found_item_type is not None:
                        found_items.append(term)
                        if show_progress:
                            print()
                        print(f"Found {found_item_type.value}: {found_item} (HD path: {current_path})")
                        printed_match = True

                for k in found_items:
                    del remaining_search_terms[k]

                if len(remaining_search_terms) == 0:
                    break

                current_path = current_path[: -len(str(index_str))]
                current_path_indices = current_path_indices[:-1]

                if show_progress:
                    if printed_match:
                        sys.stdout.write(f"{current_path}")
                    else:
                        sys.stdout.write("\b" * len(str(index_str)))
                    sys.stdout.flush()

            if len(remaining_search_terms) == 0:
                break

            if show_progress:
                sys.stdout.write("\b" * (1 + len(str(account_str))))
            current_path_indices = current_path_indices[:-1]

        if len(remaining_search_terms) == 0:
            break

        if show_progress:
            sys.stdout.write("\b" * (1 + len(current_path)))
            sys.stdout.flush()
            print()
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
    hardened_derivation: bool,
    show_hd_path: bool,
):
    if prefix is None:
        config: Dict = load_config(root_path, "config.yaml")
        selected: str = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]
    path_indices: List[int] = [12381, 8444, 2]
    wallet_hd_path_root: str = "m/"
    for i in path_indices:
        wallet_hd_path_root += f"{i}{'h' if hardened_derivation else ''}/"
    for i in range(index, index + count):
        if hardened_derivation:
            sk = master_sk_to_wallet_sk(private_key, uint32(i))
        else:
            sk = master_sk_to_wallet_sk_unhardened(private_key, uint32(i))
        address = encode_puzzle_hash(create_puzzlehash_for_pk(sk.get_g1()), prefix)
        if show_hd_path:
            print(
                f"Wallet address {i} ({wallet_hd_path_root + str(i) + ('h' if hardened_derivation else '')}): {address}"
            )
        else:
            print(f"Wallet address {i}: {address}")


def private_key_string_repr(private_key: PrivateKey):
    s: str = str(private_key)
    return s[len("<PrivateKey ") : s.rfind(">")] if s.startswith("<PrivateKey ") else s


def derive_child_key(
    root_path: Path,
    master_sk: PrivateKey,
    key_type: str,
    index: int,
    count: int,
    hardened_derivation: bool,
    show_private_keys: bool,
    show_hd_path: bool,
):
    path: List[int] = [12381, 8444]
    if key_type == "farmer":
        path.append(0)
    elif key_type == "pool":
        path.append(1)
    elif key_type == "wallet":
        path.append(2)
    elif key_type == "local":
        path.append(3)
    elif key_type == "backup":
        path.append(4)
    elif key_type == "singleton":
        path.append(5)
    elif key_type == "pool_auth":
        path.append(6)

    hd_path_root: str = "m/"
    for i in path:
        hd_path_root += f"{i}{'h' if hardened_derivation else ''}/"
    for i in range(index, index + count):
        if hardened_derivation:
            sk = _derive_path(master_sk, path + [i])
        else:
            sk = _derive_path_unhardened(master_sk, path + [i])
        hd_path: str = " (" + hd_path_root + str(i) + ("h" if hardened_derivation else "") + ")" if show_hd_path else ""
        print(f"{key_type.capitalize()} public key {i}{hd_path}: {sk.get_g1()}")
        if show_private_keys:
            print(f"{key_type.capitalize()} private key {i}{hd_path}: {private_key_string_repr(sk)}")


def private_key_for_fingerprint(fingerprint: int) -> Optional[PrivateKey]:
    private_keys = keychain.get_all_private_keys()

    for sk, _ in private_keys:
        if sk.get_g1().get_fingerprint() == fingerprint:
            return sk
    return None


def get_private_key_with_fingerprint_or_prompt(fingerprint: Optional[int]):
    if fingerprint is not None:
        return private_key_for_fingerprint(fingerprint)

    fingerprints: List[int] = [pk.get_fingerprint() for pk in keychain.get_all_public_keys()]
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
    mnemonic = filename.read_text().rstrip()
    seed = mnemonic_to_seed(mnemonic, "")
    return AugSchemeMPL.key_gen(seed)


def resolve_derivation_master_key(fingerprint: Optional[int], filename: Optional[str]) -> PrivateKey:
    if filename:
        return private_key_from_mnemonic_seed_file(Path(filename))
    else:
        return get_private_key_with_fingerprint_or_prompt(fingerprint)
