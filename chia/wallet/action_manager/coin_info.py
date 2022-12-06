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
    PuzzleSolutionDescription,
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
            description.outer_description.driver,
            description.inner_description.driver,
        )

    def alias_actions(
        self, actions: List[WalletAction], default_aliases: Dict[str, ActionAlias] = {}
    ) -> List[WalletAction]:
        action_aliases = [
            *default_aliases.values(),
            *self.inner_driver.get_aliases().values(),
            *self.outer_driver.get_aliases().values(),
        ]

        action_to_potential_alias: Dict[str, ActionAlias] = {}
        for alias in action_aliases:
            action_to_potential_alias.setdefault(alias.action_name(), [])
            action_to_potential_alias[alias.action_name()].append(alias)

        def alias_action(action: WalletAction) -> WalletAction:
            if action.name() in action_to_potential_alias:
                for alias in action_to_potential_alias[action.name()]:
                    try:
                        return alias.from_action(action)
                    except Exception:
                        pass

            return action

        return list(map(alias_action, actions))

    async def create_spend_for_actions(
        self,
        actions: List[Solver],
        default_aliases: Dict[str, ActionAlias] = {},
        environment: Solver = Solver({}),
        optimize: bool = False,
    ) -> Tuple[List[Solver], Solver, CoinSpend, SpendDescription]:
        # Get a list of the actions that each wallet supports
        supported_outer_actions = self.outer_driver.get_actions()
        supported_inner_actions = self.inner_driver.get_actions()

        action_aliases = {
            **default_aliases,
            **self.inner_driver.get_aliases(),
            **self.outer_driver.get_aliases(),
        }

        # Apply any actions that the coin supports
        actions_left: List[Solver] = []
        outer_actions: List[WalletAction] = []
        inner_actions: List[WalletAction] = []
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

        outer_match: Optional[Tuple[PuzzleSolutionDescription, Program, Program]] = await self.outer_driver.match_spend(
            spend, *outer_puzzle.uncurry()
        )
        assert outer_match is not None
        outer_description: PuzzleSolutionDescription = outer_match[0]
        inner_description: PuzzleSolutionDescription = await self.inner_driver.match_inner_puzzle_and_solution(
            self.coin, inner_puzzle, inner_solution, *inner_puzzle.uncurry()
        )

        return (
            actions_left,
            Solver({**environment.info, **environment_addition.info}),
            spend,
            SpendDescription(self.coin, outer_description, inner_description),
        )
