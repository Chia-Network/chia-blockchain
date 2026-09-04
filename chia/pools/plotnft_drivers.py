from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, cast

from chia_rs import G1Element
from chia_rs.chia_rs import Coin, CoinSpend
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from typing_extensions import Self

from chia.types.blockchain_format.program import Program, run
from chia.types.coin_spend import make_spend
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    AssertHeightRelative,
    Condition,
    CreateCoin,
    CreateCoinAnnouncement,
    Remark,
    parse_conditions_non_consensus,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.custody.custody_architecture import (
    MofN,
    ProvenSpend,
    PuzzleWithRestrictions,
)
from chia.wallet.puzzles.custody.member_puzzles import (
    BLSWithTaprootMember,
    FixedPuzzleMember,
)
from chia.wallet.puzzles.custody.restriction_utilities import ValidatorStackRestriction
from chia.wallet.puzzles.custody.restrictions import FixedCreateCoinDestinations, Heightlock, SendMessageBanned
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.puzzle_drivers import (
    DelegatedPuzzleAndSolution,
    InnerPuzzle,
    NilSolution,
    P2Conditions,
    PuzzleWithPuzzleHash,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.puzzles.singleton_drivers import (
    P2Singleton,
    P2SingletonPuzzle,
    Singleton,
    SingletonLaunchInfo,
    SingletonLaunchResult,
    SingletonPuzzle,
    SingletonSolution,
    SingletonStruct,
)
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle

CLAIM_POOL_REWARDS_DELEGATED_PUZZLE = load_clvm_maybe_recompile(
    "claim_pool_rewards_dpuz.clsp", package_or_requirement="chia.pools"
)
FORWARD_TO_POOL_PUZZLE_HASH_DELEGATED_PUZZLE = load_clvm_maybe_recompile(
    "forward_to_pool_puzzle_hash_dpuz.clsp", package_or_requirement="chia.pools"
)


def forward_to_pool_puzzle_hash_dpuz(pool_puzzle_hash: bytes32, pool_memoization: Program) -> Program:
    return FORWARD_TO_POOL_PUZZLE_HASH_DELEGATED_PUZZLE.curry(pool_puzzle_hash, pool_memoization)


@dataclass(kw_only=True, frozen=True)
class PoolConfig:
    pool_puzzle_hash: bytes32
    heightlock: uint32
    pool_memoization: Program


@dataclass(kw_only=True, frozen=True)
class UserConfig:
    synthetic_pubkey: G1Element


@dataclass(kw_only=True, frozen=True)
class PlotNFTInnerPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[InnerPuzzle] = cast("PlotNFTInnerPuzzle", None)

    user_config: UserConfig
    exiting: bool | None = None
    self_launcher_id: bytes32 | None = None
    genesis_challenge: bytes32 | None = None
    pool_config: PoolConfig | None = None
    struct_driver: ClassVar[type[SingletonStruct]] = SingletonStruct

    def __post_init__(self) -> None:
        if self.pool_config is not None and (
            self.self_launcher_id is None or self.genesis_challenge is None or self.exiting is None
        ):
            raise ValueError("Trying to initialize a pooling PlotNFT without required information")
        if self.pool_config is None and self.exiting:
            raise ValueError("Cannot initialize a PlotNFTPuzzle with an empty pool config and exiting=True")

    @property
    def launcher_id(self) -> bytes32:
        if self.self_launcher_id is None:
            raise ValueError("Launcher ID is not present because PlotNFT is not pooling")
        return self.self_launcher_id

    @property
    def singleton_struct(self) -> SingletonStruct:
        return self.struct_driver(launcher_id=self.launcher_id)

    @property
    def pooling(self) -> bool:
        return self.pool_config is not None

    @property
    def guaranteed_pool_config(self) -> PoolConfig:
        if self.pool_config is None:
            raise ValueError("Plot NFT is not pooling, cannot retrieve pool config")
        return self.pool_config

    @property
    def bls_member(self) -> BLSWithTaprootMember:
        return BLSWithTaprootMember(synthetic_key=self.user_config.synthetic_pubkey)

    @cached_property
    def forward_pool_reward_dpuz(self) -> Program:
        return forward_to_pool_puzzle_hash_dpuz(
            self.guaranteed_pool_config.pool_puzzle_hash, self.guaranteed_pool_config.pool_memoization
        )

    @property
    def waiting_room_puzzle(self) -> Self:
        return dataclasses.replace(self, exiting=True)

    @cached_property
    def claim_pool_reward_dpuz(self) -> Program:
        assert self.genesis_challenge is not None
        return CLAIM_POOL_REWARDS_DELEGATED_PUZZLE.curry(
            self.genesis_challenge[:16],
            self.struct_driver.singleton_puzzles.singleton_mod_hash,
            self.singleton_struct.struct_hash,
            P2SingletonPuzzle(singleton_id=self.launcher_id).puzzle_hash,
            self.forward_pool_reward_dpuz.get_tree_hash(),
        )

    def claim_pool_reward_dpuz_and_solution(self, reward: PoolReward) -> DelegatedPuzzleAndSolution:
        return DelegatedPuzzleAndSolution(
            puzzle=UnknownPuzzle(known_puzzle=self.claim_pool_reward_dpuz),
            solution=UnknownSolution(Program.to([self.puzzle_hash, reward.height, reward.coin.amount])),
        )

    @property
    def user_restriction(self) -> ValidatorStackRestriction:
        return ValidatorStackRestriction(
            required_wrappers=[
                FixedCreateCoinDestinations(allowed_ph=self.waiting_room_puzzle.puzzle_hash),
                SendMessageBanned(),
            ]
            if not self.exiting
            else [Heightlock(heightlock=self.guaranteed_pool_config.heightlock), SendMessageBanned()]
        )

    def modify_delegated_puzzle_and_solution(
        self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution
    ) -> DelegatedPuzzleAndSolution:
        return self.user_restriction.modify_delegated_puzzle_and_solution(
            delegated_puzzle_and_solution,
            [Program.to(None), Program.to(None)],
        )

    @property
    def user_puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(
            nonce=0,
            restrictions=[self.user_restriction],
            member=self.bls_member,
            _top_level=False,
        )

    def user_proven_spend(self, premodified_dpuz: Program) -> dict[bytes32, ProvenSpend]:
        return {
            self.user_puzzle_with_restrictions.puzzle_hash: ProvenSpend(
                puzzle_reveal=self.user_puzzle_with_restrictions.puzzle,
                solution=self.user_puzzle_with_restrictions.solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[self.user_restriction.solve(premodified_dpuz)],
                    member_solution=self.bls_member.solve(),
                ),
            )
        }

    @property
    def fixed_puzzle_member(self) -> FixedPuzzleMember:
        return FixedPuzzleMember(fixed_puzzle_hash=self.claim_pool_reward_dpuz.get_tree_hash())

    @property
    def pool_puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(
            nonce=0,
            restrictions=[],
            member=self.fixed_puzzle_member,
            _top_level=False,
        )

    def pool_proven_spend(self) -> dict[bytes32, ProvenSpend]:
        return {
            self.pool_puzzle_with_restrictions.puzzle_hash: ProvenSpend(
                puzzle_reveal=self.pool_puzzle_with_restrictions.puzzle,
                solution=self.pool_puzzle_with_restrictions.solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[],
                    member_solution=self.fixed_puzzle_member.solve(),
                ),
            )
        }

    @property
    def puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(
            nonce=0,
            restrictions=[],
            member=MofN(
                m=1,
                members=[
                    self.user_puzzle_with_restrictions,
                    self.pool_puzzle_with_restrictions,
                ],
            )
            if self.pooling
            else self.bls_member,
            additional_memos=self.additional_memos,
        )

    @property
    def memo(self) -> Program:
        return self.puzzle_with_restrictions.memo()

    @property
    def additional_memos(self) -> Program:
        if self.pooling:
            return Program.to(
                [
                    self.bls_member.synthetic_key,
                    self.guaranteed_pool_config.pool_puzzle_hash,
                    self.guaranteed_pool_config.heightlock,
                    self.guaranteed_pool_config.pool_memoization,
                ]
            )
        else:
            return Program.to([self.bls_member.synthetic_key])

    @property
    def puzzle(self) -> Program:
        return self.puzzle_with_restrictions.puzzle

    @property
    def puzzle_hash(self) -> bytes32:
        return self.puzzle_with_restrictions.puzzle_hash

    def forward_pool_reward_inner_solution(self, reward: PoolReward) -> Program:
        custody_pwr = self.puzzle_with_restrictions
        assert isinstance(custody_pwr.inner_puzzle, MofN)
        return custody_pwr.solve(
            member_validator_solutions=[],
            dpuz_validator_solutions=[],
            member_solution=custody_pwr.inner_puzzle.solve(self.pool_proven_spend()),
            delegated_puzzle_and_solution=self.claim_pool_reward_dpuz_and_solution(reward),
        )

    def exit_to_from_waiting_room_inner_solution(
        self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution
    ) -> Program:
        custody_pwr = self.puzzle_with_restrictions
        assert isinstance(custody_pwr.inner_puzzle, MofN)
        return custody_pwr.solve(
            member_validator_solutions=[],
            dpuz_validator_solutions=[],
            member_solution=custody_pwr.inner_puzzle.solve(
                self.user_proven_spend(delegated_puzzle_and_solution.puzzle.puzzle)
            ),
            delegated_puzzle_and_solution=self.user_restriction.modify_delegated_puzzle_and_solution(
                delegated_puzzle_and_solution,
                [Program.to([]), Program.to([])],
            ),
        )

    @property
    def exit_to_waiting_room_condition(self) -> CreateCoin:
        return CreateCoin(
            puzzle_hash=self.waiting_room_puzzle.puzzle_hash,
            amount=uint64(1),
            memos=[self.singleton_struct.struct_hash],
        )

    @property
    def exit_from_waiting_room_conditions(self) -> tuple[AssertHeightRelative, CreateCoin]:
        next_plotnft_puzzle = replace(self, pool_config=None, exiting=False)
        return (
            AssertHeightRelative(height=self.guaranteed_pool_config.heightlock),
            CreateCoin(
                puzzle_hash=next_plotnft_puzzle.puzzle_hash,
                amount=uint64(1),
                # maybe the full memo is not strictly necessary, but it's needed for robustness at the moment
                memo_blob=Program.to((self.singleton_struct.struct_hash, next_plotnft_puzzle.memo)),
            ),
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> PlotNFTInnerPuzzle | None:
        mips_match = PuzzleWithRestrictions.match(unknown_puzzle=unknown_puzzle, solution=solution)
        if mips_match is None:
            return None
        assert isinstance(mips_match, PuzzleWithRestrictions)
        assert isinstance(mips_match.puzzle, UnknownPuzzle)
        potential_bls_member_match = BLSWithTaprootMember.match(unknown_puzzle=mips_match.puzzle)
        if potential_bls_member_match is not None:
            return PlotNFTInnerPuzzle(
                user_config=UserConfig(synthetic_pubkey=potential_bls_member_match.guaranteed_synthetic_key)
            )
        potential_mofn_match = MofN.match(unknown_puzzle=mips_match.puzzle, solution=solution)
        if potential_mofn_match is None:
            return None
        if potential_mofn_match.m != 2:
            return None
        raise NotImplementedError("Currently unimplemented")


class GetNextPlotNFTError(Exception):
    pass


@dataclass(kw_only=True, frozen=True)
class PlotNFTLaunchResult(SingletonLaunchResult[PlotNFTInnerPuzzle]):
    necessary_conditions: list[Condition]
    necessary_spends: list[CoinSpend]
    launched_singleton: PlotNFT


@dataclass(kw_only=True, frozen=True)
class PlotNFT(Singleton[PlotNFTInnerPuzzle]):
    coin: Coin
    remarks: list[Remark] = field(default_factory=list)

    @classmethod
    def launch_plotnft(
        cls,
        *,
        origin_coins: list[Coin],
        user_config: UserConfig,
        genesis_challenge: bytes32,
        hint: bytes32,
        pool_config: PoolConfig | None = None,
        exiting: bool = False,
        remark: Remark | None = None,
    ) -> PlotNFTLaunchResult:
        origin_coin = origin_coins[0]
        launcher_coin = Coin(origin_coin.name(), cls.struct_driver.singleton_puzzles.singleton_launcher_hash, uint64(1))
        launcher_id = launcher_coin.name()

        plotnft_inner_puzzle = PlotNFTInnerPuzzle(
            self_launcher_id=launcher_id,
            user_config=user_config,
            pool_config=pool_config,
            exiting=exiting,
            genesis_challenge=genesis_challenge,
        )
        rev_puzzle = P2Conditions(
            conditions=[
                CreateCoin(
                    plotnft_inner_puzzle.puzzle_hash,
                    uint64(1),
                    memo_blob=Program.to((hint, plotnft_inner_puzzle.puzzle_with_restrictions.memo())),
                ),
                CreateCoinAnnouncement(msg=b""),
                *([] if remark is None else [remark]),
            ]
        )
        pre_rev_launch_result = super().launch(
            origin_coin=origin_coin,
            launch_info=SingletonLaunchInfo(desired_inner_puzzle=rev_puzzle, key_value_hints={}),
        )
        rev_coin_id = pre_rev_launch_result.launched_singleton.coin.name()
        assert_rev_ca = AssertCoinAnnouncement(asserted_id=rev_coin_id, asserted_msg=b"")

        rev_spend = make_spend(
            pre_rev_launch_result.launched_singleton.coin,
            pre_rev_launch_result.launched_singleton.puzzle,
            SingletonSolution(
                lineage_proof=LineageProof(parent_name=launcher_coin.parent_coin_info, amount=launcher_coin.amount),
                coin_amount=uint64(1),
                inner_solution=NilSolution(),
            ).as_program(),
        )
        return PlotNFTLaunchResult(
            necessary_conditions=[*pre_rev_launch_result.necessary_conditions, assert_rev_ca],
            necessary_spends=[*pre_rev_launch_result.necessary_spends, rev_spend],
            launched_singleton=cls(
                coin=Coin(
                    rev_coin_id,
                    SingletonPuzzle(launcher_id=launcher_id, inner_puzzle=plotnft_inner_puzzle).puzzle_hash,
                    uint64(1),
                ),
                launcher_id=launcher_id,
                lineage_proof=LineageProof(
                    parent_name=pre_rev_launch_result.launched_singleton.coin.parent_coin_info,
                    inner_puzzle_hash=rev_puzzle.puzzle_hash,
                    amount=pre_rev_launch_result.launched_singleton.coin.amount,
                ),
                inner_puzzle=plotnft_inner_puzzle,
            ),
        )

    @classmethod
    def get_next_from_coin_spend(
        cls,
        *,
        coin_spend: CoinSpend,
        genesis_challenge: bytes32 | None = None,
        pre_uncurry: UncurriedPuzzle | None = None,
        previous_plotnft_puzzle: PlotNFTInnerPuzzle | None = None,
    ) -> Self:
        # some input validation
        if genesis_challenge is None and previous_plotnft_puzzle is None:
            raise GetNextPlotNFTError("Either genesis_challenge or previous_plotnft_puzzle must be provided")
        if genesis_challenge is None:
            assert previous_plotnft_puzzle is not None  # mypy I guess can't figure this out
            genesis_challenge = previous_plotnft_puzzle.genesis_challenge
        if pre_uncurry is None:
            singleton = uncurry_puzzle(coin_spend.puzzle_reveal)
        else:
            singleton = pre_uncurry

        # examine the singleton level info
        if singleton.mod != cls.struct_driver.singleton_puzzles.singleton_mod:
            raise GetNextPlotNFTError("Invalid singleton mod for next PlotNFT")
        if singleton.args.at("frr") != cls.struct_driver.singleton_puzzles.singleton_launcher_hash:
            raise GetNextPlotNFTError("Invalid singleton launcher for next PlotNFT")

        launcher_id = bytes32(singleton.args.at("frf").as_atom())

        inner_puzzle = singleton.args.at("rf")
        inner_conditions = parse_conditions_non_consensus(
            run(inner_puzzle, Program.from_serialized(coin_spend.solution).at("rrf")).as_iter()
        )
        create_coins = [condition for condition in inner_conditions if isinstance(condition, CreateCoin)]
        remarks = [condition for condition in inner_conditions if isinstance(condition, Remark)]
        if len(create_coins) != 1:
            raise GetNextPlotNFTError("PlotNFTs must make exactly one new coin")
        singleton_create_coin = create_coins[0]

        # Now we begin to examine the inner puzzle
        plotnft_puzzle = None

        # First we see if it's just a rev
        if singleton_create_coin.puzzle_hash == inner_puzzle.get_tree_hash() and previous_plotnft_puzzle is not None:
            plotnft_puzzle = previous_plotnft_puzzle

        # Then we see if it's starting/finishing leaving
        if (
            plotnft_puzzle is None
            and previous_plotnft_puzzle is not None
            and previous_plotnft_puzzle.pool_config is not None
        ):
            if (
                replace(previous_plotnft_puzzle, pool_config=None, exiting=False).puzzle_hash
                == singleton_create_coin.puzzle_hash
            ):
                plotnft_puzzle = replace(previous_plotnft_puzzle, pool_config=None, exiting=False)
            elif replace(previous_plotnft_puzzle, exiting=True).puzzle_hash == singleton_create_coin.puzzle_hash:
                plotnft_puzzle = replace(previous_plotnft_puzzle, exiting=True)

        # Finally, we try to look for the memos
        if plotnft_puzzle is None:
            if singleton_create_coin.memo_blob is None:
                raise GetNextPlotNFTError("Invalid memoization of PlotNFT")
            try:
                unknown_inner_puzzle = PuzzleWithRestrictions.from_memo(singleton_create_coin.memo_blob.rest())
            except ValueError:
                raise GetNextPlotNFTError("Invalid memoization of PlotNFT")
            if unknown_inner_puzzle.additional_memos is None:
                raise GetNextPlotNFTError("Invalid memoization of PlotNFT")
            pubkey = G1Element.from_bytes(unknown_inner_puzzle.additional_memos.at("f").as_atom())
            if isinstance(unknown_inner_puzzle.inner_puzzle, MofN):
                pool_puzzle_hash = bytes32(unknown_inner_puzzle.additional_memos.at("rf").as_atom())
                timelock = uint32(unknown_inner_puzzle.additional_memos.at("rrf").as_int())
                pool_memoization = unknown_inner_puzzle.additional_memos.at("rrrf")
                pool_config = PoolConfig(
                    pool_puzzle_hash=pool_puzzle_hash, heightlock=timelock, pool_memoization=pool_memoization
                )
                exiting = (
                    ValidatorStackRestriction(
                        required_wrappers=[Heightlock(heightlock=timelock), SendMessageBanned()]
                    ).puzzle_hash
                    in unknown_inner_puzzle.unknown_puzzles
                )
            else:
                pool_config = None
                exiting = False

            plotnft_puzzle = PlotNFTInnerPuzzle(
                self_launcher_id=launcher_id,
                user_config=UserConfig(synthetic_pubkey=pubkey),
                pool_config=pool_config,
                exiting=exiting,
                genesis_challenge=genesis_challenge,
            )
            if plotnft_puzzle.puzzle_hash != singleton_create_coin.puzzle_hash:
                raise GetNextPlotNFTError("Invalid memoization of PlotNFT")

        return cls(
            coin=Coin(
                coin_spend.coin.name(),
                SingletonPuzzle(launcher_id=launcher_id, inner_puzzle=plotnft_puzzle).puzzle_hash,
                coin_spend.coin.amount,
            ),
            lineage_proof=LineageProof(
                parent_name=coin_spend.coin.parent_coin_info,
                inner_puzzle_hash=inner_puzzle.get_tree_hash(),
                amount=coin_spend.coin.amount,
            ),
            inner_puzzle=plotnft_puzzle,
            launcher_id=launcher_id,
            remarks=remarks,
        )

    def forward_pool_reward(self, reward: PoolReward) -> list[CoinSpend]:
        if not self.inner_puzzle.pooling:
            raise ValueError("Cannot forward pool reward while self pooling. Try `claim_pool_rewards`")
        coin_spend = self.spend(
            inner_solution=UnknownSolution(self.inner_puzzle.forward_pool_reward_inner_solution(reward))
        )
        reward_spends, _ = self.claim_p2_singletons(
            rewards_to_claim=[reward],
            reward_delegated_puzzles_and_solutions=[
                DelegatedPuzzleAndSolution(
                    puzzle=UnknownPuzzle(known_puzzle=self.inner_puzzle.forward_pool_reward_dpuz),
                    solution=UnknownSolution(Program.to([reward.coin.amount])),
                )
            ],
        )
        return [coin_spend, *reward_spends]

    def exit_to_waiting_room(self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution) -> list[CoinSpend]:
        if not self.inner_puzzle.pooling:
            raise ValueError("Cannot exit to waiting room while self pooling.")
        if self.inner_puzzle.exiting:
            raise ValueError("Already exiting to waiting room, cannot exit again")
        coin_spend = self.spend(
            inner_solution=UnknownSolution(
                solution=self.inner_puzzle.exit_to_from_waiting_room_inner_solution(delegated_puzzle_and_solution)
            )
        )
        return [coin_spend]

    def exit_waiting_room(self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution) -> list[CoinSpend]:
        if not self.inner_puzzle.pooling:
            raise ValueError("Cannot exit waiting room while self pooling.")
        if not self.inner_puzzle.exiting:
            raise ValueError("Cannot exit waiting room while not in it")
        coin_spend = self.spend(
            inner_solution=UnknownSolution(
                solution=self.inner_puzzle.exit_to_from_waiting_room_inner_solution(delegated_puzzle_and_solution)
            )
        )
        return [coin_spend]

    def claim_pool_rewards(
        self,
        rewards_to_claim: list[PoolReward],
        reward_delegated_puzzles_and_solutions: list[DelegatedPuzzleAndSolution],
    ) -> list[CoinSpend]:
        if self.inner_puzzle.pooling:
            raise ValueError("Cannot claim rewards while pooling. If you're a pool, try `forward_pool_rewards`")
        if len(rewards_to_claim) != len(reward_delegated_puzzles_and_solutions):
            raise ValueError("Number of rewards and delegated puzzles and solutions must match")
        reward_spends, messages = self.claim_p2_singletons(
            rewards_to_claim=rewards_to_claim,
            reward_delegated_puzzles_and_solutions=reward_delegated_puzzles_and_solutions,
        )
        dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=P2Conditions(
                conditions=[
                    CreateCoin(
                        puzzle_hash=self.inner_puzzle.puzzle_hash,
                        amount=self.coin.amount,
                        memos=[self.singleton_struct.struct_hash],
                    ),
                    *messages,
                ]
            ),
            solution=NilSolution(),
        )
        coin_spend = self.spend(
            inner_solution=UnknownSolution(
                solution=self.inner_puzzle.puzzle_with_restrictions.solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[],
                    member_solution=self.inner_puzzle.bls_member.solve(),
                    delegated_puzzle_and_solution=dpuz_and_solution,
                )
            )
        )
        return [coin_spend, *reward_spends]

    def join_pool(
        self, user_config: UserConfig, pool_config: PoolConfig, extra_conditions: tuple[Condition, ...] = tuple()
    ) -> list[CoinSpend]:
        plotnft_puzzle = PlotNFTInnerPuzzle(
            self_launcher_id=self.launcher_id,
            user_config=user_config,
            pool_config=pool_config,
            exiting=False,
            genesis_challenge=self.inner_puzzle.genesis_challenge,
        )

        dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=P2Conditions(
                conditions=[
                    CreateCoin(
                        plotnft_puzzle.puzzle_hash,
                        amount=self.coin.amount,
                        memo_blob=Program.to((self.singleton_struct.struct_hash, plotnft_puzzle.memo)),
                    ),
                    *extra_conditions,
                ]
            ),
            solution=NilSolution(),
        )
        coin_spend = self.spend(
            inner_solution=UnknownSolution(
                self.inner_puzzle.puzzle_with_restrictions.solve(
                    member_validator_solutions=[],
                    dpuz_validator_solutions=[],
                    member_solution=self.inner_puzzle.bls_member.solve(),
                    delegated_puzzle_and_solution=dpuz_and_solution,
                )
            )
        )
        return [coin_spend]


@dataclass(kw_only=True, frozen=True)
class PoolReward(P2Singleton):
    @property
    def height(self) -> uint32:
        return uint32.from_bytes(self.coin.parent_coin_info[28:])
