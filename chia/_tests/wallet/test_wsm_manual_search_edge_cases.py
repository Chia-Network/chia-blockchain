from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from chia_rs import Coin
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.wallet.did_wallet.did_wallet_puzzles import DIDMetadata, DIDRecoveryPuzzle, RecoveryList
from chia.wallet.puzzles.puzzle_drivers import ACSPuzzle
from chia.wallet.puzzles.singleton_drivers import SingletonPuzzle
from chia.wallet.wallet_state_manager import WalletStateManager


@pytest.mark.anyio
async def test_manual_did_search_error_paths() -> None:
    wsm = object.__new__(WalletStateManager)
    peer = MagicMock()
    wsm.wallet_node = MagicMock()
    wsm.wallet_node.get_full_node_peer = MagicMock(return_value=peer)

    coin = Coin(bytes32.zeros, bytes32.zeros, uint64(1))
    coin_state = MagicMock()
    coin_state.coin = coin

    # Not a singleton at all
    non_singleton_spend = make_spend(coin, ACSPuzzle().program, Program.to([]))
    wsm.get_latest_singleton_coin_spend = AsyncMock(return_value=(non_singleton_spend, coin_state))  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="The coin is not a DID"):
        await wsm.manual_did_search(bytes32.zeros)

    # Singleton of ACS — not a DID recovery puzzle
    acs_singleton = SingletonPuzzle(launcher_id=bytes32.zeros, inner_puzzle=ACSPuzzle())
    acs_spend = make_spend(coin, acs_singleton.program, Program.to([[None, None, 1], 1, []]))
    wsm.get_latest_singleton_coin_spend = AsyncMock(return_value=(acs_spend, coin_state))  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="The coin is not a DID"):
        await wsm.manual_did_search(bytes32.zeros)

    # DID recovery with ACS custody — not a standard puzzle
    did_inner = DIDRecoveryPuzzle(
        inner_puzzle=ACSPuzzle(),
        self_launcher_id=bytes32.zeros,
        metadata=DIDMetadata(),
        recovery_list=RecoveryList(ids=[]),
        num_of_backup_ids_needed=uint64(0),
    )
    did_singleton = SingletonPuzzle(launcher_id=bytes32.zeros, inner_puzzle=did_inner)
    did_spend = make_spend(coin, did_singleton.program, Program.to([[None, None, 1], 1, []]))
    wsm.get_latest_singleton_coin_spend = AsyncMock(return_value=(did_spend, coin_state))  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="Do not recognize DID custody"):
        await wsm.manual_did_search(bytes32.zeros)


@pytest.mark.anyio
async def test_manual_nft_search_launcher_missing() -> None:
    wsm = object.__new__(WalletStateManager)
    peer = MagicMock()
    wsm.wallet_node = MagicMock()
    wsm.wallet_node.get_full_node_peer = MagicMock(return_value=peer)
    wsm.config = {}

    coin = Coin(bytes32.zeros, bytes32.zeros, uint64(1))
    spend = make_spend(coin, ACSPuzzle().program, Program.to([]))
    coin_state = MagicMock()
    coin_state.coin = coin
    coin_state.created_height = uint32(1)
    wsm.get_latest_singleton_coin_spend = AsyncMock(return_value=(spend, coin_state))  # type: ignore[method-assign]
    wsm.wallet_node.get_coin_state = AsyncMock(return_value=[])

    fake_nft = MagicMock()
    fake_nft.launcher_id = bytes32([1] * 32)

    with patch("chia.wallet.wallet_state_manager.NFT.get_next_from_previous", return_value=fake_nft):
        with pytest.raises(ValueError, match="Launcher coin record"):
            await wsm.manual_nft_search(bytes32.zeros)
