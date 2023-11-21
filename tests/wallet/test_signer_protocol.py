from __future__ import annotations

import dataclasses

from blspy import G1Element

from chia.types.blockchain_format.coin import Coin as ConsensusCoin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import AggSigMe
from chia.wallet.util.signer_protocol import (
    KeyHints,
    SigningInstructions,
    SigningTarget,
    Spend,
    TransactionInfo,
    UnsignedTransaction,
    clvm_serialization_mode,
)


def test_signing_lifecycle() -> None:
    pubkey: G1Element = G1Element()
    message: bytes = b"message"

    coin: ConsensusCoin = ConsensusCoin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
    puzzle: Program = Program.to(1)
    solution: Program = Program.to([AggSigMe(pubkey, message).to_program()])

    coin_spend: CoinSpend = CoinSpend(coin, puzzle, solution)

    tx: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([Spend.from_coin_spend(coin_spend)]),
        SigningInstructions(
            KeyHints([], []),
            [SigningTarget(bytes(pubkey), message, bytes32([1] * 32))],
        ),
    )

    assert tx == UnsignedTransaction.from_program(Program.from_bytes(bytes(tx.as_program())))

    as_json_dict = {
        "coin": {
            "parent_coin_id": "0x" + tx.transaction_info.spends[0].coin.parent_coin_id.hex(),
            "puzzle_hash": "0x" + tx.transaction_info.spends[0].coin.puzzle_hash.hex(),
            "amount": tx.transaction_info.spends[0].coin.amount,
        },
        "puzzle": "0x" + bytes(tx.transaction_info.spends[0].puzzle).hex(),
        "solution": "0x" + bytes(tx.transaction_info.spends[0].solution).hex(),
    }
    assert tx.transaction_info.spends[0].to_json_dict() == as_json_dict

    # Test from_json_dict with the special case where it encounters the as_program serialization in the middle of JSON
    assert tx.transaction_info.spends[0] == Spend.from_json_dict(
        {
            "coin": bytes(tx.transaction_info.spends[0].coin.as_program()).hex(),
            "puzzle": bytes(tx.transaction_info.spends[0].puzzle).hex(),
            "solution": bytes(tx.transaction_info.spends[0].solution).hex(),
        }
    )

    # Test the optional serialization as blobs
    with clvm_serialization_mode(True):
        assert (
            tx.transaction_info.spends[0].to_json_dict()
            == bytes(tx.transaction_info.spends[0].as_program()).hex()  # type: ignore[comparison-overlap]
        )

    # Make sure it's still a dict if using a Streamable object
    @streamable
    @dataclasses.dataclass(frozen=True)
    class TempStreamable(Streamable):
        streamable_key: Spend

    with clvm_serialization_mode(True):
        assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {
            "streamable_key": bytes(tx.transaction_info.spends[0].as_program()).hex()
        }

    with clvm_serialization_mode(False):
        assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {"streamable_key": as_json_dict}

    with clvm_serialization_mode(False):
        assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {"streamable_key": as_json_dict}
        with clvm_serialization_mode(True):
            assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {
                "streamable_key": bytes(tx.transaction_info.spends[0].as_program()).hex()
            }
            with clvm_serialization_mode(False):
                assert TempStreamable(tx.transaction_info.spends[0]).to_json_dict() == {"streamable_key": as_json_dict}

    streamable_blob = bytes(tx.transaction_info.spends[0])
    with clvm_serialization_mode(True):
        clvm_streamable_blob = bytes(tx.transaction_info.spends[0])

    assert streamable_blob != clvm_streamable_blob
    Spend.from_bytes(streamable_blob)
    Spend.from_bytes(clvm_streamable_blob)
    assert Spend.from_bytes(streamable_blob) == Spend.from_bytes(clvm_streamable_blob) == tx.transaction_info.spends[0]

    with clvm_serialization_mode(False):
        assert bytes(tx.transaction_info.spends[0]) == streamable_blob

    inside_streamable_blob = bytes(TempStreamable(tx.transaction_info.spends[0]))
    with clvm_serialization_mode(True):
        inside_clvm_streamable_blob = bytes(TempStreamable(tx.transaction_info.spends[0]))

    assert inside_streamable_blob != inside_clvm_streamable_blob
    assert (
        TempStreamable.from_bytes(inside_streamable_blob)
        == TempStreamable.from_bytes(inside_clvm_streamable_blob)
        == TempStreamable(tx.transaction_info.spends[0])
    )
