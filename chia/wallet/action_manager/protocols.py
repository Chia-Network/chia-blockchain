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
        """
        A simple method that returns a unique string for this action (for use in dictionaries and such)
        """
        ...

    @classmethod
    def from_solver(cls, solver: Solver) -> "WalletAction":
        """
        Parse a clvm dictionary specifying this type of action and return an instance of this class
        """
        ...

    def to_solver(self) -> Solver:
        """
        Return a clvm dictionary representation of this instance
        """
        ...

    def augment(self, environment: Solver) -> "WalletAction":
        """
        Given an environment, return a new action
        """
        ...

    def de_alias(self) -> "WalletAction":
        """
        Return a more base representation of this action if one exists

        For example, if this action is a DirectPayment, a more base action is a Condition
        """
        ...

class ActionAlias(WalletAction, Protocol):
    @staticmethod
    def action_name() -> str:
        """
        Return the name of the action to which this action de_aliases
        """
        ...

    @classmethod
    def from_action(cls, action: WalletAction) -> "ActionAlias":
        """
        Given another type of action, return an instance of this action that aliases it
        """
        ...


class OuterDriver(Protocol):
    # TODO: This is not great, we should move the coin selection logic in here somehow
    @staticmethod
    def get_wallet_class() -> Type[WalletProtocol]:
        ...

    def get_actions(self) -> Dict[str, Type[WalletAction]]:
        """
        Return a {name: WalletAction} mapping of the actions that this driver should be responsible for supporting

        For example, the standard wallet can handle both "condition" and "graftroot" type actions
        """
        ...

    def get_aliases(self) -> Dict[str, Type[ActionAlias]]:
        """
        Return a {name: ActionAlias} mapping of the action aliases that this driver should be responsible for supporting

        For example, NFTs might be responsible for "update_metadata" actions or CATs might be responsible for "run_tail"
        """
        ...

    async def construct_outer_puzzle(self, inner_puzzle: Program) -> Program:
        """
        Given an inner puzzle, construct the full puzzle reveal

        The driver should already have all of the information it needs to do a puzzle reveal
        """
        ...

    async def construct_outer_solution(
        self,
        actions: List[WalletAction],
        inner_solution: Program,
        global_environment: Solver,
        local_environment: Solver,
        optimize: bool = False,
    ) -> Program:
        """
        Given an inner solution and an environment, return the full solution

        There are two layers of environment:
          - A "global" environment that represents the nature of the spend bundle and all of the coins being spent
            with the coin this function is being asked to spend
          - A "local" environment that contains arguments specific to this coin which are not accessible by other spends

        By default, the solution should be constructed with enough information to parse the environments from it later.
        If optimize == True, then construct the solution as if it's going immediately to the blockchain.
        """
        ...

    async def check_and_modify_actions(
        self,
        outer_actions: List[WalletAction],
        inner_actions: List[WalletAction],
    ) -> Tuple[List[WalletAction], List[WalletAction]]:
        """
        Given the actions to use, return some actions to use instead.

        The outer puzzle has complete control over the inner puzzle so it can modify both sets of actions. This is a
        good place to turn things like actions that require magic conditions to come from the inner puzzle into
        Condition actions.
        """
        ...

    @classmethod
    async def match_puzzle(
        cls, puzzle: Program, mod: Program, curried_args: Program
    ) -> Optional[Tuple[PuzzleDescription, Program]]:
        """
        Given a puzzle (and its uncurried representation for optimization purposes), return a description of the puzzle
        including an instance of this driver and a clvm dictionary describing the coin's features.

        Also return the inner puzzle.
        """
        ...

    @classmethod
    async def match_solution(cls, solution: Program) -> Optional[Tuple[SolutionDescription, Program]]:
        """
        Given a solution, return a description of the solution including what actions are being performed as well as
        the local environment necessary to solve the coin.

        Also return the inner solution
        """
        ...

    @staticmethod
    def get_asset_types(request: Solver) -> List[Solver]:
        """
        Given a clvm dictionary describing a puzzle, return a list of asset types for it
        (see chia/wallet/puzzles/add_wrapped_announcement.clsp for a description of asset types)
        """
        ...

    @staticmethod
    async def match_asset_types(asset_types: List[Solver]) -> bool:
        """
        Given a list of asset types, return whether or not this driver represents those asset types
        (see chia/wallet/puzzles/add_wrapped_announcement.clsp for a description of asset types)
        """
        ...

    def get_required_signatures(self, solution_description: SolutionDescription) -> List[Tuple[G1Element, bytes, bool]]:
        """
        Given a description of a solution, return what signatures will be required to be present in the aggregate
        """
        ...


