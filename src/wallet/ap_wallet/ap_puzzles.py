from typing import Optional, Tuple

from clvm_tools import binutils
import clvm
import string
from src.types.BLSSignature import BLSSignature
from src.types.program import Program
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode

# This is for spending an existing coloured coin
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.util.ints import uint64
from blspy import PublicKey


# this is for wallet A to generate the permitted puzzlehashes and sign them ahead of time
# returns a list of tuples of (puzhash, signature)
# not sure about how best to communicate/store who/what the puzzlehashes are, or if this is even important
def ap_generate_signatures(puzhashes, oldpuzzlehash, a_wallet, a_pubkey_used):
    puzhash_signature_list = []
    for p in puzhashes:
        signature = a_wallet.sign(p, a_pubkey_used)
        puzhash_signature_list.append((p, signature))
    return puzhash_signature_list


# this creates our authorised payee puzzle
def ap_make_puzzle(a_pubkey, b_pubkey):
    a_pubkey_formatted = f"0x{bytes(a_pubkey).hex()}"
    b_pubkey_formatted = f"0x{bytes(b_pubkey).hex()}"

    # Mode one is for spending to one of the approved destinations
    # Solution contains (option 1 flag, new puzzle, new solution, my_primary_input, wallet_puzzle_hash)

    # Below is the result of compiling ap_wallet.clvm
    puz = f"((c (q (c (c (q 57) (c (q {b_pubkey_formatted}) (c ((c (r (f (a))) (c (f (a)) (c (c (f (r (a))) (c (f (r (r (a)))) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (q ()))))) (q ()))))) (q ())))) ((c (f (f (a))) (c (f (a)) (c ((c (f (r (a))) (f (r (r (a)))))) (c (q ()) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (q (()))))))))))) (c (q (((c (i (f (r (a))) (q ((c (i (= (f (f (f (r (a))))) (q 51)) (q ((c (f (f (a))) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (c (c (q 50) (c (q {a_pubkey_formatted}) (c (f (r (f (f (r (a)))))) (q ())))) (f (r (r (a)))))) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (c (+ (f (r (r (f (f (r (a))))))) (f (r (r (r (r (r (a)))))))) (q ())))))))))) (q ((c (f (f (a))) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (f (r (r (a))))) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (c (f (r (r (r (r (r (a))))))) (q ()))))))))))) (a)))) (q (c (c (q 53) (c (sha256 (f (r (r (r (a))))) (f (r (r (r (r (a)))))) (f (r (r (r (r (r (a)))))))) (q ()))) (f (r (r (a))))))) (a))) (c (i (l (f (r (a)))) (q (sha256 (q 2) ((c (r (f (a))) (c (f (a)) (c (f (f (r (a)))) (q ()))))) ((c (r (f (a))) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (sha256 (q 1) (f (r (a)))))) (a)))) (a))))"
    return Program(binutils.assemble(puz))


# returns the ProgramHash of a new puzzle
def ap_get_new_puzzlehash(a_pubkey_serialized, b_pubkey_serialized):
    return ap_make_puzzle(a_pubkey_serialized, b_pubkey_serialized).get_tree_hash()


# this allows wallet A to approve of new puzzlehashes/spends from wallet B that weren't in the original list
def ap_sign_output_newpuzzlehash(newpuzzlehash, a_wallet, a_pubkey_used):
    signature = a_wallet.sign(newpuzzlehash, a_pubkey_used)
    return signature


# creates the solution that will allow wallet B to spend the coin
# Wallet B is allowed to make multiple spends but must spend the coin in its entirety
def ap_make_solution(outputs, my_primary_input, my_puzzle_hash):
    sol = "((a) ("
    for puzhash, amount in outputs:
        sol += f"(0x{ConditionOpcode.CREATE_COIN.hex()} 0x{puzhash.hex()} {amount})"
    sol += f") 0x{my_primary_input.hex()} 0x{my_puzzle_hash.hex()})"
    return Program(binutils.assemble(sol))


"""
Copyright 2020 Chia Network Inc
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
