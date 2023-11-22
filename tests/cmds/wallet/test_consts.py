from __future__ import annotations

from chia_rs import Coin, G2Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType

FINGERPRINT: str = "123456"
FINGERPRINT_ARG: str = f"-f{FINGERPRINT}"
CAT_FINGERPRINT: str = "789101"
CAT_FINGERPRINT_ARG: str = f"-f{CAT_FINGERPRINT}"
WALLET_ID: int = 1
WALLET_ID_ARG: str = f"-i{WALLET_ID}"
bytes32_hexstr = "0x6262626262626262626262626262626262626262626262626262626262626262"


def get_bytes32(bytes_index: int) -> bytes32:
    return bytes32([bytes_index] * 32)


STD_TX = TransactionRecord(
    confirmed_at_height=uint32(1),
    created_at_time=uint64(1234),
    to_puzzle_hash=get_bytes32(1),
    amount=uint64(12345678),
    fee_amount=uint64(1234567),
    confirmed=False,
    sent=uint32(0),
    spend_bundle=SpendBundle([], G2Element()),
    additions=[Coin(get_bytes32(1), get_bytes32(2), uint64(12345678))],
    removals=[Coin(get_bytes32(2), get_bytes32(4), uint64(12345678))],
    wallet_id=uint32(1),
    sent_to=[("aaaaa", uint8(1), None)],
    trade_id=None,
    type=uint32(TransactionType.OUTGOING_TX.value),
    name=get_bytes32(2),
    memos=[(get_bytes32(3), [bytes([4] * 32)])],
    valid_times=ConditionValidTimes(),
)
