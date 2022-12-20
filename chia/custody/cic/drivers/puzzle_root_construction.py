import dataclasses
import itertools

from blspy import G1Element
from typing import Dict, List, Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk

from cic.drivers.drop_coins import construct_rekey_puzzle
from cic.drivers.filters import construct_payment_and_rekey_filter, construct_rekey_filter
from cic.drivers.merkle_utils import build_merkle_tree, simplify_merkle_proof
from cic.drivers.prefarm_info import PrefarmInfo
from cic.load_clvm import load_clvm

P2_NEW_LOCK_LEVEL = load_clvm("p2_new_lock_level.clsp", package_or_requirement="cic.clsp.drop_coins")

ProofType = List[Tuple[bytes32, Tuple[uint32, List[bytes32]]]]


@streamable
@dataclasses.dataclass(frozen=True)
class RootDerivation(Streamable):
    prefarm_info: PrefarmInfo
    pubkey_list: List[G1Element]
    required_pubkeys: uint32
    maximum_pubkeys: uint32
    minimum_pubkeys: uint32
    next_root: Optional[bytes32]
    filter_proofs: ProofType
    leaf_proofs: ProofType

    def get_proofs_of_inclusion(
        self,
        aggregate_pubkey: G1Element,
        lock: bool = False,
    ) -> Tuple[Dict[bytes32, Tuple[int, List[bytes32]]], Dict[bytes32, Tuple[int, List[bytes32]]]]:
        filter_proofs: Dict[bytes32, Tuple[int, List[bytes32]]] = {}
        leaf_proofs: Dict[bytes32, Tuple[int, List[bytes32]]] = {}
        for k, v in self.filter_proofs:
            filter_proofs[k] = v
        for k, v in self.leaf_proofs:
            leaf_proofs[k] = v
        if lock:
            assert self.next_root is not None
            puzzle_hash: bytes32 = construct_lock_puzzle(
                aggregate_pubkey,
                self.prefarm_info,
                self.next_root,
            ).get_tree_hash()
        else:
            puzzle_hash = puzzle_for_pk(aggregate_pubkey).get_tree_hash()

        if puzzle_hash not in leaf_proofs:
            raise ValueError("Could not find a puzzle matching the specified pubkey")

        leaf_proof: Tuple[int, List[bytes32]] = leaf_proofs[puzzle_hash]
        innermost_tree_root: bytes32 = simplify_merkle_proof(puzzle_hash, leaf_proof)

        # First, we're going to try to use the rnp filter
        filter_hash: bytes32 = construct_payment_and_rekey_filter(
            self.prefarm_info, innermost_tree_root, uint8(1)
        ).get_tree_hash()
        if filter_hash in filter_proofs:
            return {filter_hash: filter_proofs[filter_hash]}, {puzzle_hash: leaf_proof}

        # Then, we're going to try the lock filter
        filter_hash = construct_rekey_filter(self.prefarm_info, innermost_tree_root, uint8(0)).get_tree_hash()
        if filter_hash in filter_proofs:
            return {filter_hash: filter_proofs[filter_hash]}, {puzzle_hash: leaf_proof}

        # Then, we're going to try the rekey filters
        for i in range(self.minimum_pubkeys, self.required_pubkeys):
            filter_hash = construct_rekey_filter(
                self.prefarm_info,
                innermost_tree_root,
                uint8(1 + self.required_pubkeys - i),
            ).get_tree_hash()
            if filter_hash in filter_proofs:
                return {filter_hash: filter_proofs[filter_hash]}, {puzzle_hash: leaf_proof}

        raise ValueError("Could not find a valid filter for the calculated root")


def get_all_aggregate_pubkey_combinations(pubkey_list: List[G1Element], m: int) -> List[G1Element]:
    aggregated_pubkeys: List[G1Element] = []
    for subset in itertools.combinations(pubkey_list, m):
        aggregated_pubkey = G1Element()
        for pk in subset:
            aggregated_pubkey += pk
        aggregated_pubkeys.append(aggregated_pubkey)
    return aggregated_pubkeys


