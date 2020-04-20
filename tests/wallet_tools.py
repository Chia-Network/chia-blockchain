from typing import List, Optional, Dict, Tuple

import clvm
from clvm.casts import int_to_bytes, int_from_bytes
from os import urandom
from blspy import ExtendedPrivateKey

from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.spend_bundle import SpendBundle
from src.util.condition_tools import (
    conditions_by_opcode,
    hash_key_pairs_for_conditions_dict,
    conditions_for_solution,
)
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.puzzles.p2_conditions import puzzle_for_conditions
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from src.wallet.puzzles.puzzle_utils import (
    make_assert_coin_consumed_condition,
    make_assert_my_coin_id_condition,
    make_create_coin_condition,
    make_assert_block_index_exceeds_condition,
    make_assert_block_age_exceeds_condition,
    make_assert_aggsig_condition,
    make_assert_time_exceeds_condition,
    make_assert_fee_condition,
)


class WalletTool:
    seed = b"seed"
    next_address = 0
    pubkey_num_lookup: Dict[str, int] = {}

    def __init__(self):
        self.current_balance = 0
        self.my_utxos: set = set()
        self.seed = urandom(1024)
        self.extended_secret_key = ExtendedPrivateKey.from_seed(self.seed)
        self.generator_lookups: Dict = {}
        self.name = "MyChiaWallet"
        self.puzzle_pk_cache: Dict = {}

    def get_next_public_key(self):
        pubkey = self.extended_secret_key.public_child(
            self.next_address
        ).get_public_key()
        self.pubkey_num_lookup[bytes(pubkey)] = self.next_address
        self.next_address = self.next_address + 1
        return pubkey

    def set_name(self, name):
        self.name = name

    def can_generate_puzzle_hash(self, hash):
        return any(
            map(
                lambda child: hash
                == puzzle_for_pk(
                    bytes(self.extended_secret_key.public_child(child).get_public_key())
                ).get_tree_hash(),
                reversed(range(self.next_address)),
            )
        )

    def get_keys(self, puzzle_hash):
        if puzzle_hash in self.puzzle_pk_cache:
            child = self.puzzle_pk_cache[puzzle_hash]
            pubkey = self.extended_secret_key.public_child(child).get_public_key()
            private = self.extended_secret_key.private_child(child).get_private_key()
            return pubkey, private
        else:
            for child in range(self.next_address):
                pubkey = self.extended_secret_key.public_child(child).get_public_key()
                if puzzle_hash == puzzle_for_pk(bytes(pubkey)).get_tree_hash():
                    return (
                        pubkey,
                        self.extended_secret_key.private_child(child).get_private_key(),
                    )

    def puzzle_for_pk(self, pubkey):
        return puzzle_for_pk(pubkey)

    def get_new_puzzle(self):
        pubkey_a = self.get_next_public_key()
        pubkey = bytes(pubkey_a)
        puzzle = puzzle_for_pk(pubkey)
        self.puzzle_pk_cache[puzzle.get_tree_hash()] = self.next_address - 1
        return puzzle

    def get_new_puzzlehash(self):
        puzzle = self.get_new_puzzle()
        puzzlehash = puzzle.get_tree_hash()
        return puzzlehash

    def sign(self, value, pubkey):
        privatekey = self.extended_secret_key.private_child(
            self.pubkey_num_lookup[pubkey]
        ).get_private_key()
        blskey = BLSPrivateKey(privatekey)
        return blskey.sign(value)

    def make_solution(
        self, condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]]
    ):
        ret = []

        for con_list in condition_dic.values():
            for cvp in con_list:
                if cvp.opcode == ConditionOpcode.CREATE_COIN:
                    ret.append(make_create_coin_condition(cvp.var1, cvp.var2))
                if cvp.opcode == ConditionOpcode.AGG_SIG:
                    ret.append(make_assert_aggsig_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_COIN_CONSUMED:
                    ret.append(make_assert_coin_consumed_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_TIME_EXCEEDS:
                    ret.append(make_assert_time_exceeds_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_MY_COIN_ID:
                    ret.append(make_assert_my_coin_id_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
                    ret.append(make_assert_block_index_exceeds_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
                    ret.append(make_assert_block_age_exceeds_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_FEE:
                    ret.append(make_assert_fee_condition(cvp.var1))

        return clvm.to_sexp_f([puzzle_for_conditions(ret), []])

    def generate_unsigned_transaction(
        self,
        amount,
        newpuzzlehash,
        coin: Coin,
        condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]],
        fee: int = 0,
        secretkey=None,
    ):
        spends = []
        spend_value = coin.amount
        puzzle_hash = coin.puzzle_hash
        if secretkey is None:
            pubkey, secretkey = self.get_keys(puzzle_hash)
        else:
            pubkey = secretkey.get_public_key()
        puzzle = puzzle_for_pk(bytes(pubkey))
        if ConditionOpcode.CREATE_COIN not in condition_dic:
            condition_dic[ConditionOpcode.CREATE_COIN] = []

        output = ConditionVarPair(
            ConditionOpcode.CREATE_COIN, newpuzzlehash, int_to_bytes(amount)
        )
        condition_dic[output.opcode].append(output)
        amount_total = sum(
            int_from_bytes(cvp.var2)
            for cvp in condition_dic[ConditionOpcode.CREATE_COIN]
        )
        change = spend_value - amount_total - fee
        if change > 0:
            changepuzzlehash = self.get_new_puzzlehash()
            change_output = ConditionVarPair(
                ConditionOpcode.CREATE_COIN, changepuzzlehash, int_to_bytes(change)
            )
            condition_dic[output.opcode].append(change_output)
            solution = self.make_solution(condition_dic)
        else:
            solution = self.make_solution(condition_dic)

        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    def sign_transaction(self, spends: List[Tuple[Program, CoinSolution]]):
        sigs = []
        solution: Program
        puzzle: Program
        for puzzle, solution in spends:  # type: ignore # noqa
            pubkey, secretkey = self.get_keys(solution.coin.puzzle_hash)
            secretkey = BLSPrivateKey(secretkey)
            code_ = [puzzle, solution.solution]
            sexp = Program.to(code_)
            err, con, cost = conditions_for_solution(sexp)
            if not con:
                return
            conditions_dict = conditions_by_opcode(con)

            for _ in hash_key_pairs_for_conditions_dict(
                conditions_dict, bytes(solution.coin)
            ):
                signature = secretkey.sign(_.message_hash)
                sigs.append(signature)
        aggsig = BLSSignature.aggregate(sigs)
        solution_list: List[CoinSolution] = [
            CoinSolution(
                coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])
            )
            for (puzzle, coin_solution) in spends
        ]
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def generate_signed_transaction(
        self,
        amount,
        newpuzzlehash,
        coin: Coin,
        condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]] = None,
        fee: int = 0,
    ) -> Optional[SpendBundle]:
        if condition_dic is None:
            condition_dic = {}
        transaction = self.generate_unsigned_transaction(
            amount, newpuzzlehash, coin, condition_dic, fee
        )
        if transaction is None:
            return None
        return self.sign_transaction(transaction)
