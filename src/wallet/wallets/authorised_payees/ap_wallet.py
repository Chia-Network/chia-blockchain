from standard_wallet.wallet import Wallet
import clvm
from chiasim.hashable import Program, ProgramHash, CoinSolution, SpendBundle, BLSSignature
from chiasim.hashable.Coin import Coin
from chiasim.hashable.CoinSolution import CoinSolutionList
from clvm_tools import binutils
from chiasim.wallet.BLSPrivateKey import BLSPrivateKey
from blspy import PublicKey
from chiasim.puzzles.p2_delegated_puzzle import puzzle_for_pk
from .ap_wallet_a_functions import ap_make_puzzle, ap_make_aggregation_puzzle
from utilities.puzzle_utilities import puzzlehash_from_string
from chiasim.validation.Conditions import ConditionOpcode


class APWallet(Wallet):
    def __init__(self):
        super().__init__()
        self.aggregation_coins = set()
        self.a_pubkey = None
        self.AP_puzzlehash = None
        self.approved_change_puzzle = None
        self.approved_change_signature = None
        self.temp_coin = None
        return

    def set_sender_values(self, AP_puzzlehash, a_pubkey_used):
        if isinstance(AP_puzzlehash, str):
            self.AP_puzzlehash = puzzlehash_from_string(AP_puzzlehash)
        else:
            self.AP_puzzlehash = AP_puzzlehash

        if isinstance(a_pubkey_used, str):
            a_pubkey = PublicKey.from_bytes(bytes.fromhex(a_pubkey_used))
            self.a_pubkey = a_pubkey
        else:
            self.a_pubkey = a_pubkey_used

    def set_approved_change_signature(self, signature):
        self.approved_change_signature = signature

    # allows wallet A to generate and sign permitted puzzlehashes ahead of time
    # returns a tuple of (puzhash, signature)
    def ap_generate_signatures(self, puzhashes, oldpuzzlehash, b_pubkey_used):
        puzhash_signature_list = []
        pubkey, secretkey = self.get_keys(oldpuzzlehash, None, b_pubkey_used)
        blskey = BLSPrivateKey(secretkey)
        signature = blskey.sign(oldpuzzlehash)
        puzhash_signature_list.append((oldpuzzlehash, signature))
        for p in puzhashes:
            signature = blskey.sign(p)
            puzhash_signature_list.append((p, signature))

        return puzhash_signature_list

    # pass in a_pubkey if you want the AP mode
    def get_keys(self, hash, a_pubkey_used=None, b_pubkey_used=None):
        for child in reversed(range(self.next_address)):
            pubkey = self.extended_secret_key.public_child(
                child).get_public_key()
            if hash == ProgramHash(puzzle_for_pk(pubkey.serialize())):
                return (pubkey, self.extended_secret_key.private_child(child).get_private_key())
            if a_pubkey_used is not None and b_pubkey_used is None:
                if hash == ProgramHash(ap_make_puzzle(a_pubkey_used, pubkey.serialize())):
                    return (pubkey, self.extended_secret_key.private_child(child).get_private_key())
            elif a_pubkey_used is None and b_pubkey_used is not None:
                if hash == ProgramHash(ap_make_puzzle(pubkey.serialize(), b_pubkey_used)):
                    return (pubkey, self.extended_secret_key.private_child(child).get_private_key())

    def notify(self, additions, deletions):
        super().notify(additions, deletions)
        self.my_utxos = self.temp_utxos
        self.ap_notify(additions)
        spend_bundle_list = self.ac_notify(additions)
        return spend_bundle_list

    def ap_notify(self, additions):
        # this prevents unnecessary checks and stops us receiving multiple coins
        if self.AP_puzzlehash is not None and not self.my_utxos:
            for coin in additions:
                if coin.puzzle_hash == self.AP_puzzlehash:
                    self.current_balance += coin.amount
                    self.my_utxos.add(coin)
                    print("this coin is locked using my ID, it's output must be for me")

    def ac_notify(self, additions):
        if len(self.my_utxos) >= 1:
            self.temp_coin = self.my_utxos.copy().pop()  # reset temp_coin
        else:
            return  # prevent unnecessary searching
        spend_bundle_list = []

        for coin in additions:
            my_utxos_copy = self.my_utxos.copy()
            for mycoin in self.my_utxos:
                # Check if we have already spent any coins in our utxo set
                if coin.parent_coin_info == mycoin.name():
                    my_utxos_copy.remove(mycoin)
                    self.current_balance -= mycoin.amount
                    self.my_utxos = my_utxos_copy.copy()
                    self.temp_coin = my_utxos_copy.copy().pop()

            if ProgramHash(ap_make_aggregation_puzzle(self.temp_coin.puzzle_hash)) == coin.puzzle_hash:
                self.aggregation_coins.add(coin)
                spend_bundle = self.ap_generate_signed_aggregation_transaction()
                spend_bundle_list.append(spend_bundle)

        if spend_bundle_list:
            return spend_bundle_list
        else:
            return None

    # creates the solution that will allow wallet B to spend the coin
    # Wallet B is allowed to make multiple spends but must spend the coin in its entirety
    def ap_make_solution_mode_1(self, outputs=[], my_primary_input=0x0000, my_puzzle_hash=0x0000):
        sol = "(1 (a) ("
        for puzhash, amount in outputs:
            sol += f"(0x{ConditionOpcode.CREATE_COIN.hex()} 0x{puzhash.hex()} {amount})"
        sol += f") 0x{my_primary_input.hex()} 0x{my_puzzle_hash.hex()})"
        return Program(binutils.assemble(sol))

    def ac_make_aggregation_solution(self, myid, wallet_coin_primary_input, wallet_coin_amount):
        sol = f"(0x{myid.hex()} 0x{wallet_coin_primary_input.hex()} {wallet_coin_amount})"
        return Program(binutils.assemble(sol))

    def ap_make_solution_mode_2(self, wallet_puzzle_hash, consolidating_primary_input, consolidating_coin_puzzle_hash, outgoing_amount, my_primary_input, incoming_amount):
        sol = f"(2 0x{wallet_puzzle_hash.hex()} 0x{consolidating_primary_input.hex()} 0x{consolidating_coin_puzzle_hash.hex()} {outgoing_amount} 0x{my_primary_input.hex()} {incoming_amount})"
        return Program(binutils.assemble(sol))

    # this is for sending a recieved ap coin, not creating a new ap coin
    def ap_generate_unsigned_transaction(self, puzzlehash_amount_list):
        # we only have/need one coin in this wallet at any time - this code can be improved
        spends = []
        coin = self.temp_coin
        puzzle_hash = coin.puzzle_hash

        pubkey, secretkey = self.get_keys(puzzle_hash, self.a_pubkey)
        puzzle = ap_make_puzzle(self.a_pubkey, pubkey.serialize())
        solution = self.ap_make_solution_mode_1(
            puzzlehash_amount_list, coin.parent_coin_info, puzzle_hash)
        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    # this allows wallet A to approve of new puzzlehashes/spends from wallet B that weren't in the original list
    def ap_sign_output_newpuzzlehash(self, puzzlehash, newpuzzlehash, b_pubkey_used):
        pubkey, secretkey = self.get_keys(puzzlehash, None, b_pubkey_used)
        signature = BLSPrivateKey(secretkey).sign(newpuzzlehash)
        return signature

    # this is for sending a locked coin
    # Wallet B must sign the whole transaction, and the appropriate puzhash signature from A must be included
    def ap_sign_transaction(self, spends: (Program, [CoinSolution]), signatures_from_a):
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = self.get_keys(
                solution.coin.puzzle_hash, self.a_pubkey)
            secretkey = BLSPrivateKey(secretkey)
            signature = secretkey.sign(
                ProgramHash(Program(solution.solution)))
            sigs.append(signature)
        for s in signatures_from_a:
            sigs.append(s)
        aggsig = BLSSignature.aggregate(sigs)
        solution_list = CoinSolutionList(
            [CoinSolution(coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])) for
             (puzzle, coin_solution) in spends])
        spend_bundle = SpendBundle(solution_list, aggsig)
        return spend_bundle

    # this is for sending a recieved ap coin, not sending a new ap coin
    def ap_generate_signed_transaction(self, puzzlehash_amount_list, signatures_from_a):

        # calculate amount of transaction and change
        spend_value = 0
        for puzzlehash, amount in puzzlehash_amount_list:
            spend_value += amount
        if spend_value > self.temp_coin.amount:
            return None
        change = self.current_balance - spend_value
        puzzlehash_amount_list.append((self.AP_puzzlehash, change))
        signatures_from_a.append(self.approved_change_signature)
        #breakpoint()
        transaction = self.ap_generate_unsigned_transaction(
            puzzlehash_amount_list)
        self.temp_coin = Coin(self.temp_coin, self.temp_coin.puzzle_hash,
                              change)
        return self.ap_sign_transaction(transaction, signatures_from_a)

    # This is for using the AC locked coin and aggregating it into wallet - must happen in same block as AP Mode 2
    def ap_generate_signed_aggregation_transaction(self):
        list_of_coinsolutions = []
        if self.aggregation_coins is False:  # empty sets evaluate to false in python
            return
        consolidating_coin = self.aggregation_coins.pop()

        pubkey, secretkey = self.get_keys(
            self.temp_coin.puzzle_hash, self.a_pubkey)

        # Spend wallet coin
        puzzle = ap_make_puzzle(self.a_pubkey, pubkey.serialize())
        solution = self.ap_make_solution_mode_2(self.temp_coin.puzzle_hash, consolidating_coin.parent_coin_info,
                                                consolidating_coin.puzzle_hash, consolidating_coin.amount, self.temp_coin.parent_coin_info, self.temp_coin.amount)
        signature = BLSPrivateKey(secretkey).sign(ProgramHash(solution))
        list_of_coinsolutions.append(CoinSolution(
            self.temp_coin, clvm.to_sexp_f([puzzle, solution])))

        # Spend consolidating coin
        puzzle = ap_make_aggregation_puzzle(self.temp_coin.puzzle_hash)
        solution = self.ac_make_aggregation_solution(consolidating_coin.name(
        ), self.temp_coin.parent_coin_info, self.temp_coin.amount)
        list_of_coinsolutions.append(CoinSolution(
            consolidating_coin, clvm.to_sexp_f([puzzle, solution])))
        # Spend lock
        puzstring = f"(r (c (q 0x{consolidating_coin.name().hex()}) (q ())))"
        puzzle = Program(binutils.assemble(puzstring))
        solution = Program(binutils.assemble("()"))
        list_of_coinsolutions.append(CoinSolution(Coin(self.temp_coin, ProgramHash(
            puzzle), 0), clvm.to_sexp_f([puzzle, solution])))

        self.temp_coin = Coin(self.temp_coin, self.temp_coin.puzzle_hash,
                              self.temp_coin.amount + consolidating_coin.amount)
        aggsig = BLSSignature.aggregate([signature])
        solution_list = CoinSolutionList(list_of_coinsolutions)
        return SpendBundle(solution_list, aggsig)


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
