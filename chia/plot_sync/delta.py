from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Union

from chia.protocols.harvester_protocol import Plot


@dataclass
class DeltaType:
    additions: Union[Dict[str, Plot], List[str]]
    removals: List[str]

    def __str__(self) -> str:
        return f"+{len(self.additions)}/-{len(self.removals)}"

    def clear(self) -> None:
        self.additions.clear()
        self.removals.clear()

    def empty(self) -> bool:
        return len(self.additions) == 0 and len(self.removals) == 0


@dataclass
class PlotListDelta(DeltaType):
    additions: Dict[str, Plot] = field(default_factory=dict)
    removals: List[str] = field(default_factory=list)


@dataclass
class PathListDelta(DeltaType):
    additions: List[str] = field(default_factory=list)
    removals: List[str] = field(default_factory=list)

    @staticmethod
    def from_lists(old: List[str], new: List[str]) -> PathListDelta:
        return PathListDelta([x for x in new if x not in old], [x for x in old if x not in new])


@dataclass
class Delta:
    valid: PlotListDelta = field(default_factory=PlotListDelta)
    invalid: PathListDelta = field(default_factory=PathListDelta)
    keys_missing: PathListDelta = field(default_factory=PathListDelta)
    duplicates: PathListDelta = field(default_factory=PathListDelta)

    def empty(self) -> bool:
        return self.valid.empty() and self.invalid.empty() and self.keys_missing.empty() and self.duplicates.empty()

    def __str__(self) -> str:
        return (
            f"[valid {self.valid}, invalid {self.invalid}, keys missing: {self.keys_missing}, "
            f"duplicates: {self.duplicates}]"
        )

    def clear(self) -> None:
        self.valid.clear()
        self.invalid.clear()
        self.keys_missing.clear()
        self.duplicates.clear()
