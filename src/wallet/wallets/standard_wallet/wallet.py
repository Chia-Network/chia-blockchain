from typing import List, Optional

import clvm
from os import urandom
from blspy import ExtendedPrivateKey

from src.types.hashable import ProgramHash, CoinSolution, SpendBundle, Program, BLSSignature, Coin
from src.util.condition_tools import conditions_by_opcode, hash_key_pairs_for_conditions_dict, conditions_for_solution
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.puzzles.p2_conditions import puzzle_for_conditions
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from src.wallet.puzzles.puzzle_utils import make_assert_coin_consumed_condition, make_assert_min_time_condition, \
    make_assert_my_coin_id_condition, make_create_coin_condition


class Wallet:
    seed = b'seed'
    next_address = 0
    pubkey_num_lookup = {}

    def __init__(self):
        self.current_balance = 0
        self.my_utxos = set()
        self.seed = urandom(1024)
        self.extended_secret_key = ExtendedPrivateKey.from_seed(self.seed)
        # self.contacts = {}  # {'name': (puzzlegenerator, last, extradata)}
        self.generator_lookups = {}  # {generator_hash: generator}
        self.name = "MyChiaWallet"
        self.temp_utxos = set()
        self.temp_balance = 0
        self.all_additions = {}
        self.all_deletions = {}

    def get_next_public_key(self):
        pubkey = self.extended_secret_key.public_child(
            self.next_address).get_public_key()
        self.pubkey_num_lookup[pubkey.serialize()] = self.next_address
        self.next_address = self.next_address + 1
        return pubkey

    # def add_contact(self, name, puzzlegenerator, last, extradata):
    #    if name in self.contacts:
    #        return None
    #    else:
    #        self.contacts[name] = [puzzlegenerator, last, extradata]

    def set_name(self, name):
        self.name = name

    def can_generate_puzzle_hash(self, hash):
        return any(map(lambda child: hash == ProgramHash(puzzle_for_pk(
            self.extended_secret_key.public_child(child).get_public_key().serialize())),
            reversed(range(self.next_address))))

    def get_keys(self, hash):
        for child in range(self.next_address):
            pubkey = self.extended_secret_key.public_child(
                child).get_public_key()
            if hash == ProgramHash(puzzle_for_pk(pubkey.serialize())):
                return (pubkey, self.extended_secret_key.private_child(child).get_private_key())

    def notify(self, additions, deletions):
        for coin in additions:
            if coin.name() in self.all_additions:
                continue
            self.all_additions[coin.name()] = coin
            if self.can_generate_puzzle_hash(coin.puzzle_hash):
                self.current_balance += coin.amount
                self.my_utxos.add(coin)
        for coin in deletions:
            if coin.name() in self.all_deletions:
                continue
            self.all_deletions[coin.name()] = coin
            if coin in self.my_utxos:
                self.my_utxos.remove(coin)
                self.current_balance -= coin.amount

        self.temp_utxos = self.my_utxos.copy()
        self.temp_balance = self.current_balance

    def select_coins(self, amount):
        if amount > self.temp_balance:
            return None
        used_utxos = set()
        while sum(map(lambda coin: coin.amount, used_utxos)) < amount:
            used_utxos.add(self.temp_utxos.pop())
        return used_utxos

    def puzzle_for_pk(self, pubkey):
        return puzzle_for_pk(pubkey)

    def get_new_puzzle(self):
        pubkey = self.get_next_public_key().serialize()
        puzzle = puzzle_for_pk(pubkey)
        return puzzle

    def get_new_puzzlehash(self):
        puzzle = self.get_new_puzzle()
        puzzlehash = ProgramHash(puzzle)
        return puzzlehash

    def sign(self, value, pubkey):
        privatekey = self.extended_secret_key.private_child(
            self.pubkey_num_lookup[pubkey]).get_private_key()
        blskey = BLSPrivateKey(privatekey)
        return blskey.sign(value)

    def make_solution(self, primaries=[], min_time=0, me={}, consumed=[]):
        ret = []
        for primary in primaries:
            ret.append(make_create_coin_condition(
                primary['puzzlehash'], primary['amount']))
        for coin in consumed:
            ret.append(make_assert_coin_consumed_condition(coin))
        if min_time > 0:
            ret.append(make_assert_min_time_condition(min_time))
        if me:
            ret.append(make_assert_my_coin_id_condition(me['id']))
        return clvm.to_sexp_f([puzzle_for_conditions(ret), []])

    def generate_unsigned_transaction(self, amount, newpuzzlehash, fee: int = 0):
        if self.temp_balance < amount:
            return None  # TODO: Should we throw a proper error here, or just return None?
        utxos = self.select_coins(amount + fee)
        spends = []
        output_created = False
        spend_value = sum([coin.amount for coin in utxos])
        change = spend_value - amount - fee
        for coin in utxos:
            puzzle_hash = coin.puzzle_hash

            pubkey, secretkey = self.get_keys(puzzle_hash)
            puzzle = puzzle_for_pk(pubkey.serialize())
            if output_created is False:
                primaries = [{'puzzlehash': newpuzzlehash, 'amount': amount}]
                if change > 0:
                    changepuzzlehash = self.get_new_puzzlehash()
                    primaries.append(
                        {'puzzlehash': changepuzzlehash, 'amount': change})
                    # add change coin into temp_utxo set
                    self.temp_utxos.add(Coin(coin, changepuzzlehash, change))
                solution = self.make_solution(primaries=primaries)
                output_created = True
            else:
                solution = self.make_solution(consumed=[coin.name()])
            spends.append((puzzle, CoinSolution(coin, solution)))
        self.temp_balance -= (amount + fee)
        return spends

    def sign_transaction(self, spends: (Program, [CoinSolution])):
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = self.get_keys(solution.coin.puzzle_hash)
            secretkey = BLSPrivateKey(secretkey)
            code_ = [puzzle, solution.solution]
            sexp = clvm.to_sexp_f(code_)
            err, con = conditions_for_solution(sexp)
            conditions_dict = conditions_by_opcode(con)

            for _ in hash_key_pairs_for_conditions_dict(conditions_dict):
                signature = secretkey.sign(_.message_hash)
                sigs.append(signature)
        aggsig = BLSSignature.aggregate(sigs)
        solution_list: List[CoinSolution] = [CoinSolution(coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])) for
             (puzzle, coin_solution) in spends]
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    def generate_signed_transaction(self, amount, newpuzzlehash, fee: int = 0) -> Optional[SpendBundle]:
        transaction = self.generate_unsigned_transaction(amount, newpuzzlehash, fee)
        if transaction is None:
            return None  # TODO: Should we throw a proper error here, or just return None?
        return self.sign_transaction(transaction)


"""
Copyright 2018 Chia Network Inc
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
   http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
