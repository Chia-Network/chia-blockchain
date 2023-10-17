from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from chia.cmds.cmds_util import CMDTXConfigLoader, get_wallet_client, transaction_status_msg, transaction_submitted_msg
from chia.cmds.units import units
from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import selected_network_address_prefix
from chia.util.ints import uint64
from chia.wallet.util.tx_config import DEFAULT_COIN_SELECTION_CONFIG
from chia.wallet.util.wallet_types import WalletType


async def add_dao_wallet(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    treasury_id = args["treasury_id"]
    filter_amount = args["filter_amount"]
    name = args["name"]

    print(f"Adding wallet for DAO: {treasury_id}")
    print("This may take awhile.")

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.create_new_dao_wallet(
            mode="existing",
            tx_config=CMDTXConfigLoader.from_json_dict({"reuse_puzhash": True}).to_tx_config(
                units["chia"], config, fingerprint
            ),
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


async def create_dao_wallet(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    proposal_minimum = uint64(int(Decimal(args["proposal_minimum_amount"]) * units["chia"]))

    if proposal_minimum % 2 == 0:
        proposal_minimum = uint64(1 + proposal_minimum)
        print("Adding 1 mojo to proposal minimum amount")

    dao_rules = {
        "proposal_timelock": args["proposal_timelock"],
        "soft_close_length": args["soft_close_length"],
        "attendance_required": args["attendance_required"],
        "pass_percentage": args["pass_percentage"],
        "self_destruct_length": args["self_destruct_length"],
        "oracle_spend_delay": args["oracle_spend_delay"],
        "proposal_minimum_amount": proposal_minimum,
    }
    amount_of_cats = args["amount_of_cats"]
    filter_amount = args["filter_amount"]
    name = args["name"]

    fee = Decimal(args["fee"])
    final_fee: uint64 = uint64(int(fee * units["chia"]))

    fee_for_cat = Decimal(args["fee_for_cat"])
    final_fee_for_cat: uint64 = uint64(int(fee_for_cat * units["chia"]))

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        conf_coins, _, _ = await wallet_client.get_spendable_coins(
            wallet_id=1, coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG
        )
        if len(conf_coins) < 2:  # pragma: no cover
            raise ValueError("DAO creation requires at least 2 xch coins in your wallet.")
        res = await wallet_client.create_new_dao_wallet(
            mode="new",
            dao_rules=dao_rules,
            amount_of_cats=amount_of_cats,
            treasury_id=None,
            filter_amount=filter_amount,
            name=name,
            fee=final_fee,
            fee_for_cat=final_fee_for_cat,
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )

        print("Successfully created DAO Wallet")
        print("DAO Treasury ID: {treasury_id}".format(**res))
        print("DAO Wallet ID: {wallet_id}".format(**res))
        print("CAT Wallet ID: {cat_wallet_id}".format(**res))
        print("DAOCAT Wallet ID: {dao_cat_wallet_id}".format(**res))


async def get_treasury_id(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, _, _):
        res = await wallet_client.dao_get_treasury_id(wallet_id=wallet_id)
        treasury_id = res["treasury_id"]
        print(f"Treasury ID: {treasury_id}")


async def get_rules(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, _, _):
        res = await wallet_client.dao_get_rules(wallet_id=wallet_id)
        rules = res["rules"]
        for rule, val in rules.items():
            print(f"{rule}: {val}")


async def add_funds_to_treasury(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    funding_wallet_id = args["funding_wallet_id"]
    amount = Decimal(args["amount"])

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
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
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )

        tx_id = res["tx_id"]
        start = time.time()
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(fingerprint, tx_id[2:]))
                return None

        print(f"Transaction not yet submitted to nodes. TX ID: {tx_id}")  # pragma: no cover


async def get_treasury_balance(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, _, _):
        res = await wallet_client.dao_get_treasury_balance(wallet_id=wallet_id)
        balances = res["balances"]

        if not balances:
            print("The DAO treasury currently has no funds")
            return None

        xch_mojos = get_mojo_per_unit(WalletType.STANDARD_WALLET)
        cat_mojos = get_mojo_per_unit(WalletType.CAT)
        for asset_id, balance in balances.items():
            if asset_id == "xch":
                print(f"XCH: {balance / xch_mojos}")
            else:
                print(f"{asset_id}: {balance / cat_mojos}")


async def list_proposals(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    include_closed = args["include_closed"]

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, _, _):
        res = await wallet_client.dao_get_proposals(wallet_id=wallet_id, include_closed=include_closed)
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


async def show_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    proposal_id = args["proposal_id"]

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, _, config):
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

        prefix = selected_network_address_prefix(config)
        if ptype == "spend":
            xch_conds = pd["xch_conditions"]
            asset_conds = pd["asset_conditions"]
            print("")
            if xch_conds:
                print("Proposal XCH Conditions")
                for pmt in xch_conds:
                    puzzle_hash = encode_puzzle_hash(bytes32.from_hexstr(pmt["puzzle_hash"]), prefix)
                    amount = pmt["amount"]
                    print(f"Address: {puzzle_hash}\nAmount: {amount}\n")
            if asset_conds:
                print("Proposal asset Conditions")
                for cond in asset_conds:
                    asset_id = cond["asset_id"]
                    print(f"Asset ID: {asset_id}")
                    conds = cond["conditions"]
                    for pmt in conds:
                        puzzle_hash = encode_puzzle_hash(bytes32.from_hexstr(pmt["puzzle_hash"]), prefix)
                        amount = pmt["amount"]
                        print(f"Address: {puzzle_hash}\nAmount: {amount}\n")

        elif ptype == "update":
            print("")
            print("Proposed Rules:")
            for key, val in pd["dao_rules"].items():
                print(f"{key}: {val}")

        elif ptype == "mint":
            mint_amount = pd["mint_amount"]
            address = encode_puzzle_hash(bytes32.from_hexstr(pd["new_cat_puzhash"]), prefix)
            print("")
            print(f"Amount of CAT to mint: {mint_amount}")
            print(f"Address: {address}")


async def vote_on_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    vote_amount = args["vote_amount"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    proposal_id = args["proposal_id"]
    is_yes_vote = args["is_yes_vote"]

    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.dao_vote_on_proposal(
            wallet_id=wallet_id,
            proposal_id=proposal_id,
            vote_amount=vote_amount,
            is_yes_vote=is_yes_vote,
            fee=final_fee,
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )
        tx_id = res["tx_id"]
        start = time.time()
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(fingerprint, tx_id[2:]))
                return None

        print(f"Transaction not yet submitted to nodes. TX ID: {tx_id}")  # pragma: no cover


async def close_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    proposal_id = args["proposal_id"]
    self_destruct = args["self_destruct"]
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.dao_close_proposal(
            wallet_id=wallet_id,
            proposal_id=proposal_id,
            fee=final_fee,
            self_destruct=self_destruct,
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )
        tx_id = res["tx_id"]
        start = time.time()
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(fingerprint, tx_id[2:]))
                return None

        print(f"Transaction not yet submitted to nodes. TX ID: {tx_id}")  # pragma: no cover


