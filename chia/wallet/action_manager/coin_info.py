from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Type, TypeVar

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpend
from chia.wallet.action_manager.protocols import (
    ActionAlias,
    InnerDriver,
    OuterDriver,
    PuzzleDescription,
    SolutionDescription,
    SpendDescription,
    WalletAction,
)
from chia.wallet.puzzle_drivers import Solver

_T_CoinInfo = TypeVar("_T_CoinInfo", bound="CoinInfo")


@dataclass(frozen=True)
class CoinInfo:
    coin: Coin
    _description: Solver
    outer_driver: OuterDriver
    inner_driver: InnerDriver

    @property
    def description(self) -> Solver:
        return Solver(
            {
                "coin_id": "0x" + self.coin.name().hex(),
                "parent_coin_info": "0x" + self.coin.parent_coin_info.hex(),
                "puzzle_hash": "0x" + self.coin.puzzle_hash.hex(),
                "amount": str(self.coin.amount),
                **self._description.info,
            }
        )

    @classmethod
    def from_spend_description(cls: Type[_T_CoinInfo], description: SpendDescription) -> _T_CoinInfo:
        return cls(
            description.coin,
            description.get_full_description(),
            # In python 3.8+ we can use `@runtime_checkable` on the driver protocols
            description.outer_puzzle_description.driver,  # type: ignore
            description.inner_puzzle_description.driver,  # type: ignore
        )

    def alias_actions(
        self, actions: List[WalletAction], default_aliases: Dict[str, Type[ActionAlias]] = {}
    ) -> List[WalletAction]:
        action_aliases: List[Type[ActionAlias]] = [
            *default_aliases.values(),
            *self.inner_driver.get_aliases().values(),
            *self.outer_driver.get_aliases().values(),
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

        return list(map(alias_action, actions))

    async def create_spend_for_actions(
        self,
        actions: List[Solver],
        default_aliases: Dict[str, Type[ActionAlias]] = {},
        environment: Solver = Solver({}),
        optimize: bool = False,
    ) -> Tuple[List[Solver], Solver, CoinSpend, SpendDescription]:
        # Get a list of the actions that each wallet supports
        supported_outer_actions: Dict[str, Type[WalletAction]] = self.outer_driver.get_actions()
        supported_inner_actions: Dict[str, Type[WalletAction]] = self.inner_driver.get_actions()

        action_aliases = {
            **default_aliases,
            **self.inner_driver.get_aliases(),
            **self.outer_driver.get_aliases(),
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
        new_outer_actions, new_inner_actions, environment_addition = await self.outer_driver.check_and_modify_actions(
            self.coin, outer_actions, inner_actions, environment
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
        inner_puzzle: Program = await self.inner_driver.construct_inner_puzzle()
        inner_solution: Program = await self.inner_driver.construct_inner_solution(
            new_inner_actions, environment, optimize=optimize
        )

        # Then feed those to the outer wallet
        outer_puzzle: Program = await self.outer_driver.construct_outer_puzzle(inner_puzzle)
        outer_solution: Program = await self.outer_driver.construct_outer_solution(
            new_outer_actions, inner_solution, environment, optimize=optimize
        )

        spend = CoinSpend(self.coin, outer_puzzle, outer_solution)

        outer_puzzle_match: Optional[Tuple[PuzzleDescription, Program]] = await self.outer_driver.match_puzzle(
            outer_puzzle, *outer_puzzle.uncurry()
        )
        assert outer_puzzle_match is not None
        outer_solution_match: Optional[Tuple[SolutionDescription, Program]] = await self.outer_driver.match_solution(
            outer_solution
        )
        assert outer_solution_match is not None
        outer_puzzle_description, _ = outer_puzzle_match
        outer_solution_description, _ = outer_solution_match
        inner_puzzle_match: Optional[Tuple[PuzzleDescription, Program]] = await self.inner_driver.match_puzzle(
            inner_puzzle, *inner_puzzle.uncurry()
        )
        assert inner_puzzle_match is not None
        inner_solution_match: Optional[Tuple[SolutionDescription, Program]] = await self.inner_driver.match_solution(
            inner_solution
        )
        assert inner_solution_match is not None
        inner_puzzle_description = inner_puzzle_match
        inner_solution_description = inner_solution_match

        return (
            actions_left,
            Solver({**environment.info, **environment_addition.info}),
            spend,
            SpendDescription(
                self.coin,
                outer_puzzle_description,
                outer_solution_description,
                inner_puzzle_description,
                inner_solution_description,
            ),
        )
