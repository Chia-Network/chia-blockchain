from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple, Type, Union

from blspy import G1Element
from typing_extensions import Protocol

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.wallet.puzzle_drivers import Solver
from chia.wallet.wallet_protocol import WalletProtocol


class WalletAction(Protocol):
    @staticmethod
    def name() -> str:
        ...

    @classmethod
    def from_solver(cls, solver: Solver) -> "WalletAction":
        ...

    def to_solver(self) -> Solver:
        ...

    def augment(self, environment: Solver) -> "WalletAction":
        ...

    def de_alias(self) -> "WalletAction":
        ...


class ActionAlias(Protocol):
    @staticmethod
    def name() -> str:
        ...

    @classmethod
    def from_solver(cls, solver: Solver) -> "ActionAlias":
        ...

    def to_solver(self) -> Solver:
        ...

    def de_alias(self) -> WalletAction:
        ...

    @staticmethod
    def action_name() -> str:
        ...

    @classmethod
    def from_action(cls, action: WalletAction) -> "ActionAlias":
        ...

    def augment(self, environment: Solver) -> WalletAction:
        ...


class OuterDriver(Protocol):
    # TODO: This is not great, we should move the coin selection logic in here
    @staticmethod
    def get_wallet_class() -> Type[WalletProtocol]:
        ...

    @staticmethod
    def type() -> bytes32:
        ...

    def get_actions(self) -> Dict[str, Type[WalletAction]]:
        ...

    def get_aliases(self) -> Dict[str, Type[ActionAlias]]:
        ...

    async def construct_outer_puzzle(self, inner_puzzle: Program) -> Program:
        ...

    async def construct_outer_solution(
        self,
        actions: List[WalletAction],
        inner_solution: Program,
        global_environment: Solver,
        local_environment: Solver,
        optimize: bool = False,
    ) -> Program:
        ...

    async def check_and_modify_actions(
        self,
        coin: Coin,
        outer_actions: List[WalletAction],
        inner_actions: List[WalletAction],
    ) -> Tuple[List[WalletAction], List[WalletAction]]:
        ...

    @classmethod
    async def match_puzzle(
        cls, puzzle: Program, mod: Program, curried_args: Program
    ) -> Optional[Tuple[PuzzleDescription, Program]]:
        ...

    @classmethod
    async def match_solution(cls, solution: Program) -> Optional[Tuple[SolutionDescription, Program]]:
        ...

    @staticmethod
    def get_asset_types(request: Solver) -> List[Solver]:
        ...

    @staticmethod
    async def match_asset_types(asset_types: List[Solver]) -> bool:
        ...

    def get_required_signatures(self, solution_description: SolutionDescription) -> List[Tuple[G1Element, bytes, bool]]:
        ...


class InnerDriver(Protocol):
    @staticmethod
    def type() -> bytes32:
        ...

    def get_actions(self) -> Dict[str, Type[WalletAction]]:
        ...

    def get_aliases(self) -> Dict[str, Type[ActionAlias]]:
        ...

    async def construct_inner_puzzle(self) -> Program:
        ...

    async def construct_inner_solution(
        self,
        actions: List[WalletAction],
        global_environment: Solver,
        local_environment: Solver,
        optimize: bool = False,
    ) -> Program:
        ...

    @classmethod
    async def match_puzzle(cls, puzzle: Program, mod: Program, curried_args: Program) -> Optional[PuzzleDescription]:
        ...

    @classmethod
    async def match_solution(cls, solution: Program) -> Optional[SolutionDescription]:
        ...

    def get_required_signatures(self, solution_description: SolutionDescription) -> List[Tuple[G1Element, bytes, bool]]:
        ...


@dataclass(frozen=True)
class PuzzleDescription:
    driver: Union[InnerDriver, OuterDriver]
    coin_description: Solver


@dataclass(frozen=True)
class SolutionDescription:
    actions: List[WalletAction]
    environment: Solver


