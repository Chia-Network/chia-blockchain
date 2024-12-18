from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from chia_rs import AugSchemeMPL
from clvm.casts import int_to_bytes
from clvm.operators import KEYWORD_FROM_ATOM
from clvm_tools.binutils import disassemble as bu_disassemble

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    AssertPuzzleAnnouncement,
    CreateCoinAnnouncement,
    CreatePuzzleAnnouncement,
    SendMessage,
    UnknownCondition,
    parse_conditions_non_consensus,
)
from chia.wallet.uncurried_puzzle import UncurriedPuzzle

CONDITIONS = {opcode.name: opcode.value[0] for opcode in ConditionOpcode}
KFA = {v: k for k, v in CONDITIONS.items()}


# information needed to spend a cc
# if we ever support more genesis conditions, like a re-issuable coin,
# we may need also to save the `genesis_coin_mod` or its hash


def disassemble(sexp: Program):
    """
    This version of `disassemble` also disassembles condition opcodes like `ASSERT_ANNOUNCEMENT_CONSUMED`.
    """
    kfa = dict(KEYWORD_FROM_ATOM)
    kfa.update((Program.to(k).as_atom(), v) for k, v in KFA.items())
    return bu_disassemble(sexp, kfa)


def coin_as_program(coin: Coin) -> Program:
    """
    Convenience function for when putting `coin_info` into a solution.
    """
    return Program.to([coin.parent_coin_info, coin.puzzle_hash, coin.amount])


def dump_coin(coin: Coin) -> str:
    coin_str = (
        f"Coin ID:    {coin.name().hex()}\n"
        f"Parent ID:  {coin.parent_coin_info}\n"
        f"PuzzleHash: {coin.puzzle_hash}\n"
        f"Amount:     {coin.amount}\n"
    )
    return coin_str


def recursive_uncurry_dump(
    puzzle: Program, layer: int, prefix: str, uncurried_already: UncurriedPuzzle, puzzle_dict: dict[str, str]
) -> None:
    mod = uncurried_already.mod
    curried_args = uncurried_already.args
    if mod != puzzle:
        mod_hex = mod.get_tree_hash().hex()
        for key, val in puzzle_dict.items():
            if val == mod_hex:
                mod_name = key
                break
        else:
            mod_name = "Unknown Puzzle"
        print(f"{prefix}- Layer {layer}: {mod_name.upper()}")
        print(f"{prefix}  - Mod hash: {mod.get_tree_hash().hex()}")
        print(f"{prefix}  - Curried args:")

        for arg in curried_args.as_iter():
            uncurry_dump(arg, prefix=f"{prefix}    ")
        mod2, curried_args2 = mod.uncurry()
        if mod2 != mod:
            recursive_uncurry_dump(mod, layer + 1, prefix, UncurriedPuzzle(mod2, curried_args2), puzzle_dict)
    else:
        print(f"{prefix}- {bu_disassemble(puzzle)}")


def uncurry_dump(puzzle: Program, prefix: str = "") -> None:
    puzzle_json_path = Path("chia/wallet/puzzles/deployed_puzzle_hashes.json")
    with open(puzzle_json_path) as f:
        puzzle_dict = json.load(f)
    mod, curried_args = puzzle.uncurry()

    recursive_uncurry_dump(puzzle, 1, prefix, UncurriedPuzzle(mod, curried_args), puzzle_dict)


