from __future__ import annotations

import asyncio
from decimal import Decimal
import time
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
    treasury_id = args["treasury_id"]
    filter_amount = args["filter_amount"]
    name = args["name"]

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
    wallet_id = args["wallet_id"]
    funding_wallet_id = args["funding_wallet_id"]
    amount = Decimal(args["amount"])
    fee = Decimal(args["fee"])

    try:
        typ = await get_wallet_type(wallet_id=funding_wallet_id, wallet_client=wallet_client)
        mojo_per_unit = get_mojo_per_unit(typ)
    except LookupError:
        print(f"Wallet id: {wallet_id} not found.")
        return

    final_fee: uint64 = uint64(int(fee * units["chia"]))
    final_amount: uint64 = uint64(int(amount * mojo_per_unit))

    res = await wallet_client.dao_add_funds_to_treasury(
        wallet_id=wallet_id,
        funding_wallet_id=funding_wallet_id,
        amount=final_amount
    )

    tx_id = res["tx_id"]
    start = time.time()
    while time.time() - start < 10:
        await asyncio.sleep(0.1)
        tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
        if len(tx.sent_to) > 0:
            print(transaction_submitted_msg(tx))
            print(transaction_status_msg(fingerprint, tx_id))
            return None

    print("Transaction not yet submitted to nodes")
    print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}")


async def get_treasury_balance(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]

    res = await wallet_client.dao_get_treasury_balance(wallet_id=wallet_id)
    balances = res["balances"]

    if not balances:
        print("The DAO treasury currently has no funds")
        return None

    for asset_id, balance in balances.items():
        if asset_id == "null":
            print(f"XCH: {balance}")
        else:
            print(f"{asset_id}: {balance}")


async def list_proposals(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]

    res = await wallet_client.dao_get_proposals(wallet_id=wallet_id)
    proposals = res["proposals"]
    # proposal_id: bytes32  # this is launcher_id
    # inner_puzzle: Program
    # amount_voted: uint64
    # yes_votes: uint64
    # current_coin: Coin
    # current_innerpuz: Optional[Program]
    # timer_coin: Optional[Coin]  # if this is None then the proposal has finished
    # singleton_block_height: uint32  # Block height that current proposal singleton coin was created in
    # passed: Optional[bool]
    # closed: Optional[bool]
    if not res["success"]:
        print("Error: unable to fetch proposals.")
        return
    lockup_time = res["lockup_times"]
    soft_close_length = res["soft_close_length"]
    print("############################")
    for prop in proposals:
        print(f"Proposal ID: {prop.proposal_id.hex()}")
        print(f"Votes for: {prop.yes_votes}")
        print(f"Votes against: {prop.total_votes - prop.yes_votes}")
        print(f"Closable at block height: {prop.singleton_block_height + lockup_time}")
        print("------------------------")
    print(f"Proposals have {soft_close_length} blocks of soft close time.")
    print("############################")


async def show_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    raise ValueError("Not Implemented")


async def vote_on_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    vote_amount = args["vote_amount"]
    if "fee" in args:
        fee = args["fee"]
    else:
        fee = uint64(0)
    proposal_id = request["proposal_id"]
    is_yes_vote = request["is_yes_vote"]
    # wallet_id: int, proposal_id: str, vote_amount: uint64, is_yes_vote: bool = True, fee: uint64 = uint64(0)
    res = await wallet_client.dao_vote_on_proposals(
        wallet_id=wallet_id, proposal_id=proposal_id, vote_amount=vote_amount, is_yes_vote=is_yes_vote, fee=fee
    )
    spend_bundle = res["spend_bundle"]
    if res["success"]:
        print(f"Submitted spend bundle with name: {spend_bundle.name()}")
    else:
        print("Unable to generate vote transaction.")


async def close_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    if "fee" in args:
        fee = args["fee"]
    else:
        fee = uint64(0)
    proposal_id = request["proposal_id"]
    res = await wallet_client.dao_close_proposal(
        wallet_id=wallet_id, proposal_id=proposal_id, fee=fee
    )
    # dao_close_proposal(self, wallet_id: int, proposal_id: str, fee: uint64 = uint64(0))
    if res["success"]:
        name = res["tx_id"]
        print(f"Submitted proposal close transaction with name: {name}")
    else:
        print("Unable to generate close transaction.")


