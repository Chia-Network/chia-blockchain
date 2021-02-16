from dataclasses import dataclass
from typing import Optional

from src.types.blockchain_format.vdf import VDFInfo, VDFProof
from src.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class SignagePoint(Streamable):
    cc_vdf: Optional[VDFInfo]
    cc_proof: Optional[VDFProof]
    rc_vdf: Optional[VDFInfo]
    rc_proof: Optional[VDFProof]