def debug_spend_bundle(spend_bundle, agg_sig_additional_data=DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA) -> None:
    """
    Print a lot of useful information about a `SpendBundle` that might help with debugging
    its clvm.
    """

    pks = []
    msgs = []

    created_coin_announcements: dict[bytes, list] = {}
    asserted_coin_announcements: dict[bytes, list] = {}
    created_puzzle_announcements: dict[bytes, list] = {}
    asserted_puzzle_announcements: dict[bytes, list] = {}
    sent_messages: dict[bytes, list] = {}
    received_messages: dict[bytes, list] = {}
    bad_messages: dict[bytes, list] = {}

    print("=" * 80)
    for i, coin_spend in enumerate(spend_bundle.coin_spends):
        coin = coin_spend.coin
        coin_name = coin.name()
        puzzle_reveal = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        solution = Program.from_bytes(bytes(coin_spend.solution))

        sent_messages[coin_name] = []
        received_messages[coin_name] = []
        bad_messages[coin_name] = []
        created_coin_announcements[coin_name] = []
        asserted_coin_announcements[coin_name] = []
        created_puzzle_announcements[coin_name] = []
        asserted_puzzle_announcements[coin_name] = []

        print(f"Spending Coin {i}:")
        print(dump_coin(coin_spend.coin))

        print()
        print("--- Puzzle Info ---")
        uncurry_dump(puzzle_reveal)

        if puzzle_reveal.get_tree_hash() != coin_spend.coin.puzzle_hash:
            print()
            print("*** BAD PUZZLE REVEAL")
            print(f"{puzzle_reveal.get_tree_hash().hex()} vs {coin_spend.coin.puzzle_hash.hex()}")
            print("*" * 80)
            print()
            continue

        print("\n\n--- Output Conditions ---\n")
        conditions_iter = puzzle_reveal.run(solution).as_iter()
        conditions = sorted(
            parse_conditions_non_consensus(conditions_iter, abstractions=False),
            key=lambda instance: instance.__class__.__name__,
        )
        conditions_dict = conditions_dict_for_solution(puzzle_reveal, solution, INFINITE_COST)
        for pk, m in pkm_pairs_for_conditions_dict(conditions_dict, coin, agg_sig_additional_data):
            pks.append(pk)
            msgs.append(m)
        for cond in conditions:
            cond_type = KFA[cond.to_program().first().as_int()]
            print(f"{cond_type}")
            if cond_type in {"SEND_MESSAGE", "RECEIVE_MESSAGE"}:
                if isinstance(cond, UnknownCondition):
                    print(f"   mode: {cond.args[0].as_int():06b}")
                    print(f"   message: {cond.args[1].as_atom().hex()}")
                    print("    ** Malformed args for condition **")
                    bad_messages[coin_name].append(cond)
                else:
                    assert isinstance(cond, SendMessage)
                    print(f"    mode: {cond.mode_integer:06b}")
                    print(f"    message: {cond.msg.hex()}")
                    other_side = cond.receiver if cond_type == "SEND_MESSAGE" else cond.sender
                    assert other_side is not None
                    for key, val in other_side.to_json_dict().items():
                        if val is not None:
                            print(f"    {key}: {val}")
            else:
                for key, val in cond.to_json_dict().items():
                    if val is not None:
                        print(f"    {key}: {val}")
            if isinstance(cond, SendMessage):
                if cond_type == "SEND_MESSAGE":
                    sent_messages[coin_name].append(cond)
                if cond_type == "RECEIVE_MESSAGE":
                    received_messages[coin_name].append(cond)
            if isinstance(cond, AssertPuzzleAnnouncement):
                asserted_puzzle_announcements[coin_name].append(cond)
            if isinstance(cond, CreatePuzzleAnnouncement):
                if cond.puzzle_hash is None:
                    cond = dataclasses.replace(cond, puzzle_hash=coin.puzzle_hash)
                created_puzzle_announcements[coin_name].append(cond)
            if isinstance(cond, AssertCoinAnnouncement):
                asserted_coin_announcements[coin_name].append(cond)
            if isinstance(cond, CreateCoinAnnouncement):
                if cond.coin_id is None:
                    cond = dataclasses.replace(cond, coin_id=coin_name)
                created_coin_announcements[coin_name].append(cond)
            print()
        print("=" * 80)

    print("Coin Summary\n")

    created = set(spend_bundle.additions())
    spent = set(spend_bundle.removals())

    ephemeral = created.intersection(spent)
    created.difference_update(ephemeral)
    spent.difference_update(ephemeral)
    print()
    print("--- SPENT COINS ---\n")
    for coin in sorted(spent, key=lambda _: _.name()):
        print(f"{dump_coin(coin)}")
    print()
    print("--- CREATED COINS ---\n")
    for coin in sorted(created, key=lambda _: _.name()):
        print(f"{dump_coin(coin)}")

    if ephemeral:
        print()
        print("--- EPHEMERAL COINS ---\n")
        for coin in sorted(ephemeral, key=lambda _: _.name()):
            print(f"{dump_coin(coin)}")

    print("-" * 80)
    print("PUZZLE ANNOUNCEMENTS\n\n")

    print("Created Puzzle Announcements\n")
    for coin_id, cpas in created_puzzle_announcements.items():
        for cpa in cpas:
            assertion = cpa.corresponding_assertion().msg_calc
            asserted_by = []
            for asserting_coin_id, apas in asserted_puzzle_announcements.items():
                for apa in apas:
                    if assertion == apa.msg:
                        asserted_by.append(asserting_coin_id.hex())
            print(f"CoinID: {coin_id.hex()}")
            print(f"Message: {cpa.msg.hex()}")
            print(f"Announces: {assertion}")
            if asserted_by:
                print("Asserted By Coins:")
                for c_id in asserted_by:
                    print(f"  ->  {c_id}")
            else:
                print("** Not Asserted **")
            print()

    print("Asserted Puzzle Announcements\n")
    for coin_id, apas in asserted_puzzle_announcements.items():
        for apa in apas:
            assertion = apa.msg
            created_by = []
            message = None
            for creating_coin_id, cpas in created_puzzle_announcements.items():
                for cpa in cpas:
                    if cpa.corresponding_assertion().msg_calc == assertion:
                        created_by.append(creating_coin_id.hex())
                        message = cpa.msg
            print(f"CoinID: {coin_id.hex()}")
            if message is not None:
                print(f"Message: {message.hex()}")
            print(f"Announces: {assertion}")
            if created_by:
                print("Asserted By Coins:")
                for c_id in created_by:
                    print(f"  ->  {c_id}")
            else:
                print("** Not Asserted **")
            print()

    print("-" * 80)
    print("COIN ANNOUNCEMENTS\n")

    print("Created Coin Announcements\n")
    for coin_id, ccas in created_coin_announcements.items():
        for cca in ccas:
            assertion = cca.corresponding_assertion().msg_calc
            asserted_by = []
            for asserting_coin_id, acas in asserted_coin_announcements.items():
                for aca in acas:
                    if assertion == aca.msg:
                        asserted_by.append(asserting_coin_id.hex())
            print(f"CoinID: {coin_id.hex()}")
            print(f"Message: {cca.msg.hex()}")
            print(f"Announces: {assertion}")
            if asserted_by:
                print("Asserted By Coins:")
                for c_id in asserted_by:
                    print(f"  ->  {c_id}")
            else:
                print("** Not Asserted **")
            print()

    print("Asserted Coin Announcements\n")
    for coin_id, acas in asserted_coin_announcements.items():
        for aca in acas:
            assertion = aca.msg
            created_by = []
            message = None
            for creating_coin_id, ccas in created_coin_announcements.items():
                for cca in ccas:
                    if cca.corresponding_assertion().msg_calc == assertion:
                        created_by.append(creating_coin_id.hex())
                        message = cca.msg
            print(f"CoinID: {coin_id.hex()}")
            if message is not None:
                print(f"Message: {message.hex()}")
            print(f"Announces: {assertion}")
            if created_by:
                print("Asserted By Coins:")
                for c_id in created_by:
                    print(f"  ->  {c_id}")
            else:
                print("** Not Asserted **")
            print()

    print("-" * 80)
    print("SENT MESSAGES")
    print()
    for coin_id, messages in sent_messages.items():
        coin = next((cs.coin for cs in spend_bundle.coin_spends if cs.coin.name() == coin_id), None)
        coin_list = [coin.parent_coin_info, coin.puzzle_hash, int_to_bytes(coin.amount)]
        for message in messages:
            mode = f"{message.mode:06b}"
            print(f"SENDER: {coin_id.hex()}")
            print(f"    Mode: {mode}")
            print(f"    Message: {message.msg}")

            sender_mode = mode[:3]
            receiver_mode = mode[3:]
            expected_receiver_args = []
            if sender_mode == "111":
                expected_receiver_args.append(Program.to(coin.name()))
            else:
                for i in range(3):
                    if int(sender_mode, 2) & (1 << (2 - i)):
                        expected_receiver_args.append(Program.to(coin_list[i]))
            # now find a matching receiver
            found = False
            for receiver_id, r_messages in received_messages.items():
                for r_message in r_messages:
                    if r_message.mode == message.mode:
                        if r_message.args == expected_receiver_args:
                            print(f"RECEIVER: {receiver_id.hex()}")
                            print(f"    Message: {r_message.msg}")
                            if r_message.msg != message.msg:
                                print("    ** Messages do not match **")
                            expected_sender_args = []
                            receiver_coin = next(
                                (cs.coin for cs in spend_bundle.coin_spends if cs.coin.name() == receiver_id), None
                            )
                            assert receiver_coin is not None
                            receiver_coin_list = [
                                receiver_coin.parent_coin_info,
                                receiver_coin.puzzle_hash,
                                int_to_bytes(receiver_coin.amount),
                            ]
                            if receiver_mode == "111":
                                expected_sender_args.append(Program.to(receiver_id))
                            else:
                                for i in range(3):
                                    if int(receiver_mode, 2) & (1 << (2 - i)):
                                        expected_sender_args.append(Program.to(receiver_coin_list[i]))
                            if expected_sender_args != message.args:
                                print("    ** Mismatched Sender Args **")
                            print()
                            found = True
            if not found:
                print("** RECEIVER NOT FOUND **")
                print()

    print("-" * 80)
    print("RECEIVED MESSAGES")
    print()
    for coin_id, messages in received_messages.items():
        coin = next((cs.coin for cs in spend_bundle.coin_spends if cs.coin.name() == coin_id), None)
        coin_list = [coin.parent_coin_info, coin.puzzle_hash, int_to_bytes(coin.amount)]
        for message in messages:
            mode = f"{message.mode:06b}"
            print(f"RECEIVER: {coin_id.hex()}")
            print(f"    Mode: {mode}")
            print(f"    Message: {message.msg}")

            sender_mode = mode[:3]
            receiver_mode = mode[3:]
            expected_sender_args = []
            if receiver_mode == "111":
                expected_sender_args.append(Program.to(coin.name()))
            else:
                for i in range(3):
                    if int(receiver_mode, 2) & (1 << (2 - i)):
                        expected_sender_args.append(Program.to(coin_list[i]))
            # now find a matching sender
            found = False
            for sender_id, s_messages in sent_messages.items():
                for s_message in s_messages:
                    if s_message.mode == message.mode:
                        if s_message.args == expected_sender_args:
                            print(f"SENDER: {sender_id.hex()}")
                            print(f"    Message: {s_message.msg}")
                            if s_message.msg != message.msg:
                                print("    ** Messages do not match **")
                            expected_receiver_args = []
                            sender_coin = next(
                                (cs.coin for cs in spend_bundle.coin_spends if cs.coin.name() == sender_id), None
                            )
                            assert sender_coin is not None
                            sender_coin_list = [
                                sender_coin.parent_coin_info,
                                sender_coin.puzzle_hash,
                                int_to_bytes(sender_coin.amount),
                            ]
                            if sender_mode == "111":
                                expected_receiver_args.append(Program.to(sender_id))
                            else:
                                for i in range(3):
                                    if int(sender_mode, 2) & (1 << (2 - i)):
                                        expected_receiver_args.append(Program.to(sender_coin_list[i]))
                            if expected_receiver_args != message.args:
                                print("    ** Mismatched Sender Args **")
                            print()
                            found = True
            if not found:
                print("** SENDER NOT FOUND **")
                print()

    print()
    print("=" * 80)
    print("SIGNATURES")
    print()
    validates = AugSchemeMPL.aggregate_verify(pks, msgs, spend_bundle.aggregated_signature)
    print(f"Aggregated signature check pass: {validates}")
    print()
    print("Public Keys:")
    for pk in pks:
        print(f"  {pk}")
    print()
    print("Messages")
    for msg in msgs:
        print(f"  {msg.hex()}")
    print()
    print("Additional Data:")
    print(f"  {agg_sig_additional_data.hex()}")
    print()
    print("Signature:")
    print(f"  {spend_bundle.aggregated_signature}")
    print()
