from standard_wallet.wallet import Wallet
import clvm
import sys
from chiasim.hashable import Program, ProgramHash, SpendBundle
from binascii import hexlify
from clvm_tools import binutils
from chiasim.wallet.BLSPrivateKey import BLSPrivateKey
from chiasim.validation.Conditions import ConditionOpcode
from chiasim.puzzles.p2_delegated_puzzle import puzzle_for_pk
from utilities.puzzle_utilities import puzzlehash_from_string
from utilities.keys import build_spend_bundle, sign_f_for_keychain


# ASWallet is subclass of Wallet
class ASWallet(Wallet):
    def __init__(self):
        self.as_pending_utxos = set()
        self.overlook = []
        super().__init__()
        return

    # special AS version of the standard get_keys function which allows both ...
    # ... parties in an atomic swap recreate an atomic swap puzzle which was ...
    # ... created by the other party
    def get_keys(self, hash, as_pubkey_sender = None, as_pubkey_receiver = None, as_amount = None, as_timelock_t = None, as_secret_hash = None):
        for child in reversed(range(self.next_address)):
            pubkey = self.extended_secret_key.public_child(child).get_public_key()
            if hash == ProgramHash(puzzle_for_pk(pubkey.serialize())):
                return (pubkey, self.extended_secret_key.private_child(child).get_private_key())
            elif as_pubkey_sender is not None and as_pubkey_receiver is not None and as_amount is not None and as_timelock_t is not None and as_secret_hash is not None:
                if hash == ProgramHash(self.as_make_puzzle(as_pubkey_sender, as_pubkey_receiver, as_amount, as_timelock_t, as_secret_hash)):
                    return (pubkey, self.extended_secret_key.private_child(child).get_private_key())

    def notify(self, additions, deletions, as_swap_list=[]):
        super().notify(additions, deletions)
        puzzlehashes = []
        for swap in as_swap_list:
            puzzlehashes.append(swap["outgoing puzzlehash"])
            puzzlehashes.append(swap["incoming puzzlehash"])
        if puzzlehashes != []:
            self.as_notify(additions, puzzlehashes)

    def as_notify(self, additions, puzzlehashes):
        for coin in additions:
            for puzzlehash in puzzlehashes:
                if hexlify(coin.puzzle_hash).decode('ascii') == puzzlehash and coin.puzzle_hash not in self.overlook:
                    self.as_pending_utxos.add(coin)
                    self.overlook.append(coin.puzzle_hash)

    # finds a pending atomic swap coin to be spent
    def as_select_coins(self, amount, as_puzzlehash):
        if amount > self.current_balance or amount < 0:
            return None
        used_utxos = set()
        if isinstance(as_puzzlehash, str):
            as_puzzlehash = puzzlehash_from_string(as_puzzlehash)
        coins = self.my_utxos.copy()
        for pcoin in self.as_pending_utxos:
            coins.add(pcoin)
        for coin in coins:
            if coin.puzzle_hash == as_puzzlehash:
                used_utxos.add(coin)
        return used_utxos

    # generates the hash of the secret used for the atomic swap coin hashlocks
    def as_generate_secret_hash(self, secret):
        secret_hash_cl = "(sha256 (q %s))" % (secret)
        sec = "(%s)" % secret
        cost, secret_hash_preformat = clvm.run_program(binutils.assemble("(sha256 (f (a)))"), binutils.assemble(sec))
        secret_hash = binutils.disassemble(secret_hash_preformat)
        return secret_hash

    def as_make_puzzle(self, as_pubkey_sender, as_pubkey_receiver, as_amount, as_timelock_block, as_secret_hash):
        as_pubkey_sender_cl = "0x%s" % (hexlify(as_pubkey_sender).decode('ascii'))
        as_pubkey_receiver_cl = "0x%s" % (hexlify(as_pubkey_receiver).decode('ascii'))
        as_payout_puzzlehash_receiver = ProgramHash(puzzle_for_pk(as_pubkey_receiver))
        as_payout_puzzlehash_sender = ProgramHash(puzzle_for_pk(as_pubkey_sender))
        payout_receiver = "(c (q 0x%s) (c (q 0x%s) (c (q %d) (q ()))))" % (hexlify(ConditionOpcode.CREATE_COIN).decode('ascii'), hexlify(as_payout_puzzlehash_receiver).decode('ascii'), as_amount)
        payout_sender = "(c (q 0x%s) (c (q 0x%s) (c (q %d) (q ()))))" % (hexlify(ConditionOpcode.CREATE_COIN).decode('ascii'), hexlify(as_payout_puzzlehash_sender).decode('ascii'), as_amount)
        aggsig_receiver = "(c (q 0x%s) (c (q %s) (c (sha256tree (a)) (q ()))))" % (hexlify(ConditionOpcode.AGG_SIG).decode('ascii'), as_pubkey_receiver_cl)
        aggsig_sender = "(c (q 0x%s) (c (q %s) (c (sha256tree (a)) (q ()))))" % (hexlify(ConditionOpcode.AGG_SIG).decode('ascii'), as_pubkey_sender_cl)
        receiver_puz = ("((c (i (= (sha256 (f (r (a)))) (q %s)) (q (c " + aggsig_receiver + " (c " + payout_receiver + " (q ())))) (q (x (q 'invalid secret')))) (a))) ) ") % (as_secret_hash)
        timelock = "(c (q 0x%s) (c (q %d) (q ()))) " % (hexlify(ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS).decode('ascii'), as_timelock_block)
        sender_puz = "(c " + aggsig_sender + " (c " + timelock + " (c " + payout_sender + " (q ()))))"
        as_puz_sender = "((c (i (= (f (a)) (q 77777)) (q " + sender_puz + ") (q (x (q 'not a valid option'))) ) (a)))"
        as_puz = "((c (i (= (f (a)) (q 33333)) (q " + receiver_puz + " (q " + as_puz_sender + ")) (a)))"
        return Program(binutils.assemble(as_puz))

    def as_get_new_puzzlehash(self, as_pubkey_sender, as_pubkey_receiver, as_amount, as_timelock_block, as_secret_hash):
        as_puz = self.as_make_puzzle(as_pubkey_sender, as_pubkey_receiver, as_amount, as_timelock_block, as_secret_hash)
        as_puzzlehash = ProgramHash(as_puz)
        return as_puzzlehash

    # 33333 is the receiver solution code prefix
    def as_make_solution_receiver(self, as_sec_to_try):
        sol = "(33333 "
        sol += "%s" % (as_sec_to_try)
        sol += ")"
        return Program(binutils.assemble(sol))

    # 77777 is the sender solution code prefix
    def as_make_solution_sender(self):
        sol = "(77777 "
        sol += ")"
        return Program(binutils.assemble(sol))

    # returns a list of tuples of the form (coin_name, puzzle_hash, conditions_dict, puzzle_solution_program)
    def as_solution_list(self, body_program):
        try:
            cost, sexp = clvm.run_program(body_program, [])
        except clvm.EvalError.EvalError:
            raise ValueError(body_program)
        npc_list = []
        for name_solution in sexp.as_iter():
            _ = name_solution.as_python()
            if len(_) != 2:
                raise ValueError(name_solution)
            if not isinstance(_[0], bytes) or len(_[0]) != 32:
                raise ValueError(name_solution)
            if not isinstance(_[1], list) or len(_[1]) != 2:
                raise ValueError(name_solution)
            puzzle_solution_program = name_solution.rest().first()
            puzzle_program = puzzle_solution_program.first()
            puzzle_hash = ProgramHash(Program(puzzle_program))
            npc_list.append((puzzle_hash, puzzle_solution_program))
        return npc_list

    def get_private_keys(self):
        return [BLSPrivateKey(self.extended_secret_key.private_child(child).get_private_key()) for child in range(self.next_address)]

    def make_keychain(self):
        private_keys = self.get_private_keys()
        return dict((_.public_key(), _) for _ in private_keys)

    def make_signer(self):
        return sign_f_for_keychain(self.make_keychain())

    def as_create_spend_bundle(self, as_puzzlehash, as_amount, as_timelock_block, as_secret_hash, as_pubkey_sender = None, as_pubkey_receiver = None, who = None, as_sec_to_try = None):
        utxos = self.as_select_coins(as_amount, as_puzzlehash)
        spends = []
        for coin in utxos:
            puzzle = self.as_make_puzzle(as_pubkey_sender, as_pubkey_receiver, as_amount, as_timelock_block, as_secret_hash)
            if who == "sender":
                solution = self.as_make_solution_sender()
            elif who == "receiver":
                solution = self.as_make_solution_receiver(as_sec_to_try)
            pair = solution.to([puzzle, solution])
            signer = self.make_signer()
            spend_bundle = build_spend_bundle(coin, Program(pair), sign_f=signer)
            spends.append(spend_bundle)
        return SpendBundle.aggregate(spends)


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