async def lockup_coins(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    amount = args["amount"]
    final_amount: uint64 = uint64(int(Decimal(amount) * units["cat"]))
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.dao_send_to_lockup(
            wallet_id=wallet_id,
            amount=final_amount,
            fee=final_fee,
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )
        tx_id = res["tx_id"]
        start = time.time()
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(fingerprint, tx_id[2:]))
                return None

        print(f"Transaction not yet submitted to nodes. TX ID: {tx_id}")  # pragma: no cover


async def release_coins(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.dao_free_coins_from_finished_proposals(
            wallet_id=wallet_id,
            fee=final_fee,
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )
        tx_id = res["tx_id"]
        start = time.time()
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(fingerprint, tx_id[2:]))
                return None
        print(f"Transaction not yet submitted to nodes. TX ID: {tx_id}")  # pragma: no cover


async def exit_lockup(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.dao_exit_lockup(
            wallet_id=wallet_id,
            coins=[],
            fee=final_fee,
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )
        tx_id = res["tx_id"]
        start = time.time()
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = await wallet_client.get_transaction(wallet_id, bytes32.from_hexstr(tx_id))
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(fingerprint, tx_id[2:]))
                return None
        print(f"Transaction not yet submitted to nodes. TX ID: {tx_id}")  # pragma: no cover


async def create_spend_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    asset_id = args.get("asset_id")
    address = args.get("to_address")
    amount = args.get("amount")
    additions_file = args.get("from_json")
    if additions_file is None and (address is None or amount is None):
        raise ValueError("Must include a json specification or an address / amount pair.")
    if additions_file:  # pragma: no cover
        with open(additions_file, "r") as f:
            additions_dict = json.load(f)
        additions = []
        for addition in additions_dict:
            addition["puzzle_hash"] = decode_puzzle_hash(addition["address"]).hex()
            del addition["address"]
            additions.append(addition)
    else:
        additions = None
    vote_amount = args.get("vote_amount")
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
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
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )
        if res["success"]:
            asset_id_name = asset_id if asset_id else "XCH"
            print(f"Created spend proposal for asset: {asset_id_name}")
            print("Successfully created proposal.")
            print("Proposal ID: {}".format(res["proposal_id"]))
        else:  # pragma: no cover
            print("Failed to create proposal.")


async def create_update_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    fee = Decimal(args["fee"])
    final_fee: uint64 = uint64(int(fee * units["chia"]))
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
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.dao_create_proposal(
            wallet_id=wallet_id,
            proposal_type="update",
            new_dao_rules=new_dao_rules,
            vote_amount=vote_amount,
            fee=final_fee,
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )
        if res["success"]:
            print("Successfully created proposal.")
            print("Proposal ID: {}".format(res["proposal_id"]))
        else:  # pragma: no cover
            print("Failed to create proposal.")


async def create_mint_proposal(args: Dict[str, Any], wallet_rpc_port: Optional[int], fp: int) -> None:
    wallet_id = args["wallet_id"]
    fee = args["fee"]
    final_fee: uint64 = uint64(int(Decimal(fee) * units["chia"]))
    cat_target_address = args["cat_target_address"]
    amount = args["amount"]
    vote_amount = args.get("vote_amount")
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.dao_create_proposal(
            wallet_id=wallet_id,
            proposal_type="mint",
            cat_target_address=cat_target_address,
            amount=amount,
            vote_amount=vote_amount,
            fee=final_fee,
            tx_config=CMDTXConfigLoader.from_json_dict(
                {
                    "min_coin_amount": args["min_coin_amount"],
                    "max_coin_amount": args["max_coin_amount"],
                    "coins_to_exclude": args["coins_to_exclude"],
                    "amounts_to_exclude": args["amounts_to_exclude"],
                    "reuse_puzhash": args["reuse_puzhash"],
                }
            ).to_tx_config(units["chia"], config, fingerprint),
        )
        if res["success"]:
            print("Successfully created proposal.")
            print("Proposal ID: {}".format(res["proposal_id"]))
        else:  # pragma: no cover
            print("Failed to create proposal.")
