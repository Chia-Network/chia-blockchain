from __future__ import annotations

import pytest
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trade_manager import TradeManager


@pytest.mark.anyio
async def test_trade_manager_unknown_proofs_checker() -> None:
    trade_manager = object.__new__(TradeManager)
    asset_id = bytes32.zeros
    with pytest.raises(ValueError, match="Unknown proofs checker for CRCAT"):
        await trade_manager.check_for_requested_payment_modifications(
            requested_payments={asset_id: []},
            driver_dict={
                asset_id: PuzzleInfo(
                    {
                        "type": AssetType.CAT.value,
                        "tail": "0x" + asset_id.hex(),
                        "also": {
                            "type": AssetType.CR.value,
                            "authorized_providers": ["0x" + asset_id.hex()],
                            "proofs_checker": Program.to([1]),
                        },
                    }
                )
            },
            taking=False,
        )
