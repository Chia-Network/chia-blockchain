import logging
from typing import Any, Dict, List, Tuple

from blspy import G1Element
from clvm.casts import int_from_bytes
from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint64
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_conditions

log = logging.getLogger(__name__)
SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
NFT_TRANSFER_PROGRAM = load_clvm("nft_transfer_program.clvm")
OFFER_MOD = load_clvm("settlement_payments.clvm")
NFT_METADATA_UPDATER = load_clvm("nft_metadata_updater_default.clvm")
NFT_OWNERSHIP_LAYER = load_clvm("nft_ownership_layer.clvm")
NFT_TRANSFER_PROGRAM_DEFAULT = load_clvm("nft_ownership_transfer_program_one_way_claim_with_royalties.clvm")
NFT_INNER_INNERPUZ = load_clvm("nft_v1_innerpuz.clvm")
STANDARD_PUZZLE_MOD = load_clvm("p2_delegated_puzzle_or_hidden_puzzle.clvm")


def create_nft_layer_puzzle_with_curry_params(
    metadata: Program, metadata_updater_hash: bytes32, inner_puzzle: Program
) -> Program:
    """Curries params into nft_state_layer.clvm

    Args to curry:
        NFT_STATE_LAYER_MOD_HASH
        METADATA
        METADATA_UPDATER_PUZZLE_HASH
        INNER_PUZZLE"""
    log.debug(
        "Creating nft layer puzzle curry: mod_hash: %s, metadata: %r, metadata_hash: %s",
        NFT_STATE_LAYER_MOD_HASH,
        metadata,
        metadata_updater_hash,
    )
    return NFT_STATE_LAYER_MOD.curry(NFT_STATE_LAYER_MOD_HASH, metadata, metadata_updater_hash, inner_puzzle)


def create_full_puzzle_with_nft_puzzle(singleton_id: bytes32, inner_puzzle: Program) -> Program:
    log.debug(
        "Creating full NFT puzzle with inner puzzle: \n%r\n%r",
        singleton_id,
        inner_puzzle.get_tree_hash(),
    )
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))

    full_puzzle = SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, inner_puzzle)
    log.debug("Created NFT full puzzle with inner: %s", full_puzzle.get_tree_hash())
    return full_puzzle


def create_full_puzzle(
    singleton_id: bytes32, metadata: Program, metadata_updater_puzhash: bytes32, inner_puzzle: Program
) -> Program:
    log.debug(
        "Creating full NFT puzzle with: \n%r\n%r\n%r\n%r",
        singleton_id,
        metadata.get_tree_hash(),
        metadata_updater_puzhash,
        inner_puzzle.get_tree_hash(),
    )
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    singleton_inner_puzzle = create_nft_layer_puzzle_with_curry_params(metadata, metadata_updater_puzhash, inner_puzzle)

    full_puzzle = SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, singleton_inner_puzzle)
    log.debug("Created NFT full puzzle: %s", full_puzzle.get_tree_hash())
    return full_puzzle


def get_nft_info_from_puzzle(puzzle: Program, nft_coin: Coin) -> NFTInfo:
    """
    Extract NFT info from a full puzzle
    :param puzzle: NFT full puzzle
    :param nft_coin: NFT coin
    :return: NFTInfo
    """
    uncurried_nft: UncurriedNFT = UncurriedNFT.uncurry(puzzle)
    data_uris: List[str] = []
    for uri in uncurried_nft.data_uris.as_python():
        data_uris.append(str(uri, "utf-8"))
    meta_uris: List[str] = []
    for uri in uncurried_nft.meta_uris.as_python():
        meta_uris.append(str(uri, "utf-8"))
    license_uris: List[str] = []
    for uri in uncurried_nft.license_uris.as_python():
        license_uris.append(str(uri, "utf-8"))

    nft_info = NFTInfo(
        uncurried_nft.singleton_launcher_id.as_python(),
        nft_coin.name(),
        uncurried_nft.owner_did,
        uncurried_nft.trade_price_percentage,
        data_uris,
        uncurried_nft.data_hash.as_python(),
        meta_uris,
        uncurried_nft.meta_hash.as_python(),
        license_uris,
        uncurried_nft.license_hash.as_python(),
        uint64(uncurried_nft.series_total.as_int()),
        uint64(uncurried_nft.series_total.as_int()),
        uncurried_nft.metadata_updater_hash.as_python(),
        disassemble(uncurried_nft.metadata),
    )
    return nft_info


def metadata_to_program(metadata: Dict[bytes, Any]) -> Program:
    """
    Convert the metadata dict to a Chialisp program
    :param metadata: User defined metadata
    :return: Chialisp program
    """
    kv_list = []
    for key, value in metadata.items():
        kv_list.append((key, value))
    program: Program = Program.to(kv_list)
    return program