async def lockup_coins(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    amount = args["amount"]
    final_amount: uint64 = uint64(int(Decimal(amount) * units["cat"]))
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    typ = await get_wallet_type(wallet_id=4, wallet_client=wallet_client)
    res = await wallet_client.dao_send_to_lockup(wallet_id=wallet_id, amount=final_amount, fee=final_fee)
    tx_id = res["tx_id"]
    start = time.time()
    while time.time() - start < 10:
        await asyncio.sleep(0.1)
        tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
        if len(tx.sent_to) > 0:
            print(transaction_submitted_msg(tx))
            print(transaction_status_msg(fingerprint, tx_id))
            return None

    print("Transaction not yet submitted to nodes")


async def release_coins(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    res = await wallet_client.dao_free_coins_from_finished_proposal(
        wallet_id=wallet_id
    )
    raise ValueError("Not Implemented")


async def create_spend_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    if "fee" in args:
        fee = args["fee"]
    else:
        fee = uint64(0)

    if "to_address" in args:
        address = args["to_address"]
    else:
        address = None
    if "amount" in args:
        amount = args["amount"]
    else:
        amount = None
    if "from_json" in args:
        additions = args["from_json"]
    else:
        additions = None
    if additions is None and (address is None or amount is None):
        print("ERROR: Must include a json specification or an address / amount pair.")
    if "vote_amount" in args:
        vote_amount = args["vote_amount"]
    else:
        vote_amount = None
    res = await wallet_client.dao_create_proposal(
        wallet_id=wallet_id,
        proposal_type="spend",
        additions=additions,
        amount=amount,
        inner_address=address,
        vote_amount=vote_amount,
        fee=fee
    )
    if res["success"]:
        print(f"Successfully created proposal.")
    else:
        print("Failed to create proposal.")


async def create_update_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    if "fee" in args:
        fee = args["fee"]
    else:
        fee = uint64(0)
    if "proposal_timelock" in args:
        proposal_timelock = args["proposal_timelock"]
    else:
        proposal_timelock = None
    if "soft_close_length" in args:
        soft_close_length = args["soft_close_length"]
    else:
        soft_close_length = None
    if "attendance_required" in args:
        attendance_required = args["attendance_required"]
    else:
        attendance_required = None
    if "pass_percentage" in args:
        pass_percentage = args["pass_percentage"]
    else:
        pass_percentage = None
    if "self_destruct_length" in args:
        self_destruct_length = args["self_destruct_length"]
    else:
        self_destruct_length = None
    if "oracle_spend_delay" in args:
        oracle_spend_delay = args["oracle_spend_delay"]
    else:
        oracle_spend_delay = None
    if "vote_amount" in args:
        vote_amount = args["vote_amount"]
    else:
        vote_amount = None
    new_dao_rules = {
        "proposal_timelock": proposal_timelock,
        "soft_close_length": soft_close_length,
        "attendance_required": attendance_required,
        "pass_percentage": pass_percentage,
        "self_destruct_length": self_destruct_length,
        "oracle_spend_delay": oracle_spend_delay,
    }
    res = await wallet_client.dao_create_proposal(
        wallet_id=wallet_id,
        proposal_type="update",
        new_dao_rules=new_dao_rules,
        vote_amount=vote_amount,
        fee=fee,
    )
    if res["success"]:
        print(f"Successfully created proposal.")
    else:
        print("Failed to create proposal.")


async def create_mint_proposal(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    if "fee" in args:
        fee = args["fee"]
    else:
        fee = uint64(0)
    cat_target_address = args["cat_target_address"]
    amount = args["amount"]
    if "vote_amount" in args:
        vote_amount = args["vote_amount"]
    res = await wallet_client.dao_create_proposal(
        wallet_id=wallet_id,
        proposal_type="mint",
        cat_target_address=cat_target_address,
        amount=amount,
        vote_amount=vote_amount,
        fee=fee,
    )
    if res["success"]:
        print(f"Successfully created proposal.")
    else:
        print("Failed to create proposal.")
