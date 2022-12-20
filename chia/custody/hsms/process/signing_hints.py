from dataclasses import dataclass
from typing import Dict, List

from hsms.bls12_381 import BLSPublicKey, BLSSecretExponent
from hsms.util.clvm_serialization import (
    clvm_to_list_of_ints,
    clvm_to_list,
)


@dataclass
class SumHint:
    public_keys: List[BLSPublicKey]
    synthetic_offset: BLSSecretExponent

    def final_public_key(self) -> BLSPublicKey:
        return sum(self.public_keys, start=self.synthetic_offset.public_key())

    def as_program(self):
        return ([bytes(_) for _ in self.public_keys], bytes(self.synthetic_offset))

    @classmethod
    def from_program(cls, program) -> "SumHint":
        public_keys = clvm_to_list(
            program.pair[0], lambda x: BLSPublicKey.from_bytes(x.atom)
        )
        synthetic_offset = BLSSecretExponent.from_bytes(program.pair[1].atom)
        return cls(public_keys, synthetic_offset)


@dataclass
class PathHint:
    root_public_key: BLSPublicKey
    path: List[int]

    def public_key(self) -> BLSPublicKey:
        return self.root_public_key.child_for_path(self.path)

    def as_program(self):
        return (bytes(self.root_public_key), self.path)

    @classmethod
    def from_program(cls, program) -> "PathHint":
        root_public_key = BLSPublicKey.from_bytes(program.pair[0].atom)
        path = clvm_to_list_of_ints(program.pair[1])
        return cls(root_public_key, path)


SumHints = Dict[BLSPublicKey, SumHint]
PathHints = Dict[BLSPublicKey, PathHint]
