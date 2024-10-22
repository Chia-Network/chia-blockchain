from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from chia_rs import G1Element

from chia.cmds.cmds_util import CMDTXConfigLoader, get_wallet_client, write_transactions_to_file
from chia.cmds.param_types import CliAmount
from chia.cmds.units import units
from chia.rpc.wallet_request_types import VaultCreate, VaultRecovery
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord


async def create_vault(
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    public_key: str,
    recovery_public_key: Optional[str],
    timelock: Optional[int],
    hidden_puzzle_index: int,
    fee: uint64,
    name: Optional[str],
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    excluded_coin_ids: Sequence[bytes32],
    reuse_puzhash: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> list[TransactionRecord]:
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, fingerprint, config):
        assert hidden_puzzle_index >= 0
        tx_config = CMDTXConfigLoader(
            min_coin_amount=min_coin_amount,
            max_coin_amount=max_coin_amount,
            excluded_coin_ids=list(excluded_coin_ids),
            reuse_puzhash=reuse_puzhash,
        ).to_tx_config(units["chia"], config, fingerprint)
        if timelock is not None:
            assert timelock > 0
        try:
            res = await wallet_client.vault_create(
                VaultCreate(
                    secp_pk=bytes.fromhex(public_key),
                    hp_index=uint32(hidden_puzzle_index),
                    bls_pk=G1Element.from_bytes(bytes.fromhex(recovery_public_key)) if recovery_public_key else None,
                    timelock=uint64(timelock) if timelock else None,
                    fee=fee,
                    push=push,
                ),
                tx_config=tx_config,
                timelock_info=condition_valid_times,
            )
            print("Successfully created a Vault wallet")
            return res.transactions
        except Exception as e:
            print(f"Failed to create a new Vault: {e}")
            return []


async def recover_vault(
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    wallet_id: int,
    public_key: str,
    hidden_puzzle_index: int,
    recovery_public_key: Optional[str],
    timelock: Optional[int],
    initiate_file: str,
    finish_file: str,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    excluded_coin_ids: Sequence[bytes32],
    reuse_puzhash: Optional[bool],
    condition_valid_times: ConditionValidTimes,
) -> None:
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, fingerprint, config):
        assert hidden_puzzle_index >= 0
        if timelock is not None:
            assert timelock > 0
        tx_config = CMDTXConfigLoader(
            min_coin_amount=min_coin_amount,
            max_coin_amount=max_coin_amount,
            excluded_coin_ids=list(excluded_coin_ids),
            reuse_puzhash=reuse_puzhash,
        ).to_tx_config(units["chia"], config, fingerprint)
        try:
            response = await wallet_client.vault_recovery(
                VaultRecovery(
                    wallet_id=uint32(wallet_id),
                    secp_pk=bytes.fromhex(public_key),
                    hp_index=uint32(hidden_puzzle_index),
                    bls_pk=G1Element.from_bytes(bytes.fromhex(recovery_public_key)) if recovery_public_key else None,
                    timelock=uint64(timelock) if timelock else None,
                ),
                tx_config=tx_config,
                timelock_info=condition_valid_times,
            )
            write_transactions_to_file([response.recovery_tx], initiate_file)
            write_transactions_to_file([response.finish_tx], finish_file)
        except Exception as e:
            print(f"Error creating recovery transactions: {e}")
