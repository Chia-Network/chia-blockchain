from typing import Tuple

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint32
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.nft_wallet.nft_off_chain import (
    delete_off_chain_metadata,
    get_off_chain_metadata,
    read_off_chain_metadata,
)
from chia.wallet.nft_wallet.nft_puzzles import (
    LAUNCHER_PUZZLE_HASH,
    NFT_TRANSFER_PROGRAM_DEFAULT,
    SINGLETON_MOD_HASH,
    construct_ownership_layer,
    create_full_puzzle,
)
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions
from tests.core.make_block_generator import int_to_public_key
from tests.wallet.nft_wallet.test_nft_puzzles import NFT_METADATA_UPDATER_DEFAULT, OFFER_MOD


def make_a_new_solution() -> Tuple[Program, Program]:
    destination = int_to_public_key(2)
    p2_puzzle = puzzle_for_pk(destination)
    puzhash = p2_puzzle.get_tree_hash()
    new_did = Program.to("test").get_tree_hash()
    new_did_inner_hash = Program.to("fake").get_tree_hash()
    trade_prices_list = [[200, OFFER_MOD.get_tree_hash()]]

    condition_list = [
        [
            51,
            puzhash,
            1,
            [puzhash],
        ],
        [-10, new_did, trade_prices_list, new_did_inner_hash],
    ]
    solution = Program.to(
        [
            [],
            [],
            [
                [solution_for_conditions(condition_list)],
            ],
        ],
    )
    return p2_puzzle, solution


def make_a_new_ownership_layer_puzzle() -> Tuple[Program, Program]:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    old_did = Program.to("test_2").get_tree_hash()
    nft_id = Program.to("nft_id")
    SINGLETON_STRUCT = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    curried_tp = NFT_TRANSFER_PROGRAM_DEFAULT.curry(
        SINGLETON_STRUCT,
        innerpuz.get_tree_hash(),
        2000,
    )
    curried_inner = innerpuz
    curried_ownership_layer = construct_ownership_layer(old_did, curried_tp, curried_inner)
    return innerpuz, curried_ownership_layer


def create_test_full_puzzle() -> Program:
    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
        ("mu", ["https://bafybeigzcazxeu7epmm4vtkuadrvysv74lbzzbl2evphtae6k57yhgynp4.ipfs.nftstorage.link/6590.json"]),
        ("mh", 0x6A9CB99B7B9A987309E8DD4FD14A7CA2423858585DA68CC9EC689669DD6DD6AB),
    ]
    p2_puzzle, ownership_puzzle = make_a_new_ownership_layer_puzzle()
    puzzle = create_full_puzzle(
        Program.to(["singleton_id"]).get_tree_hash(),
        Program.to(metadata),
        NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(),
        ownership_puzzle,
    )
    return puzzle


@pytest.mark.asyncio
async def test_get_metadata() -> None:
    puzzle = create_test_full_puzzle()
    nft_coin_info: NFTCoinInfo = NFTCoinInfo(
        puzzle.get_tree_hash(),
        Coin(puzzle.get_tree_hash(), puzzle.get_tree_hash(), uint32(0)),
        None,
        puzzle,
        uint32(0),
        puzzle.get_tree_hash(),
        uint32(0),
    )
    data = await get_off_chain_metadata(nft_coin_info)
    assert data is not None

    data_1 = read_off_chain_metadata(nft_coin_info)
    assert data == data_1


@pytest.mark.asyncio
async def test_delete_metadata() -> None:
    puzzle = create_test_full_puzzle()
    nft_coin_info: NFTCoinInfo = NFTCoinInfo(
        puzzle.get_tree_hash(),
        Coin(puzzle.get_tree_hash(), puzzle.get_tree_hash(), uint32(0)),
        None,
        puzzle,
        uint32(0),
        puzzle.get_tree_hash(),
        uint32(0),
    )
    data = await get_off_chain_metadata(nft_coin_info)
    assert data is not None
    delete_off_chain_metadata(nft_coin_info.nft_id)
    assert read_off_chain_metadata(nft_coin_info) is None