def program_to_metadata(program: Program) -> Dict[bytes, Any]:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for kv_pair in program.as_iter():
        metadata[kv_pair.first().as_atom()] = kv_pair.rest().as_python()
    return metadata


def prepend_value(key: bytes, value: Program, metadata: Dict[bytes, Any]) -> None:
    """
    Prepend a value to a list in the metadata
    :param key: Key of the field
    :param value: Value want to add
    :param metadata: Metadata
    :return:
    """

    if value != Program.to(0):
        if metadata[key] == b"":
            metadata[key] = [value.as_python()]
        else:
            metadata[key].insert(0, value.as_python())


def update_metadata(metadata: Program, update_condition: Program) -> Program:
    """
    Apply conditions of metadata updater to the previous metadata
    :param metadata: Previous metadata
    :param update_condition: Update metadata conditions
    :return: Updated metadata
    """
    new_metadata: Dict[bytes, Any] = program_to_metadata(metadata)
    uri: Program = update_condition.rest().rest().first()
    prepend_value(uri.first().as_python(), uri.rest(), new_metadata)
    return metadata_to_program(new_metadata)


def create_ownership_layer_puzzle(nft_id: bytes32, did_id: bytes32, p2_puzzle: Program, percentage: uint16) -> Program:
    log.debug(f"Creating ownership layer puzzle with {nft_id=} {did_id=} {percentage=} {p2_puzzle=}")
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    transfer_program = NFT_TRANSFER_PROGRAM_DEFAULT.curry(
        singleton_struct,
        p2_puzzle.get_tree_hash(),
        percentage,
        OFFER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
    )
    nft_inner_puzzle = NFT_INNER_INNERPUZ.curry(
        STANDARD_PUZZLE_MOD.get_tree_hash(), NFT_INNER_INNERPUZ.get_tree_hash(), p2_puzzle
    )
    nft_ownership_layer_puzzle = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(), did_id, transfer_program, nft_inner_puzzle
    )
    return nft_ownership_layer_puzzle


def create_ownership_layer_transfer_solution(
    new_did: bytes32,
    new_did_inner_hash: bytes,
    trade_prices_list: List[List[int]],
    new_pubkey: G1Element,
    conditions: List[Any] = [],
) -> Program:
    log.debug(f"Creating a transfer solution with: {new_did=} {new_did_inner_hash=} {trade_prices_list=} {new_pubkey=}")
    condition_list = [new_did, [trade_prices_list], new_pubkey, [new_did_inner_hash], 0, 0, conditions]
    log.debug("Condition list raw: %r", condition_list)
    solution = Program.to([[solution_for_conditions(condition_list)]])
    log.debug("Generated transfer solution: %s", disassemble(solution))
    return solution


def get_metadata_and_p2_puzhash(unft: UncurriedNFT, solution: Program) -> Tuple[Program, bytes32]:
    if unft.owner_did:
        conditions = solution.at("ffffrrrrrrf").as_iter()
    else:
        conditions = solution.rest().first().rest().as_iter()
    metadata = unft.metadata
    for condition in conditions:
        log.debug("Checking solution condition: %s", disassemble(condition))
        if condition.list_len() < 2:
            # invalid condition
            continue

        condition_code = int_from_bytes(condition.first().atom)
        log.debug("Checking condition code: %r", condition_code)
        if condition_code == -24:
            # metadata update
            # (-24 (meta updater puzzle) url)
            metadata_list = list(metadata.as_python())
            new_metadata = []
            for metadata_entry in metadata_list:
                key = metadata_entry[0]
                if key == b"u":
                    new_metadata.append((b"u", [condition.rest().rest().first().atom] + list(metadata_entry[1:])))
                else:
                    new_metadata.append((b"h", metadata_entry[1]))
            metadata = Program.to(new_metadata)
        elif condition_code == 51 and int_from_bytes(condition.rest().rest().first().atom) == 1:
            puzhash = bytes32(condition.rest().first().atom)
            log.debug("Got back puzhash from solution: %s", puzhash)
    assert puzhash
    return metadata, puzhash


def generate_new_puzzle(unft, new_p2_puzzle, metadata, solution):
    if not unft.owner_did:
        inner_puzzle = new_p2_puzzle
    else:
        new_did_id = solution.at("ffffrf").atom
        new_did_inner_hash = solution.at("ffffrrff").atom
        inner_puzzle = create_ownership_layer_puzzle(
            unft.singleton_launcher_id, new_did_id, new_did_inner_hash, unft.trade_price_percentage
        )
    return create_full_puzzle(
        unft.singleton_launcher_id, Program.to(metadata), unft.metadata_updater_hash, inner_puzzle
    )