def construct_lock_puzzle(pubkey: G1Element, prefarm_info: PrefarmInfo, next_root: bytes32) -> Program:
    return P2_NEW_LOCK_LEVEL.curry(
        pubkey,
        construct_rekey_puzzle(prefarm_info).get_tree_hash(),
        next_root,
    )


def solve_lock_puzzle(old_puzzle_root: bytes32, singleton_inner: bytes32, singleton_amount: uint64) -> Program:
    return Program.to([old_puzzle_root, (singleton_inner, singleton_amount)])


def calculate_puzzle_root(
    prefarm_info: PrefarmInfo,
    pubkey_list: List[G1Element],
    required_pubkeys: uint32,
    maximum_pubkeys: uint32,
    minimum_pubkeys: uint32,
) -> RootDerivation:
    sorted_pubkey_list = [G1Element.from_bytes(b) for b in sorted([bytes(pk) for pk in pubkey_list])]
    assert minimum_pubkeys > 0 and maximum_pubkeys > 0 and required_pubkeys > 0
    if required_pubkeys < maximum_pubkeys:
        next_puzzle_root: Optional[bytes32] = calculate_puzzle_root(
            prefarm_info,
            sorted_pubkey_list,
            uint32(required_pubkeys + 1),
            maximum_pubkeys,
            minimum_pubkeys,
        ).prefarm_info.puzzle_root
    else:
        next_puzzle_root = None

    all_inner_proofs: Dict[bytes32, Tuple[int, List[bytes32]]] = {}
    all_filters: List[bytes32] = []

    # Construct the rekey and payments filter
    standard_pk_list: List[G1Element] = get_all_aggregate_pubkey_combinations(sorted_pubkey_list, required_pubkeys)
    all_standard_phs: List[bytes32] = [puzzle_for_pk(pk).get_tree_hash() for pk in standard_pk_list]
    rnp_root, rnp_proofs = build_merkle_tree(all_standard_phs)
    rnp_filter: bytes32 = construct_payment_and_rekey_filter(prefarm_info, rnp_root, uint8(1)).get_tree_hash()
    all_filters.append(rnp_filter)
    all_inner_proofs = all_inner_proofs | rnp_proofs

    # Construct the lock filter
    if next_puzzle_root is not None:
        next_pk_list: List[G1Element] = get_all_aggregate_pubkey_combinations(sorted_pubkey_list, required_pubkeys + 1)
        all_lock_phs: List[bytes32] = [
            construct_lock_puzzle(pk, prefarm_info, next_puzzle_root).get_tree_hash() for pk in next_pk_list
        ]
        lock_root, lock_proofs = build_merkle_tree(all_lock_phs)
        lock_filter: bytes32 = construct_rekey_filter(prefarm_info, lock_root, uint8(0)).get_tree_hash()
        all_filters.append(lock_filter)
        all_inner_proofs = all_inner_proofs | lock_proofs

    # Construct the remaining slower rekey filters
    for i in range(minimum_pubkeys, required_pubkeys):
        slow_pubkeys: List[G1Element] = get_all_aggregate_pubkey_combinations(sorted_pubkey_list, i)
        slow_phs: List[bytes32] = [puzzle_for_pk(pk).get_tree_hash() for pk in slow_pubkeys]
        slower_root, slower_proofs = build_merkle_tree(slow_phs)
        all_filters.append(
            construct_rekey_filter(
                prefarm_info,
                slower_root,
                uint8(1 + required_pubkeys - i),
            ).get_tree_hash()
        )
        all_inner_proofs = all_inner_proofs | slower_proofs

    filter_root, filter_proofs = build_merkle_tree(all_filters)
    return RootDerivation(
        dataclasses.replace(prefarm_info, puzzle_root=filter_root),
        sorted_pubkey_list,
        required_pubkeys,
        maximum_pubkeys,
        minimum_pubkeys,
        next_puzzle_root,
        list(filter_proofs.items()),  # type: ignore
        list(all_inner_proofs.items()),  # type: ignore
    )
