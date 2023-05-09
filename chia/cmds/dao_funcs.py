from __future__ import annotations

from typing import Any, Dict

from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.util.ints import uint64


async def add_dao_wallet(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    """
    TODO: Mojos vs. XCH on the command line
    """
    treasury_id = args["treasury_id"]
    name = args["name"]
    filter_amount = args["filter_amount"]
    fee = 0
    name = "hi"

    filter_amount = 200
    amount_of_cats = 2000

    res = await wallet_client.create_new_dao_wallet(
        mode="existing",
        dao_rules=None,
        amount_of_cats=uint64(amount_of_cats,
        treasury_id=treasury_id,
        filter_amount=filter_amount,
        name=name,
        fee=uint64(fee),
    )
    print(res)


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
