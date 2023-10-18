from __future__ import annotations

from blspy import G1Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.conditions import AggSigMe
from chia.wallet.util.signer_protocol import (
    KeyHints,
    SigningInstructions,
    SigningTarget,
    Spend,
    TransactionInfo,
    UnsignedTransaction,
)


def test_signing_lifecycle() -> None:
    pubkey: G1Element = G1Element()
    message: bytes = b"message"

    coin: Coin = Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
    puzzle: Program = Program.to(1)
    solution: Program = Program.to([AggSigMe(pubkey, message).to_program()])

    coin_spend: CoinSpend = CoinSpend(coin, puzzle, solution)

    tx: UnsignedTransaction = UnsignedTransaction(
        TransactionInfo([Spend.from_coin_spend(coin_spend)]),
        SigningInstructions(
            KeyHints([], []),
            [SigningTarget(Program.to(pubkey), Program.to(message), Program.to("hook"))],
        ),
    )

    assert tx == UnsignedTransaction.from_program(tx.as_program())
