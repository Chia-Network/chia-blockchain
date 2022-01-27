
from typing import Any, Dict, List, Set
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.wallet.puzzles.cc_loader import CC_MOD
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk
from chia.types.blockchain_format.sized_bytes import bytes32
from blspy import PrivateKey, G1Element


def get_cat_puzzle_hash(asset_id: str, xch_puzzle_hash: str) -> str:
    tail_hash = bytes.fromhex(asset_id.lstrip("0x"))
    xch_puzzle_hash = bytes.fromhex(xch_puzzle_hash.lstrip("0x"))
    cat_puzzle_hash = CC_MOD.curry(CC_MOD.get_tree_hash(), tail_hash, xch_puzzle_hash).get_tree_hash(xch_puzzle_hash)
    return "0x" + cat_puzzle_hash.hex()


def convert_to_coin(raw_coin: Dict) -> Coin:
    if type(raw_coin) != dict:
        raise Exception(f"Expected coin is a dict, got {raw_coin}")
    if not 'puzzle_hash' in raw_coin:
        raise Exception(f"Coin is missing puzzle_hash field: {raw_coin}")
    if not 'puzzle_hash' in raw_coin:
        raise Exception(f"Coin is missing puzzle_hash field: {raw_coin}")
    coin = Coin(
        parent_coin_info=bytes.fromhex(raw_coin["parent_coin_info"].lstrip("0x")),
        puzzle_hash=bytes.fromhex(raw_coin["puzzle_hash"].lstrip("0x")),
        amount=int(raw_coin["amount"]),
    )
    return coin


def convert_to_cat_coins(
    target_asset_id: str,
    sender_private_key: PrivateKey,
    raw_cat_coins_pool: List[Dict],
) -> Set[Coin]:
    """Convert a list of raw coin dicts into a set of Coin objects

    Args:
        target_asset_id (str): expected CAT asset ID (used to validate the input coins list)
        sender_private_key (PrivateKey): the target sender's derived private key
        raw_cat_coins_pool (List[Dict]): the list of raw coin dicts

    Returns:
        Set[Coin]: set of Coin objects
    """

    sender_public_key_bytes = bytes(sender_private_key.get_g1())
    sender_public_key: G1Element = G1Element.from_bytes(sender_public_key_bytes)

    sender_xch_puzzle: Program = puzzle_for_pk(sender_public_key)
    sender_xch_puzzle_hash: bytes32 = sender_xch_puzzle.get_tree_hash()
    sender_cat_puzzle_hash = get_cat_puzzle_hash(
        asset_id=target_asset_id.hex(),
        xch_puzzle_hash=sender_xch_puzzle_hash.hex(),
    )

    if type(raw_cat_coins_pool) != list:
        raise Exception(f"Expected raw_cat_coins_pool is a list, got {raw_cat_coins_pool}")

    cat_coins_pool: Set[Coin] = set()
    for raw_coin in raw_cat_coins_pool:
        coin: Coin = convert_to_coin(raw_coin=raw_coin)
        puzzle_hash = coin.puzzle_hash.hex()
        if puzzle_hash != sender_cat_puzzle_hash:
            raise Exception(f"Inconsistent coin in raw_cat_coins_pool: {puzzle_hash} != {sender_cat_puzzle_hash}")
        cat_coins_pool.add(coin)
    return cat_coins_pool


def convert_to_coin_spend(raw_coin_spend: Dict) -> CoinSpend:
    if type(raw_coin_spend) != dict:
        raise Exception(f"Expected raw_coin_spend is a dict, got {raw_coin_spend}")
    if not 'coin' in raw_coin_spend:
        raise Exception(f"CoinSpend is missing coin field: {raw_coin_spend}")
    if not 'puzzle_reveal' in raw_coin_spend:
        raise Exception(f"CoinSpend is missing puzzle_reveal field: {raw_coin_spend}")
    if not 'solution' in raw_coin_spend:
        raise Exception(f"CoinSpend is missing solution field: {raw_coin_spend}")

    return CoinSpend(
        coin=convert_to_coin(raw_coin=raw_coin_spend["coin"]),
        puzzle_reveal=SerializedProgram.fromhex(raw_coin_spend["puzzle_reveal"]),
        solution=SerializedProgram.fromhex(raw_coin_spend["solution"]),
    )


def convert_to_parent_coin_spends(
    raw_parent_coin_spends: Dict[str, Dict[str, Any]],
) -> Dict[str, CoinSpend]:
    """Convert a dict of raw coin_name->ParentCoinSpend's dict into coin_name->CoinSpend

    Args:
        raw_parent_coin_spends (Dict[Dict]): raw dict of dicts
    """
    if type(raw_parent_coin_spends) != dict:
        raise Exception(f"Expected raw_parent_coin_spends is a dict, got {raw_parent_coin_spends}")

    parent_coin_spends: Dict[CoinSpend] = {}
    for name, raw_coin_spend in raw_parent_coin_spends.items():
        coin_spend: CoinSpend = convert_to_coin_spend(raw_coin_spend=raw_coin_spend)
        parent_coin_spends[name] = coin_spend
    return parent_coin_spends