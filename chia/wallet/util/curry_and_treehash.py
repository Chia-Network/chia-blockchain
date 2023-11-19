from __future__ import annotations

from hashlib import sha256
from typing import Callable, List

from chia.types.blockchain_format.sized_bytes import bytes32

CurryHashFunction = Callable[..., bytes32]


NULL = bytes.fromhex("")
ONE = bytes.fromhex("01")
TWO = bytes.fromhex("02")
Q_KW = bytes.fromhex("01")
A_KW = bytes.fromhex("02")
C_KW = bytes.fromhex("04")


def shatree_atom(atom: bytes) -> bytes32:
    s = sha256()
    s.update(ONE)
    s.update(atom)
    return bytes32(s.digest())


def shatree_pair(left_hash: bytes32, right_hash: bytes32) -> bytes32:
    s = sha256()
    s.update(TWO)
    s.update(left_hash)
    s.update(right_hash)
    return bytes32(s.digest())


Q_KW_TREEHASH = shatree_atom(Q_KW)
A_KW_TREEHASH = shatree_atom(A_KW)
C_KW_TREEHASH = shatree_atom(C_KW)
ONE_TREEHASH = shatree_atom(ONE)
NULL_TREEHASH = shatree_atom(NULL)


# The environment `E = (F . R)` recursively expands out to
# `(c . ((q . F) . EXPANSION(R)))` if R is not 0
# `1` if R is 0


def curried_values_tree_hash(arguments: List[bytes32]) -> bytes32:
    if len(arguments) == 0:
        return ONE_TREEHASH

    return shatree_pair(
        C_KW_TREEHASH,
        shatree_pair(
            shatree_pair(Q_KW_TREEHASH, arguments[0]),
            shatree_pair(curried_values_tree_hash(arguments[1:]), NULL_TREEHASH),
        ),
    )


# The curry pattern is `(a . ((q . F)  . (E . 0)))` == `(a (q . F) E)
# where `F` is the `mod` and `E` is the curried environment


def curry_and_treehash(hash_of_quoted_mod_hash: bytes32, *hashed_arguments: bytes32) -> bytes32:
    """
    `hash_of_quoted_mod_hash` : tree hash of `(q . MOD)` where `MOD` is template to be curried
    `arguments` : tree hashes of arguments to be curried
    """

    curried_values = curried_values_tree_hash(list(hashed_arguments))
    return shatree_pair(
        A_KW_TREEHASH,
        shatree_pair(hash_of_quoted_mod_hash, shatree_pair(curried_values, NULL_TREEHASH)),
    )


def calculate_hash_of_quoted_mod_hash(mod_hash: bytes32) -> bytes32:
    return shatree_pair(Q_KW_TREEHASH, mod_hash)