class InnerDriver(Protocol):
    def get_actions(self) -> Dict[str, Type[WalletAction]]:
        """
        Return a {name: WalletAction} mapping of the actions that this driver should be responsible for supporting

        For example, the standard wallet can handle both "condition" and "graftroot" type actions
        """
        ...

    def get_aliases(self) -> Dict[str, Type[ActionAlias]]:
        """
        Return a {name: ActionAlias} mapping of the action aliases that this driver should be responsible for supporting

        For example, NFTs might be responsible for "update_metadata" actions or CATs might be responsible for "run_tail"
        """
        ...

    async def construct_inner_puzzle(self) -> Program:
        """
        Construct the full puzzle reveal

        The driver should already have all of the information it needs to do a puzzle reveal
        """
        ...

    async def construct_inner_solution(
        self,
        actions: List[WalletAction],
        global_environment: Solver,
        local_environment: Solver,
        optimize: bool = False,
    ) -> Program:
        """
        Given an environment, return the full solution

        There are two layers of environment:
          - A "global" environment that represents the nature of the spend bundle and all of the coins being spent
            with the coin this function is being asked to spend
          - A "local" environment that contains arguments specific to this coin which are not accessible by other spends

        By default, the solution should be constructed with enough information to parse the environments from it later.
        If optimize == True, then construct the solution as if it's going immediately to the blockchain.
        """
        ...

    @classmethod
    async def match_puzzle(cls, puzzle: Program, mod: Program, curried_args: Program) -> Optional[PuzzleDescription]:
        """
        Given a puzzle (and its uncurried representation for optimization purposes), return a description of the puzzle
        including an instance of this driver and a clvm dictionary describing the coin's features.
        """
        ...

    @classmethod
    async def match_solution(cls, solution: Program) -> Optional[SolutionDescription]:
        """
        Given a solution, return a description of the solution including what actions are being performed as well as
        the local environment necessary to solve the coin.
        """
        ...

    def get_required_signatures(self, solution_description: SolutionDescription) -> List[Tuple[G1Element, bytes, bool]]:
        """
        Given a description of a solution, return what signatures will be required to be present in the aggregate
        """
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
    """
    A SpendDescription should contain enough information to create a coin spend. The individual parts of it are more
    accessible that they would be in a coin spend to prevent lots of duplicate code parsing the same information.
    """
    coin: Coin
    outer_puzzle_description: PuzzleDescription
    outer_solution_description: SolutionDescription
    inner_puzzle_description: PuzzleDescription
    inner_solution_description: SolutionDescription

    def get_all_actions(self, default_aliases: Dict[str, Type[ActionAlias]] = {}) -> List[WalletAction]:
        """
        Return both outer/inner actions, aliased if possible
        """
        action_aliases: List[Type[ActionAlias]] = [
            *default_aliases.values(),
            *self.inner_puzzle_description.driver.get_aliases().values(),
            *self.outer_puzzle_description.driver.get_aliases().values(),
        ]

        # Build a dictionary of actions mapping to the aliases that may be able to parse them
        action_to_potential_alias: Dict[str, List[Type[ActionAlias]]] = {}
        for alias in action_aliases:
            action_to_potential_alias.setdefault(alias.action_name(), [])
            action_to_potential_alias[alias.action_name()].append(alias)

        def alias_action(action: WalletAction) -> WalletAction:
            if action.name() in action_to_potential_alias:
                for potential_alias in action_to_potential_alias[action.name()]:
                    try:
                        # Try to parse the action using each alias
                        alias: ActionAlias = potential_alias.from_action(action)
                        return alias
                    except Exception:
                        # On failure, just keep trying until we run out
                        # TODO: catching all exceptions here is not fantastic,
                        # maybe a specific exception from the aliases to signal failure to parse would be good?
                        pass

            return action

        return list(
            map(alias_action, [*self.outer_solution_description.actions, *self.inner_solution_description.actions])
        )

    def get_all_signatures(self) -> List[Tuple[G1Element, bytes, bool]]:
        """
        Return all signatures requirements for this coin spend
        """
        return [
            *self.outer_puzzle_description.driver.get_required_signatures(self.outer_solution_description),
            *self.inner_puzzle_description.driver.get_required_signatures(self.inner_solution_description),
        ]

    def get_full_description(self) -> Solver:
        """
        Return a user-friendly clvm dictionary describing the coin and its composite puzzles
        """
        return Solver(
            {
                "coin_id": "0x" + self.coin.name().hex(),
                "parent_coin_info": "0x" + self.coin.parent_coin_info.hex(),
                "puzzle_hash": "0x" + self.coin.puzzle_hash.hex(),
                "amount": str(self.coin.amount),
                **self.inner_puzzle_description.coin_description.info,
                # outer puzzle descriptors take priority over inner puzzle descriptors
                **self.outer_puzzle_description.coin_description.info,
            }
        )

    async def apply_actions(
        self,
        actions: List[Solver],
        default_aliases: Dict[str, Type[ActionAlias]] = {},
        environment: Solver = Solver({}),
    ) -> Tuple[List[Solver], SpendDescription]:
        """
        Given a list of actions and a global environment, return all actions that could not be applied as well as a new
        SpendDescription instance containing the applied actions
        """
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
            outer_actions, inner_actions
        )

        # Double check that the new inner actions are still okay with the inner wallet
        for inner_action in new_inner_actions:
            if inner_action.name() not in supported_inner_actions:
                # If they're not, don't attempt any actions, something funky is going on
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

        # Now we're going to match the newly generated solutions to get new solution descriptions
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
        """
        Digest the existing SpendDescription into a CoinSpend in the specified global environment
        """
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
