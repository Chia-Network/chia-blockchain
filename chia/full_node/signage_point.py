from dataclasses import dataclass
from typing import Optional

from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class SignagePoint(Streamable):
    cc_vdf: Optional[VDFInfo]
    cc_proof: Optional[VDFProof]
    rc_vdf: Optional[VDFInfo]
    rc_proof: Optional[VDFProof]
