from dataclasses import dataclass
from typing import List

import blspy

from src.types.sized_bytes import bytes48, bytes96, bytes32
from src.util.streamable import Streamable, streamable

ZERO96 = bytes96([0] * 96)


class BLSPublicKey(bytes48):
    pass


# TODO Stop using this after BLSLibrary is updated
@dataclass(frozen=True)
@streamable
class BLSSignature(Streamable):
    """
    This wraps the blspy.BLSPublicKey and resolves a couple edge cases around aggregation and validation.
    """

    @dataclass(frozen=True)
    @streamable
    class PkMessagePair(Streamable):
        public_key: BLSPublicKey
        message_hash: bytes32

    sig: bytes96

    @classmethod
    def aggregate(cls, sigs):
        sigs = [_ for _ in sigs if _.sig != ZERO96]
        if len(sigs) == 0:
            sig = ZERO96
        else:
            wrapped_sigs = [blspy.PrependSignature.from_bytes(_.sig) for _ in sigs]
            sig = bytes(blspy.PrependSignature.aggregate(wrapped_sigs))
        return cls(sig)

    def validate(self, hash_key_pairs: List[PkMessagePair]) -> bool:
        # check for special case of 0
        if len(hash_key_pairs) == 0:
            return True
        message_hashes = [_.message_hash for _ in hash_key_pairs]
        public_keys = [blspy.PublicKey.from_bytes(_.public_key) for _ in hash_key_pairs]
        try:
            # when the signature is invalid, this method chokes
            signature = blspy.PrependSignature.from_bytes(self.sig)
            return signature.verify(message_hashes, public_keys)
        except Exception:
            return False
