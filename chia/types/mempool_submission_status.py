from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Union

from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.ints import uint8
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class MempoolSubmissionStatus(Streamable):
    """
    :sent_to: in `TradeRecord` and `TransactionRecord` are a
    Tuple of (peer_id: str, status: MempoolInclusionStatus, error: Optional[str])
    MempoolInclusionStatus is represented as a uint8 in those structs so they can be `Streamable`
    """

    peer_id: str
    inclusion_status: uint8  # MempoolInclusionStatus
    error_msg: Optional[str]

    def to_json_dict_convenience(self) -> Dict[str, Union[str, MempoolInclusionStatus, Optional[str]]]:
        formatted = self.to_json_dict()
        formatted["inclusion_status"] = MempoolInclusionStatus(self.inclusion_status).name
        return formatted

    def __str__(self) -> str:
        return f"{self.to_json_dict_convenience()}"
