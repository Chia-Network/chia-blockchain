import zlib

from dataclasses import dataclass
from typing import List

from hsms.bls12_381 import BLSPublicKey, BLSSignature
from hsms.process.signing_hints import SumHint, PathHint
from hsms.streamables import bytes32, CoinSpend, Program
from hsms.util.byte_chunks import assemble_chunks, create_chunks_for_blob
from hsms.util.clvm_serialization import (
    transform_dict,
    transform_dict_by_key,
    clvm_to_list,
)


@dataclass
class SignatureInfo:
    signature: BLSSignature
    partial_public_key: BLSPublicKey
    final_public_key: BLSPublicKey
    message: bytes


@dataclass
class UnsignedSpend:
    coin_spends: List[CoinSpend]
    sum_hints: List[SumHint]
    path_hints: List[PathHint]
    agg_sig_me_network_suffix: bytes32

    def as_program(self):
        as_clvm = [("a", self.agg_sig_me_network_suffix)]
        cs_as_clvm = [
            [_.coin.parent_coin_info, _.puzzle_reveal, _.coin.amount, _.solution]
            for _ in self.coin_spends
        ]
        as_clvm.append(("c", cs_as_clvm))
        sh_as_clvm = [_.as_program() for _ in self.sum_hints]
        as_clvm.append(("s", sh_as_clvm))
        ph_as_clvm = [_.as_program() for _ in self.path_hints]
        as_clvm.append(("p", ph_as_clvm))
        self_as_program = Program.to(as_clvm)
        return self_as_program

    @classmethod
    def from_program(cls, program) -> "UnsignedSpend":
        d = transform_dict(program, transform_dict_by_key(UNSIGNED_SPEND_TRANSFORMER))
        return cls(d["c"], d.get("s", []), d.get("p", []), d["a"])

    def __bytes__(self):
        return bytes(self.as_program())

    @classmethod
    def from_bytes(cls, blob) -> "UnsignedSpend":
        return cls.from_program(Program.from_bytes(blob))

    def chunk(self, bytes_per_chunk: int) -> List[bytes]:
        bundle_bytes = zlib.compress(bytes(self), level=9)
        return create_chunks_for_blob(bundle_bytes, bytes_per_chunk)

    @classmethod
    def from_chunks(cls, chunks: List[bytes]) -> "UnsignedSpend":
        return UnsignedSpend.from_bytes(zlib.decompress(assemble_chunks(chunks)))


UNSIGNED_SPEND_TRANSFORMER = {
    "c": lambda x: clvm_to_list(x, CoinSpend.from_program),
    "s": lambda x: clvm_to_list(x, SumHint.from_program),
    "p": lambda x: clvm_to_list(x, PathHint.from_program),
    "a": lambda x: x.atom,
}