@dataclass(frozen=True)
class SpendDescription:
    coin: Coin
    outer_puzzle_description: PuzzleDescription
    outer_solution_description: SolutionDescription
    inner_puzzle_description: PuzzleDescription
    inner_solution_description: SolutionDescription

    def get_all_actions(self, default_aliases: Dict[str, Type[ActionAlias]] = {}) -> List[WalletAction]:
        action_aliases: List[Type[ActionAlias]] = [
            *default_aliases.values(),
            *self.inner_puzzle_description.driver.get_aliases().values(),
            *self.outer_puzzle_description.driver.get_aliases().values(),
        ]

        action_to_potential_alias: Dict[str, List[Type[ActionAlias]]] = {}
        for alias in action_aliases:
            action_to_potential_alias.setdefault(alias.action_name(), [])
            action_to_potential_alias[alias.action_name()].append(alias)

        def alias_action(action: WalletAction) -> WalletAction:
            if action.name() in action_to_potential_alias:
                for potential_alias in action_to_potential_alias[action.name()]:
                    try:
                        alias: ActionAlias = potential_alias.from_action(action)
                        return alias
                    except Exception:
                        pass

            return action

        return list(
            map(alias_action, [*self.outer_solution_description.actions, *self.inner_solution_description.actions])
        )

    def get_all_signatures(self) -> List[Tuple[G1Element, bytes, bool]]:
        return [
            *self.outer_puzzle_description.driver.get_required_signatures(self.outer_solution_description),
            *self.inner_puzzle_description.driver.get_required_signatures(self.inner_solution_description),
        ]

    def get_full_description(self) -> Solver:
        return Solver(
            {
                "coin_id": "0x" + self.coin.name().hex(),
                "parent_coin_info": "0x" + self.coin.parent_coin_info.hex(),
                "puzzle_hash": "0x" + self.coin.puzzle_hash.hex(),
                "amount": str(self.coin.amount),
                **self.inner_puzzle_description.coin_description.info,
                **self.outer_puzzle_description.coin_description.info,
            }
        )

    def get_full_environment(self) -> Solver:
        return Solver(
            {**self.inner_solution_description.environment.info, **self.outer_solution_description.environment.info}
        )

    async def apply_actions(
        self,
        actions: List[Solver],
        default_aliases: Dict[str, Type[ActionAlias]] = {},
        environment: Solver = Solver({}),
    ) -> Tuple[List[Solver], SpendDescription]:
        # Get a list of the actions that each wallet supports
        supported_outer_actions: Dict[str, Type[WalletAction]] = self.outer_puzzle_description.driver.get_actions()
        supported_inner_actions: Dict[str, Type[WalletAction]] = self.inner_puzzle_description.driver.get_actions()

        action_aliases = {
            **default_aliases,
            **self.inner_puzzle_description.driver.get_aliases(),
            **self.outer_puzzle_description.driver.get_aliases(),
        }

        # Apply any actions that the coin supports
        actions_left: List[Solver] = []
        outer_actions: List[WalletAction] = []
        inner_actions: List[WalletAction] = []
        # I'm not sure why pylint fails to recognize supported_*_actions as dicts (maybe not familiar w/ protocols?)
        # pylint: disable=unsupported-membership-test,unsubscriptable-object
        for action in actions:
            if action["type"] in action_aliases:
                alias = action_aliases[action["type"]].from_solver(action)
                action = alias.de_alias().to_solver()
            if action["type"] in supported_outer_actions:
                outer_actions.append(supported_outer_actions[action["type"]].from_solver(action))
            elif action["type"] in supported_inner_actions:
                inner_actions.append(supported_inner_actions[action["type"]].from_solver(action))
            else:
                actions_left.append(action)

        # Let the outer wallet potentially modify the actions (for example, adding hints to payments)
        # In python 3.8+ we can use `@runtime_checkable` on the driver protocols
        (
            new_outer_actions,
            new_inner_actions,
        ) = await self.outer_puzzle_description.driver.check_and_modify_actions(  # type: ignore
            self.coin, outer_actions, inner_actions
        )

        # Double check that the new inner actions are still okay with the inner wallet
        for inner_action in new_inner_actions:
            if inner_action.name() not in supported_inner_actions:
                # If they're not, abort and don't do anything
                actions_left = actions
                new_outer_actions = []
                new_inner_actions = []
                break
        # pylint: enable=unsupported-membership-test,unsubscriptable-object

        # Create the inner puzzle and solution first
        inner_solution: Program = await self.inner_puzzle_description.driver.construct_inner_solution(  # type: ignore
            new_inner_actions,
            global_environment=environment,
            local_environment=self.inner_solution_description.environment,
            optimize=False,
        )

        # Then feed those to the outer wallet
        outer_solution: Program = await self.outer_puzzle_description.driver.construct_outer_solution(  # type: ignore
            new_outer_actions,
            inner_solution,
            global_environment=environment,
            local_environment=self.outer_solution_description.environment,
            optimize=False,
        )

        outer_solution_match: Optional[
            Tuple[SolutionDescription, Program]
        ] = await self.outer_puzzle_description.driver.match_solution(outer_solution)
        if outer_solution_match is None:
            raise ValueError("Outer Wallet generated a solution it couldn't match itself")
        new_outer_solution_description, _ = outer_solution_match

        new_inner_solution_description: Optional[
            SolutionDescription
        ] = await self.inner_puzzle_description.driver.match_solution(inner_solution)
        if new_inner_solution_description is None:
            raise ValueError("Inner Wallet generated a solution it couldn't match itself")

        return (
            actions_left,
            replace(
                self,
                outer_solution_description=new_outer_solution_description,
                inner_solution_description=new_inner_solution_description,
            ),
        )

    async def spend(self, environment: Solver = Solver({}), optimize: bool = False) -> CoinSpend:
        # In python 3.8+ we can use `@runtime_checkable` on the driver protocols
        # Create the inner puzzle and solution first
        inner_puzzle: Program = await self.inner_puzzle_description.driver.construct_inner_puzzle()  # type: ignore
        inner_solution: Program = await self.inner_puzzle_description.driver.construct_inner_solution(  # type: ignore
            self.inner_solution_description.actions,
            global_environment=environment,
            local_environment=self.inner_solution_description.environment,
            optimize=optimize,
        )

        # Then feed those to the outer wallet
        outer_puzzle: Program = await self.outer_puzzle_description.driver.construct_outer_puzzle(inner_puzzle)  # type: ignore  # noqa
        outer_solution: Program = await self.outer_puzzle_description.driver.construct_outer_solution(  # type: ignore
            self.outer_solution_description.actions,
            inner_solution,
            global_environment=environment,
            local_environment=self.outer_solution_description.environment,
            optimize=optimize,
        )

        return CoinSpend(self.coin, outer_puzzle, outer_solution)
