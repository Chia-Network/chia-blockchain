from typing import Dict, List, Optional

from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.full_block import FullBlock


def coin_to_json(coin: Coin) -> Dict:
    coin_id: bytes32 = coin.name()
    coin_json: Dict = coin.to_json_dict()
    coin_json["coin_id"] = coin_id
    return coin_json


def coin_from_json(coin_json: Dict) -> Coin:
    if "coin_id" in coin_json:
        del coin_json["coin_id"]
    return Coin.from_json_dict(coin_json)


def coin_record_to_json(coin_record: CoinRecord) -> Dict:
    coin_id: bytes32 = coin_record.coin.name()
    coin_record_json: Dict = coin_record.to_json_dict()
    coin_record_json["coin"]["coin_id"] = coin_id
    return coin_record_json


def coin_record_from_json(coin_record_json: Dict) -> CoinRecord:
    if "coin_id" in coin_record_json["coin"]:
        del coin_record_json["coin"]["coin_id"]
    return CoinRecord.from_json_dict(coin_record_json)


def block_record_to_json(block_record: BlockRecord) -> Dict:
    br_json: Dict = block_record.to_json_dict()
    new_reward_claims: Optional[List[Dict]] = None
    if block_record.reward_claims_incorporated is not None:
        new_reward_claims = [coin_to_json(rc) for rc in block_record.reward_claims_incorporated]
    br_json["reward_claims_incorporated"] = new_reward_claims
    return br_json


def block_record_from_json(block_record_json: Dict) -> BlockRecord:
    if "reward_claims_incorporated" in block_record_json and block_record_json["reward_claims_incorporated"] is not None:
        new_reward_claims: List[Coin] = []
        for coin in block_record_json["reward_claims_incorporated"]:
            coin_copy = coin.copy()
            if "coin_id" in coin_copy:
                del coin_copy["coin_id"]
            new_reward_claims.append(coin_copy)
        block_record_json["reward_claims_incorporated"] = new_reward_claims
    return BlockRecord.from_json_dict(block_record_json)


def full_block_to_json(full_block: FullBlock) -> Dict:
    fb_json: Dict = full_block.to_json_dict()
    new_reward_claims: Optional[List[Dict]] = None
    if full_block.transactions_info is not None:
        new_reward_claims = [coin_to_json(rc) for rc in full_block.transactions_info.reward_claims_incorporated]
    fb_json["transactions_info"]["reward_claims_incorporated"] = new_reward_claims
    return fb_json


def full_block_from_json(full_block_json: Dict) -> FullBlock:
    if "transactions_info" in full_block_json and full_block_json["transactions_info"] is not None:
        new_reward_claims: List[Dict] = []
        for coin in full_block_json["transactions_info"]["reward_claims_incorporated"]:
            coin_copy = coin.copy()
            if "coin_id" in coin_copy:
                del coin_copy["coin_id"]
            new_reward_claims.append(coin_copy)
        full_block_json["transactions_info"]["reward_claims_incorporated"] = new_reward_claims
    return FullBlock.from_json_dict(full_block_json)


def coin_spend_to_json(coin_spend: CoinSpend) -> Dict:
    cs_json: Dict = coin_spend.to_json_dict()
    cs_json["coin"] = coin_to_json(coin_spend.coin)
    return cs_json


def coin_spend_from_json(coin_spend_json: Dict) -> CoinSpend:
    if "coin_id" in coin_spend_json["coin"]:
        del coin_spend_json["coin"]["coin_id"]
    return CoinSpend.from_json_dict(coin_spend_json)
