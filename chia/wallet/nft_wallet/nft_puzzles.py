from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from clvm.casts import int_from_bytes
from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16, uint64
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo, NFTInfo
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_conditions
from chia.wallet.util.address_type import AddressType

log = logging.getLogger(__name__)
SINGLETON_TOP_LAYER_MOD = load_clvm_maybe_recompile("singleton_top_layer_v1_1.clsp")
LAUNCHER_PUZZLE = load_clvm_maybe_recompile("singleton_launcher.clsp")
NFT_STATE_LAYER_MOD = load_clvm_maybe_recompile("nft_state_layer.clsp")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
NFT_METADATA_UPDATER = load_clvm_maybe_recompile("nft_metadata_updater_default.clsp")
NFT_OWNERSHIP_LAYER = load_clvm_maybe_recompile("nft_ownership_layer.clsp")
NFT_OWNERSHIP_LAYER_HASH = NFT_OWNERSHIP_LAYER.get_tree_hash()
NFT_TRANSFER_PROGRAM_DEFAULT = load_clvm_maybe_recompile(
    "nft_ownership_transfer_program_one_way_claim_with_royalties.clsp",
)
STANDARD_PUZZLE_MOD = load_clvm_maybe_recompile("p2_delegated_puzzle_or_hidden_puzzle.clsp")
INTERMEDIATE_LAUNCHER_MOD = load_clvm_maybe_recompile("nft_intermediate_launcher.clsp")


def create_nft_layer_puzzle_with_curry_params(
    metadata: Program, metadata_updater_hash: bytes32, inner_puzzle: Program
) -> Program:
    """Curries params into nft_state_layer.clsp

    Args to curry:
        NFT_STATE_LAYER_MOD_HASH
        METADATA
        METADATA_UPDATER_PUZZLE_HASH
        INNER_PUZZLE"""
    return NFT_STATE_LAYER_MOD.curry(NFT_STATE_LAYER_MOD_HASH, metadata, metadata_updater_hash, inner_puzzle)


def create_full_puzzle_with_nft_puzzle(singleton_id: bytes32, inner_puzzle: Program) -> Program:
    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "Creating full NFT puzzle with inner puzzle: \n%r\n%r",
            singleton_id,
            inner_puzzle.get_tree_hash(),
        )
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))

    full_puzzle = SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, inner_puzzle)
    if log.isEnabledFor(logging.DEBUG):
        log.debug("Created NFT full puzzle with inner: %s", full_puzzle.get_tree_hash())
    return full_puzzle


def create_full_puzzle(
    singleton_id: bytes32, metadata: Program, metadata_updater_puzhash: bytes32, inner_puzzle: Program
) -> Program:
    if log.isEnabledFor(logging.DEBUG):
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
    if log.isEnabledFor(logging.DEBUG):
        log.debug("Created NFT full puzzle: %s", full_puzzle.get_tree_hash())
    return full_puzzle


