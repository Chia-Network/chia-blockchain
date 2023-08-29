from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from chia.cmds.cmds_util import get_wallet_client, transaction_status_msg, transaction_submitted_msg
from chia.cmds.units import units
from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import selected_network_address_prefix
from chia.util.ints import uint64
from chia.wallet.util.wallet_types import WalletType


async def add_dao_wallet(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    treasury_id = args["treasury_id"]
    filter_amount = args["filter_amount"]
    name = args["name"]

    print(f"Adding wallet for DAO: {treasury_id}")
    print("This may take awhile.")

    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
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


async def create_dao_wallet(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    dao_rules = {
        "proposal_timelock": args["proposal_timelock"],
        "soft_close_length": args["soft_close_length"],
        "attendance_required": args["attendance_required"],
        "pass_percentage": args["pass_percentage"],
        "self_destruct_length": args["self_destruct_length"],
        "oracle_spend_delay": args["oracle_spend_delay"],
        "proposal_minimum_amount": args["proposal_minimum_amount"],
    }
    amount_of_cats = args["amount_of_cats"]
    filter_amount = args["filter_amount"]
    name = args["name"]
    reuse_puzhash = args["reuse_puzhash"]

    fee = Decimal(args["fee"])
    final_fee: uint64 = uint64(int(fee * units["chia"]))

    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.create_new_dao_wallet(
            mode="new",
            dao_rules=dao_rules,
            amount_of_cats=amount_of_cats,
            treasury_id=None,
            filter_amount=filter_amount,
            name=name,
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
        )

        print("Successfully created DAO Wallet")
        print("DAO Treasury ID: {treasury_id}".format(**res))
        print("DAO Wallet ID: {wallet_id}".format(**res))
        print("CAT Wallet ID: {cat_wallet_id}".format(**res))
        print("DAOCAT Wallet ID: {dao_cat_wallet_id}".format(**res))


async def get_treasury_id(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]

    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_get_treasury_id(wallet_id=wallet_id)
        treasury_id = res["treasury_id"]
        print(f"Treasury ID: {treasury_id}")


async def add_funds_to_treasury(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    funding_wallet_id = args["funding_wallet_id"]
    amount = Decimal(args["amount"])
    reuse_puzhash = args["reuse_puzhash"]

    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        try:
            typ = await get_wallet_type(wallet_id=funding_wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(typ)
        except LookupError:  # pragma: no cover
            print(f"Wallet id: {wallet_id} not found.")
            return

        fee = Decimal(args["fee"])
        final_fee: uint64 = uint64(int(fee * units["chia"]))
        final_amount: uint64 = uint64(int(amount * mojo_per_unit))

        res = await wallet_client.dao_add_funds_to_treasury(
            wallet_id=wallet_id,
            funding_wallet_id=funding_wallet_id,
            amount=final_amount,
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
        )

        tx_id = res["tx_id"]
        start = time.time()
        print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}")
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(fingerprint, tx_id))
                return None

        print("Transaction not yet submitted to nodes")  # pragma: no cover


async def get_treasury_balance(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]

    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_get_treasury_balance(wallet_id=wallet_id)
        balances = res["balances"]

        if not balances:
            print("The DAO treasury currently has no funds")
            return None

        for asset_id, balance in balances.items():
            if asset_id == "xch":
                mojos = get_mojo_per_unit(WalletType.STANDARD_WALLET)
                print(f"XCH: {balance / mojos}")
            else:
                mojos = get_mojo_per_unit(WalletType.CAT)
                print(f"{asset_id}: {balance / mojos}")


async def list_proposals(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]

    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_get_proposals(wallet_id=wallet_id)
        proposals = res["proposals"]
        soft_close_length = res["soft_close_length"]
        print("############################")
        for prop in proposals:
            print("Proposal ID: {proposal_id}".format(**prop))
            prop_status = "CLOSED" if prop["closed"] else "OPEN"
            print(f"Status: {prop_status}")
            print("Votes for: {yes_votes}".format(**prop))
            votes_against = prop["amount_voted"] - prop["yes_votes"]
            print(f"Votes against: {votes_against}")
            print("------------------------")
        print(f"Proposals have {soft_close_length} blocks of soft close time.")
        print("############################")


async def show_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    proposal_id = args["proposal_id"]

    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, config):
        res = await wallet_client.dao_parse_proposal(wallet_id, proposal_id)
        pd = res["proposal_dictionary"]
        blocks_needed = pd["state"]["blocks_needed"]
        passed = pd["state"]["passed"]
        closable = pd["state"]["closable"]
        status = "CLOSED" if pd["state"]["closed"] else "OPEN"
        votes_needed = pd["state"]["total_votes_needed"]
        yes_needed = pd["state"]["yes_votes_needed"]

        ptype_val = pd["proposal_type"]
        if (ptype_val == "s") and ("mint_amount" in pd):
            ptype = "mint"
        elif ptype_val == "s":
            ptype = "spend"
        elif ptype_val == "u":
            ptype = "update"

        print("")
        print(f"Details of Proposal: {proposal_id}")
        print("---------------------------")
        print("")
        print(f"Type: {ptype.upper()}")
        print(f"Status: {status}")
        print(f"Passed: {passed}")
        if not passed:
            print(f"Yes votes needed: {yes_needed}")

        if not pd["state"]["closed"]:
            print(f"Closable: {closable}")
            if not closable:
                print(f"Total votes needed: {votes_needed}")
                print(f"Blocks remaining: {blocks_needed}")

        if ptype == "spend":
            xch_conds = pd["xch_conditions"]
            asset_conds = pd["asset_conditions"]
            print("")
            if xch_conds:
                print("Proposal XCH Conditions")
                for pmt in xch_conds:
                    print("{puzzle_hash} {amount}".format(**pmt))
            if asset_conds:
                print("Proposal asset Conditions")
                for cond in asset_conds:
                    asset_id = cond["asset_id"]
                    print(f"Asset ID: {asset_id}")
                    conds = cond["conditions"]
                    for pmt in conds:
                        print("{puzzle_hash} {amount}".format(**pmt))

        elif ptype == "update":
            print("")
            print("Proposed Rules:")
            for key, val in pd["dao_rules"].items():
                print(f"{key}: {val}")

        elif ptype == "mint":
            mint_amount = pd["mint_amount"]
            prefix = selected_network_address_prefix(config)
            address = encode_puzzle_hash(bytes32.from_hexstr(pd["new_cat_puzhash"]), prefix)
            print("")
            print(f"Amount of CAT to mint: {mint_amount}")
            print(f"Address: {address}")


async def vote_on_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    vote_amount = args["vote_amount"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    proposal_id = args["proposal_id"]
    is_yes_vote = args["is_yes_vote"]
    reuse_puzhash = args["reuse_puzhash"]
    # wallet_id: int, proposal_id: str, vote_amount: uint64, is_yes_vote: bool = True, fee: uint64 = uint64(0)
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_vote_on_proposal(
            wallet_id=wallet_id,
            proposal_id=proposal_id,
            vote_amount=vote_amount,
            is_yes_vote=is_yes_vote,
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
        )
        spend_bundle = res["spend_bundle_name"]
        if res["success"]:
            print(f"Submitted spend bundle with name: {spend_bundle}")
        else:  # pragma: no cover
            print("Unable to generate vote transaction.")


async def close_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    proposal_id = args["proposal_id"]
    reuse_puzhash = args["reuse_puzhash"]
    self_destruct = args["self_destruct"]
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_close_proposal(
            wallet_id=wallet_id,
            proposal_id=proposal_id,
            fee=final_fee,
            self_destruct=self_destruct,
            reuse_puzhash=reuse_puzhash,
        )
        if res["success"]:
            name = res["tx_id"]
            print(f"Submitted proposal close transaction with name: {name}")
        else:  # pragma: no cover
            print("Unable to generate close transaction.")


async def lockup_coins(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    amount = args["amount"]
    final_amount: uint64 = uint64(int(Decimal(amount) * units["cat"]))
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    reuse_puzhash = args["reuse_puzhash"]
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_send_to_lockup(
            wallet_id=wallet_id,
            amount=final_amount,
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
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

        print("Transaction not yet submitted to nodes")  # pragma: no cover


async def release_coins(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    reuse_puzhash = args["reuse_puzhash"]
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_free_coins_from_finished_proposals(
            wallet_id=wallet_id,
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
        )
        if res["success"]:
            spend_bundle_id = res["spend_bundle_id"]
            print(f"Transaction submitted with spend bundle ID: {spend_bundle_id}.")
        else:  # pragma: no cover
            print("Transaction failed.")


async def exit_lockup(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    reuse_puzhash = args["reuse_puzhash"]
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_exit_lockup(
            wallet_id=wallet_id,
            coins=[],
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
        )
        if res["success"]:
            spend_bundle_id = res["spend_bundle_id"]
            print(f"Transaction submitted with spend bundle ID: {spend_bundle_id}.")
        else:  # pragma: no cover
            print("Transaction failed.")


async def create_spend_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    reuse_puzhash = args["reuse_puzhash"]
    asset_id = args.get("asset_id")
    address = args.get("to_address")
    amount = args.get("amount")
    additions = args.get("from_json")
    if additions is None and (address is None or amount is None):
        raise ValueError("Must include a json specification or an address / amount pair.")
    vote_amount = args.get("vote_amount")
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        wallet_type = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
        mojo_per_unit = get_mojo_per_unit(wallet_type=wallet_type)
        final_amount: Optional[uint64] = uint64(int(Decimal(amount) * mojo_per_unit)) if amount else None
        res = await wallet_client.dao_create_proposal(
            wallet_id=wallet_id,
            proposal_type="spend",
            additions=additions,
            amount=final_amount,
            inner_address=address,
            asset_id=asset_id,
            vote_amount=vote_amount,
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
        )
        if res["success"]:
            print(f"Created spend proposal for asset: {asset_id}")
            print("Successfully created proposal.")
            print("Proposal ID: {}".format(res["proposal_id"]))
        else:  # pragma: no cover
            print("Failed to create proposal.")


async def create_update_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    fee = Decimal(args["fee"])
    final_fee: uint64 = uint64(int(fee * units["chia"]))
    reuse_puzhash = args["reuse_puzhash"]
    proposal_timelock = args.get("proposal_timelock")
    soft_close_length = args.get("soft_close_length")
    attendance_required = args.get("attendance_required")
    pass_percentage = args.get("pass_percentage")
    self_destruct_length = args.get("self_destruct_length")
    oracle_spend_delay = args.get("oracle_spend_delay")
    vote_amount = args.get("vote_amount")
    new_dao_rules = {
        "proposal_timelock": proposal_timelock,
        "soft_close_length": soft_close_length,
        "attendance_required": attendance_required,
        "pass_percentage": pass_percentage,
        "self_destruct_length": self_destruct_length,
        "oracle_spend_delay": oracle_spend_delay,
    }
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_create_proposal(
            wallet_id=wallet_id,
            proposal_type="update",
            new_dao_rules=new_dao_rules,
            vote_amount=vote_amount,
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
        )
        if res["success"]:
            print("Successfully created proposal.")
            print("Proposal ID: {}".format(res["proposal_id"]))
        else:  # pragma: no cover
            print("Failed to create proposal.")


async def create_mint_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    reuse_puzhash = args["reuse_puzhash"]
    cat_target_address = args["cat_target_address"]
    amount = args["amount"]
    vote_amount = args.get("vote_amount")
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, _):
        res = await wallet_client.dao_create_proposal(
            wallet_id=wallet_id,
            proposal_type="mint",
            cat_target_address=cat_target_address,
            amount=amount,
            vote_amount=vote_amount,
            fee=final_fee,
            reuse_puzhash=reuse_puzhash,
        )
        if res["success"]:
            print("Successfully created proposal.")
            print("Proposal ID: {}".format(res["proposal_id"]))
        else:  # pragma: no cover
            print("Failed to create proposal.")
