from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
from clvm.casts import int_from_bytes, int_to_bytes

from chia.consensus.constants import ConsensusConstants
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import agg_sig_additional_data, conditions_dict_for_solution, make_aggsig_final_message
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)

DEFAULT_SEED = b"seed" * 8
assert len(DEFAULT_SEED) == 32


class WalletTool:
    next_address = 0
    pubkey_num_lookup: Dict[bytes, uint32] = {}
    puzzle_pk_cache: Dict[bytes32, PrivateKey] = {}

    def __init__(self, constants: ConsensusConstants, sk: Optional[PrivateKey] = None):
        self.constants = constants
        self.current_balance = 0
        self.my_utxos: set = set()
        if sk is not None:
            self.private_key = sk
        else:
            self.private_key = AugSchemeMPL.key_gen(DEFAULT_SEED)
        self.generator_lookups: Dict = {}
        self.puzzle_pk_cache: Dict = {}
        self.get_new_puzzle()

    def get_next_address_index(self) -> uint32:
        self.next_address = uint32(self.next_address + 1)
        return self.next_address

    def get_private_key_for_puzzle_hash(self, puzzle_hash: bytes32) -> PrivateKey:
        sk = self.puzzle_pk_cache.get(puzzle_hash)
        if sk:
            return sk
        for child in range(self.next_address):
            pubkey = master_sk_to_wallet_sk(self.private_key, uint32(child)).get_g1()
            if puzzle_hash == puzzle_for_pk(pubkey).get_tree_hash():
                return master_sk_to_wallet_sk(self.private_key, uint32(child))
        raise ValueError(f"Do not have the keys for puzzle hash {puzzle_hash}")

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        return puzzle_for_pk(pubkey)

    def get_new_puzzle(self) -> Program:
        next_address_index: uint32 = self.get_next_address_index()
        sk: PrivateKey = master_sk_to_wallet_sk(self.private_key, next_address_index)
        pubkey: G1Element = sk.get_g1()
        self.pubkey_num_lookup[bytes(pubkey)] = next_address_index

        puzzle: Program = puzzle_for_pk(pubkey)

        self.puzzle_pk_cache[puzzle.get_tree_hash()] = sk
        return puzzle

    def get_new_puzzlehash(self) -> bytes32:
        puzzle = self.get_new_puzzle()
        return puzzle.get_tree_hash()

    def sign(self, value: bytes, pubkey: bytes) -> G2Element:
        privatekey: PrivateKey = master_sk_to_wallet_sk(self.private_key, self.pubkey_num_lookup[pubkey])
        return AugSchemeMPL.sign(privatekey, value)

    def make_solution(self, condition_dic: Dict[ConditionOpcode, List[ConditionWithArgs]]) -> Program:
        ret = []

        for con_list in condition_dic.values():
            for cvp in con_list:
                if cvp.opcode == ConditionOpcode.CREATE_COIN and len(cvp.vars) > 2:
                    formatted: List[Any] = []
                    formatted.extend(cvp.vars)
                    formatted[2] = cvp.vars[2:]
                    ret.append([cvp.opcode.value] + formatted)
                else:
                    ret.append([cvp.opcode.value] + cvp.vars)
        return solution_for_conditions(Program.to(ret))

    def generate_unsigned_transaction(
        self,
        amount: uint64,
        new_puzzle_hash: bytes32,
        coins: List[Coin],
        condition_dic: Dict[ConditionOpcode, List[ConditionWithArgs]],
        fee: int = 0,
        secret_key: Optional[PrivateKey] = None,
        additional_outputs: Optional[List[Tuple[bytes32, int]]] = None,
        memo: Optional[bytes32] = None,
    ) -> List[CoinSpend]:
        spends = []

        spend_value = sum([c.amount for c in coins])

        if ConditionOpcode.CREATE_COIN not in condition_dic:
            condition_dic[ConditionOpcode.CREATE_COIN] = []
        if ConditionOpcode.CREATE_COIN_ANNOUNCEMENT not in condition_dic:
            condition_dic[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT] = []

        coin_create = [new_puzzle_hash, int_to_bytes(amount)]
        if memo is not None:
            coin_create.append(memo)
        output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, coin_create)
        condition_dic[output.opcode].append(output)
        if additional_outputs is not None:
            for o in additional_outputs:
                out = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [o[0], int_to_bytes(o[1])])
                condition_dic[out.opcode].append(out)

        amount_total = sum(int_from_bytes(cvp.vars[1]) for cvp in condition_dic[ConditionOpcode.CREATE_COIN])
        change = spend_value - amount_total - fee
        if change > 0:
            change_puzzle_hash = self.get_new_puzzlehash()
            change_output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [change_puzzle_hash, int_to_bytes(change)])
            condition_dic[output.opcode].append(change_output)

        secondary_coins_cond_dic: Dict[ConditionOpcode, List[ConditionWithArgs]] = dict()
        secondary_coins_cond_dic[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT] = []
        for n, coin in enumerate(coins):
            puzzle_hash = coin.puzzle_hash
            if secret_key is None:
                secret_key = self.get_private_key_for_puzzle_hash(puzzle_hash)
            pubkey = secret_key.get_g1()
            puzzle: Program = puzzle_for_pk(pubkey)
            if n == 0:
                message_list = [c.name() for c in coins]
                for outputs in condition_dic[ConditionOpcode.CREATE_COIN]:
                    coin_to_append = Coin(
                        coin.name(),
                        bytes32(outputs.vars[0]),
                        int_from_bytes(outputs.vars[1]),
                    )
                    message_list.append(coin_to_append.name())
                message = std_hash(b"".join(message_list))
                condition_dic[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT].append(
                    ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [message])
                )
                primary_announcement_hash = Announcement(coin.name(), message).name()
                secondary_coins_cond_dic[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT].append(
                    ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [primary_announcement_hash])
                )
                main_solution = self.make_solution(condition_dic)
                spends.append(
                    CoinSpend(
                        coin, SerializedProgram.from_program(puzzle), SerializedProgram.from_program(main_solution)
                    )
                )
            else:
                spends.append(
                    CoinSpend(
                        coin,
                        SerializedProgram.from_program(puzzle),
                        SerializedProgram.from_program(self.make_solution(secondary_coins_cond_dic)),
                    )
                )
        return spends

    def sign_transaction(self, coin_spends: List[CoinSpend]) -> SpendBundle:
        signatures = []
        data = agg_sig_additional_data(self.constants.AGG_SIG_ME_ADDITIONAL_DATA)
        agg_sig_opcodes = [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_ME,
        ]
        for coin_spend in coin_spends:
            secret_key = self.get_private_key_for_puzzle_hash(coin_spend.coin.puzzle_hash)
            synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
            conditions_dict = conditions_dict_for_solution(
                coin_spend.puzzle_reveal, coin_spend.solution, self.constants.MAX_BLOCK_COST_CLVM
            )

            for cwa in conditions_dict.get(ConditionOpcode.AGG_SIG_UNSAFE, []):
                msg = cwa.vars[1]
                signature = AugSchemeMPL.sign(synthetic_secret_key, msg)
                signatures.append(signature)

            for agg_sig_opcode in agg_sig_opcodes:
                for cwa in conditions_dict.get(agg_sig_opcode, []):
                    msg = make_aggsig_final_message(agg_sig_opcode, cwa.vars[1], coin_spend.coin, data)
                    signature = AugSchemeMPL.sign(synthetic_secret_key, msg)
                    signatures.append(signature)

        aggsig = AugSchemeMPL.aggregate(signatures)
        spend_bundle = SpendBundle(coin_spends, aggsig)
        return spend_bundle

    def generate_signed_transaction(
        self,
        amount: uint64,
        new_puzzle_hash: bytes32,
        coin: Coin,
        condition_dic: Dict[ConditionOpcode, List[ConditionWithArgs]] = None,
        fee: int = 0,
        additional_outputs: Optional[List[Tuple[bytes32, int]]] = None,
        memo: Optional[bytes32] = None,
    ) -> SpendBundle:
        if condition_dic is None:
            condition_dic = {}
        transaction = self.generate_unsigned_transaction(
            amount, new_puzzle_hash, [coin], condition_dic, fee, additional_outputs=additional_outputs, memo=memo
        )
        assert transaction is not None
        return self.sign_transaction(transaction)

    def generate_signed_transaction_multiple_coins(
        self,
        amount: uint64,
        new_puzzle_hash: bytes32,
        coins: List[Coin],
        condition_dic: Dict[ConditionOpcode, List[ConditionWithArgs]] = None,
        fee: int = 0,
        additional_outputs: Optional[List[Tuple[bytes32, int]]] = None,
    ) -> SpendBundle:
        if condition_dic is None:
            condition_dic = {}
        transaction = self.generate_unsigned_transaction(
            amount, new_puzzle_hash, coins, condition_dic, fee, additional_outputs=additional_outputs
        )
        assert transaction is not None
        return self.sign_transaction(transaction)
