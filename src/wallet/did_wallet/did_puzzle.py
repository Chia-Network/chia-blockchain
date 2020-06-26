from clvm_tools import binutils
from src.types.program import Program
from typing import List


def create_core(genesis_coin_id: bytes) -> str:
    core = f"((c (q ((c 28 (c 2 (c 5 (c 11 (c 23 (c 47 (c ((c 47 95)) (q ())))))))))) (c (q ((53 (c 8 (c (sha256 (q 0x{genesis_coin_id.hex()}) ((c 22 (c 2 (c 5 (c 23 (q ())))))) 11) (q ()))) (c (i ((c 26 (c 2 (c 95 (q (())))))) (q (c ((c 18 (c 2 (c 11 (c 47 (c 23 (c 5 (q ())))))))) 95)) (q (x))) 1)) (((c (i (> 23 (q ())) (q ((c (i (l 5) (q (c (q 53) (c (sha256 (sha256 9 ((c 22 (c 2 (c 21 (c 47 (q ())))))) 45) ((c 22 (c 2 (c 11 (c 47 (q ())))))) 23) (q ())))) (q ((c 20 (c 2 (c 11 (c 23 (c 47 (q ()))))))))) 1))) (q (x))) 1)) (c (i 5 (q ((c (i (= 17 (q 51)) (q ((c (i (> 89 (q ())) (q ((c (i 11 (q (x)) (q ((c 26 (c 2 (c 13 (q (q)))))))) 1))) (q ((c 26 (c 2 (c 13 (c 11 (q ())))))))) 1))) (q ((c 26 (c 2 (c 13 (c 11 (q ())))))))) 1))) (q (q 1))) 1)) ((c 30 (c 2 (c (c (q 7) (c (c (q 5) (c (c (q 1) (c 5 (q ()))) (c (c (c (q 5) (c (c (q 1) (c (c (q 97) (c 11 (q ()))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ()))) (q ()))))) (c (i (l 5) (q ((c (i ((c (i ((c (i (l 9) (q (q ())) (q (q 1))) 1)) (q ((c (i (= 9 (q 97)) (q (q 1)) (q (q ()))) 1))) (q (q ()))) 1)) (q 21) (q (sha256 (q 2) ((c 30 (c 2 (c 9 (q ()))))) ((c 30 (c 2 (c 13 (q ())))))))) 1))) (q (sha256 (q 1) 5))) 1))) 1)))" # type: ignore # noqa
    return core


def create_innerpuz(pubkey: bytes, identities: List[bytes]) -> str:
    id_list = "("
    for id in identities:
        id_list = id_list + "0x" + id
    id_list = id_list + ")"
    innerpuz = f"((c (q ((c (i 5 (q ((c (i (= 5 (q 1)) (q (c (c 20 (c 95 (c 11 (q ())))) (c (c 20 (c ((c 30 (c 2 (q (()))))) (q (())))) (c ((c 18 (c 2 (c 23 (q ()))))) (c (c 24 (c 47 (q ()))) (q ())))))) (q ((c 28 (c 2 (c 22 (c 47 (c (c (c 20 (c 23 (c 11 (q ())))) (q ())) (c 23 (q ())))))))))) 1))) (q (c (c 20 (c 23 (c 11 (q ())))) (c ((c 18 (c 2 (c 23 (q ()))))) (q ()))))) 1))) (c (q (((57 . 52) 51 (c (i 5 (q ((c 28 (c 2 (c 13 (c 11 (c (c ((c 26 (c 2 (c 9 (c 11 (c 47 (q ()))))))) 23) (c 47 (q ()))))))))) (q 23)) 1)) ((c 16 (c (q 0x{pubkey.hex()}) (c 5 (q ())))) 5 24 (c (sha256 5 ((c 30 (c 2 (q (()))))) (q ())) (q ()))) {id_list} (c (i (l 5) (q (sha256 (q 2) ((c 30 (c 2 (c 9 (q ()))))) ((c 30 (c 2 (c 13 (q ()))))))) (q (sha256 (q 1) 5))) 1))) 1)))" # type: ignore # noqa
    return innerpuz


def create_fullpuz(innerpuzhash, core) -> str:
    puzstring = f"(r (c (q 0x{innerpuzhash}) ((c (q {core}) (a)))))"
    return puzstring


def create_eve_solution():

    return
