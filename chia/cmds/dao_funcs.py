from __future__ import annotations

from typing import Any, Dict

from chia.rpc.wallet_rpc_client import WalletRpcClient


async def add_dao_wallet(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def create_dao_wallet(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def add_funds_to_treasury(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def get_treasury_balance(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def list_proposals(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def show_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def vote_on_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def close_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def lockup_coins(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def release_coins(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def create_spend_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def create_update_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def create_mint_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")
