from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.util.ints import uint64
from chia.cmds.units import units
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config, selected_network_address_prefix
from chia.util.bech32m import bech32_decode, decode_puzzle_hash, encode_puzzle_hash
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.address_type import AddressType, ensure_valid_address
from chia.wallet.util.wallet_types import WalletType
from chia.cmds.cmds_util import transaction_status_msg, transaction_submitted_msg
from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type


async def add_dao_wallet(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    treasury_id=args["treasury_id"]
    filter_amount=args["filter_amount"]
    name=args["name"]

    print(f"Adding wallet for DAO: {treasury_id}")
    print("This may take awhile.")

    res = await wallet_client.create_new_dao_wallet(
        mode="existing",
        dao_rules=None,
        amount_of_cats=None,
        treasury_id=treasury_id,
        filter_amount=filter_amount,
        name=name,
    )

    print("Successfully created DAO Wallet")
    print("DAO Treasury ID: {treasury_id}".format(**res))
    print("DAO Wallet ID: {wallet_id}".format(**res))
    print("CAT Wallet ID: {cat_wallet_id}".format(**res))
    print("DAOCAT Wallet ID: {dao_cat_wallet_id}".format(**res))


async def create_dao_wallet(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    dao_rules = {
        "proposal_timelock": args["proposal_timelock"],
        "soft_close_length": args["soft_close_length"],
        "attendance_required": args["attendance_required"],
        "pass_percentage": args["pass_percentage"],
        "self_destruct_length": args["self_destruct_length"],
        "oracle_spend_delay": args["oracle_spend_delay"],
    }
    amount_of_cats = args["amount_of_cats"]
    filter_amount = args["filter_amount"]
    name = args["name"]
    
    fee = Decimal(args["fee"])
    final_fee: uint64 = uint64(int(fee * units["chia"]))

    res = await wallet_client.create_new_dao_wallet(
        mode="new",
        dao_rules=dao_rules,
        amount_of_cats=amount_of_cats,
        treasury_id=None,
        filter_amount=filter_amount,
        name=name,
        fee=final_fee,
    )

    print("Successfully created DAO Wallet")
    print("DAO Treasury ID: {treasury_id}".format(**res))
    print("DAO Wallet ID: {wallet_id}".format(**res))
    print("CAT Wallet ID: {cat_wallet_id}".format(**res))
    print("DAOCAT Wallet ID: {dao_cat_wallet_id}".format(**res))


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
