from __future__ import annotations

from dataclasses import dataclass

from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SignagePoint(Streamable):
    cc_vdf: VDFInfo | None
    cc_proof: VDFProof | None
    rc_vdf: VDFInfo | None
    rc_proof: VDFProof | None