async def get_nft_info_from_puzzle(
    nft_coin_info: NFTCoinInfo, config: Dict[str, Any], ignore_size_limit: bool = False
) -> NFTInfo:
    """
    Extract NFT info from a full puzzle
    :param nft_coin_info NFTCoinInfo in local database
    :param config Wallet config
    :param ignore_size_limit Ignore the off-chain metadata loading size limit
    :return: NFTInfo
    """
    uncurried_nft: Optional[UncurriedNFT] = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
    assert uncurried_nft is not None
    data_uris: List[str] = []

    for uri in uncurried_nft.data_uris.as_python():  # pylint: disable=E1133
        data_uris.append(str(uri, "utf-8"))
    meta_uris: List[str] = []
    for uri in uncurried_nft.meta_uris.as_python():  # pylint: disable=E1133
        meta_uris.append(str(uri, "utf-8"))
    license_uris: List[str] = []
    for uri in uncurried_nft.license_uris.as_python():  # pylint: disable=E1133
        license_uris.append(str(uri, "utf-8"))
    off_chain_metadata: Optional[str] = None
    nft_info = NFTInfo(
        encode_puzzle_hash(uncurried_nft.singleton_launcher_id, prefix=AddressType.NFT.hrp(config=config)),
        uncurried_nft.singleton_launcher_id,
        nft_coin_info.coin.name(),
        nft_coin_info.latest_height,
        uncurried_nft.owner_did,
        uncurried_nft.trade_price_percentage,
        uncurried_nft.royalty_address,
        data_uris,
        uncurried_nft.data_hash.as_python(),
        meta_uris,
        uncurried_nft.meta_hash.as_python(),
        license_uris,
        uncurried_nft.license_hash.as_python(),
        uint64(uncurried_nft.edition_total.as_int()),
        uint64(uncurried_nft.edition_number.as_int()),
        uncurried_nft.metadata_updater_hash.as_python(),
        disassemble(uncurried_nft.metadata),
        nft_coin_info.mint_height,
        uncurried_nft.supports_did,
        uncurried_nft.p2_puzzle.get_tree_hash(),
        nft_coin_info.pending_transaction,
        nft_coin_info.minter_did,
        off_chain_metadata=off_chain_metadata,
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


def construct_ownership_layer(
    current_owner: Optional[bytes32],
    transfer_program: Program,
    inner_puzzle: Program,
) -> Program:
    return NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER_HASH,
        current_owner,
        transfer_program,
        inner_puzzle,
    )


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
        did_id,
        percentage,
        p2_puzzle,
    )
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    if not royalty_puzzle_hash:
        royalty_puzzle_hash = p2_puzzle.get_tree_hash()
    transfer_program = NFT_TRANSFER_PROGRAM_DEFAULT.curry(
        singleton_struct,
        royalty_puzzle_hash,
        percentage,
    )
    nft_inner_puzzle = p2_puzzle

    nft_ownership_layer_puzzle = construct_ownership_layer(
        bytes32(did_id) if did_id else None, transfer_program, nft_inner_puzzle
    )
    return nft_ownership_layer_puzzle


def create_ownership_layer_transfer_solution(
    new_did: bytes,
    new_did_inner_hash: bytes,
    trade_prices_list: List[List[int]],
    new_puzhash: bytes32,
) -> Program:
    log.debug(
        "Creating a transfer solution with: DID:%s Inner_puzhash:%s trade_price:%s puzhash:%s",
        new_did.hex(),
        new_did_inner_hash.hex(),
        str(trade_prices_list),
        new_puzhash.hex(),
    )
    condition_list = [
        [
            51,
            new_puzhash,
            1,
            [new_puzhash],
        ],
        [-10, new_did, trade_prices_list, new_did_inner_hash],
    ]
    log.debug("Condition list raw: %r", condition_list)
    solution = Program.to(
        [
            [solution_for_conditions(condition_list)],
        ]
    )
    log.debug("Generated transfer solution: %s", solution)
    return solution


def get_metadata_and_phs(unft: UncurriedNFT, solution: SerializedProgram) -> Tuple[Program, bytes32]:
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution.to_program()))
    metadata = unft.metadata
    puzhash_for_derivation: Optional[bytes32] = None
    for condition in conditions.as_iter():
        if condition.list_len() < 2:
            # invalid condition
            continue
        condition_code = condition.first().as_int()
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
            memo = bytes32(condition.as_python()[-1][0])
            puzhash_for_derivation = memo
            log.debug("Got back puzhash from solution: %s", puzhash_for_derivation)
    assert puzhash_for_derivation
    return metadata, puzhash_for_derivation


def recurry_nft_puzzle(unft: UncurriedNFT, solution: Program, new_inner_puzzle: Program) -> Program:
    log.debug("Generating NFT puzzle with ownership support: %s", disassemble(solution))
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution))
    new_did_id = unft.owner_did
    new_puzhash = None
    for condition in conditions.as_iter():
        if condition.first().as_int() == -10:
            # this is the change owner magic condition
            new_did_id = condition.at("rf").atom
        elif condition.first().as_int() == 51:
            new_puzhash = condition.at("rf").atom
    # assert new_puzhash and new_did_id
    log.debug(f"Found NFT puzzle details: {new_did_id} {new_puzhash}")
    assert unft.transfer_program
    new_ownership_puzzle = construct_ownership_layer(new_did_id, unft.transfer_program, new_inner_puzzle)

    return new_ownership_puzzle


def get_new_owner_did(unft: UncurriedNFT, solution: Program) -> Optional[bytes32]:
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution))
    new_did_id = None
    for condition in conditions.as_iter():
        if condition.first().as_int() == -10:
            # this is the change owner magic condition
            new_did_id = condition.at("rf").atom
    return new_did_id
