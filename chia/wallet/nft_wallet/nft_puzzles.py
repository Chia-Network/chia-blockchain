import logging
from typing import Any, Dict, List, Optional, Tuple

from blspy import G1Element
from clvm.casts import int_from_bytes
from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint64
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo, NFTInfo
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
OFFER_MOD = load_clvm("settlement_payments.clvm")
NFT_METADATA_UPDATER = load_clvm("nft_metadata_updater_default.clvm")
NFT_OWNERSHIP_LAYER = load_clvm("nft_ownership_layer.clvm")
NFT_TRANSFER_PROGRAM_DEFAULT = load_clvm("nft_ownership_transfer_program_one_way_claim_with_royalties_new.clvm")
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
    log.debug(
        "Currying with: %s %s %s %s",
        NFT_STATE_LAYER_MOD_HASH,
        inner_puzzle.get_tree_hash(),
        metadata_updater_hash,
        metadata.get_tree_hash(),
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


def get_nft_info_from_puzzle(nft_coin_info: NFTCoinInfo) -> NFTInfo:
    """
    Extract NFT info from a full puzzle
    :param nft_coin_info NFTCoinInfo in local database
    :return: NFTInfo
    """
    uncurried_nft: UncurriedNFT = UncurriedNFT.uncurry(nft_coin_info.full_puzzle)
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
        uncurried_nft.singleton_launcher_id,
        nft_coin_info.coin.name(),
        uncurried_nft.owner_did,
        uncurried_nft.owner_pubkey,
        uncurried_nft.trade_price_percentage,
        uncurried_nft.royalty_address,
        data_uris,
        uncurried_nft.data_hash.as_python(),
        meta_uris,
        uncurried_nft.meta_hash.as_python(),
        license_uris,
        uncurried_nft.license_hash.as_python(),
        uint64(uncurried_nft.series_total.as_int()),
        uint64(uncurried_nft.series_number.as_int()),
        uncurried_nft.metadata_updater_hash.as_python(),
        disassemble(uncurried_nft.metadata),
        nft_coin_info.mint_height,
        uncurried_nft.supports_did,
        nft_coin_info.pending_transaction,
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


def create_ownership_layer_puzzle(
    nft_id: bytes32,
    did_id: bytes,
    p2_puzzle: Program,
    percentage: uint16,
    royalty_puzzle_hash: Optional[bytes32] = None,
) -> Program:
    log.debug(
        "Creating ownership layer puzzle with NFT_ID: %s DID_ID: %s Royalty_Percentage: %d P2_puzzle: %s",
        nft_id.hex(),
        did_id.hex(),
        percentage,
        p2_puzzle,
    )
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    if not royalty_puzzle_hash:
        royalty_puzzle_hash = p2_puzzle.get_tree_hash()
    transfer_program = NFT_TRANSFER_PROGRAM_DEFAULT.curry(
        STANDARD_PUZZLE_MOD.get_tree_hash(),
        singleton_struct,
        royalty_puzzle_hash,
        percentage,
        OFFER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
    )
    nft_inner_puzzle = p2_puzzle

    nft_ownership_layer_puzzle = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(), did_id, transfer_program, nft_inner_puzzle
    )
    return nft_ownership_layer_puzzle


def create_ownership_layer_transfer_solution(
    new_did: bytes,
    new_did_inner_hash: bytes32,
    trade_prices_list: List[List[int]],
    new_pubkey: G1Element,
) -> Program:
    log.debug(
        "Creating a transfer solution with: DID:%s Inner_puzhash:%s trade_price:%s pubkey:%s",
        new_did.hex(),
        new_did_inner_hash.hex(),
        str(trade_prices_list),
        new_pubkey,
    )
    puzhash = STANDARD_PUZZLE_MOD.curry(new_pubkey).get_tree_hash()
    condition_list = [
        [
            51,
            puzhash,
            1,
            [puzhash],
        ],
        [-10, new_did, trade_prices_list, new_pubkey, [new_did_inner_hash]],
    ]
    log.debug("Condition list raw: %r", condition_list)
    solution = Program.to(
        [
            [solution_for_conditions(condition_list)],
            1,
        ]
    )
    log.debug("Generated transfer solution: %s", solution)
    return solution


def get_metadata_and_phs(unft: UncurriedNFT, puzzle: Program, solution: SerializedProgram) -> Tuple[Program, bytes32]:
    full_solution: Program = Program.from_bytes(bytes(solution))
    delegated_puz_solution: Program = Program.from_bytes(bytes(solution)).rest().rest().first().first()
    if delegated_puz_solution.rest().as_python() == b"":
        conditions = puzzle.run(full_solution)
    else:
        conditions = delegated_puz_solution.rest().first().rest()
    metadata = unft.metadata
    puzhash_for_derivation: Optional[bytes32] = None
    for condition in conditions.as_iter():
        if condition.list_len() < 2:
            # invalid condition
            continue
        condition_code = int_from_bytes(condition.first().atom)
        log.debug("Checking condition code: %r", condition_code)
        if condition_code == -24:
            # metadata update
            metadata = update_metadata(metadata, condition)
            metadata = Program.to(metadata)
        elif condition_code == 51 and int_from_bytes(condition.rest().rest().first().atom) == 1:
            # destination puzhash
            if puzhash_for_derivation is not None:
                # ignore duplicated create coin conditions
                continue
            puzhash = bytes32(condition.rest().first().atom)
            memo = bytes32(condition.as_python()[-1][0])
            if memo != puzhash:
                puzhash_for_derivation = memo
            else:
                puzhash_for_derivation = puzhash
            log.debug("Got back puzhash from solution: %s", puzhash_for_derivation)
    assert puzhash_for_derivation
    return metadata, puzhash_for_derivation


def recurry_nft_puzzle(unft: UncurriedNFT, solution: Program) -> Program:
    log.debug("Generating NFT puzzle with ownership support: %s", solution)
    conditions = solution.at("frfr").as_iter()
    for change_did_condition in conditions:
        if change_did_condition.first().as_int() == -10:
            # this is the change owner magic condition
            break
    else:
        raise ValueError("Not a valid puzzle")
    new_did_id = change_did_condition.at("rf").atom
    # trade_list_price = change_did_condition.at("rrf").as_python()
    # new_did_inner_hash = change_did_condition.at("rrrrf").atom
    new_pub_key = G1Element.from_bytes(change_did_condition.at("rrrf").atom)
    log.debug(f"Found NFT puzzle details: {new_did_id.hex()} ")
    inner_puzzle = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(),
        new_did_id,
        unft.transfer_program,
        STANDARD_PUZZLE_MOD.curry(new_pub_key),
    )
    return inner_puzzle
