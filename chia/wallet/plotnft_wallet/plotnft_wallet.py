from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, ClassVar, cast, final

from chia_rs import G2Element
from chia_rs.chia_rs import Coin, G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64, uint128
from typing_extensions import Self, Unpack

from chia.pools.plotnft_drivers import PlotNFT, PoolConfig, PoolReward, RewardPuzzle, SingletonStruct, UserConfig
from chia.pools.pool_wallet_info import PoolSingletonState, PoolState, PoolWalletInfo
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.program import Program
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.wallet.conditions import AssertCoinAnnouncement, Condition, CreateCoin, CreateCoinAnnouncement, Remark
from chia.wallet.puzzles.custody.custody_architecture import DelegatedPuzzleAndSolution
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


@final
@dataclasses.dataclass
class PlotNFT2Wallet:
    if TYPE_CHECKING:
        from chia.wallet.wallet_protocol import WalletProtocol

        _protocol_check: ClassVar[WalletProtocol[object]] = cast("PlotNFT2Wallet", None)

    wallet_state_manager: WalletStateManager
    xch_wallet: Wallet
    log: logging.Logger
    wallet_info: WalletInfo

    @classmethod
    async def create(
        cls, *, wallet_state_manager: WalletStateManager, xch_wallet: Wallet, wallet_info: WalletInfo
    ) -> Self:
        self = cls(
            wallet_state_manager=wallet_state_manager,
            xch_wallet=xch_wallet,
            log=logging.getLogger(__name__),
            wallet_info=wallet_info,
        )
        await wallet_state_manager.add_interested_puzzle_hashes(
            puzzle_hashes=[self.p2_singleton_puzzle_hash, self.hint], wallet_ids=[self.id()]
        )
        if await wallet_state_manager.user_store.get_wallet_by_id(wallet_info.id) is None:
            await wallet_state_manager.user_store.create_wallet(
                name=wallet_info.name,
                wallet_type=wallet_info.type,
                data=wallet_info.data,
                id=wallet_info.id,
            )
        async with wallet_state_manager.new_action_scope(
            tx_config=wallet_state_manager.tx_config, push=True
        ) as action_scope:
            if wallet_state_manager.config["plotnft2_claim_address"] is None:
                claim_address = encode_puzzle_hash(
                    await action_scope.get_puzzle_hash(wallet_state_manager),
                    AddressType.XCH.hrp(wallet_state_manager.config),
                )
                wallet_state_manager.config["plotnft2_claim_address"] = claim_address
        return self

    @property
    def hint(self) -> bytes32:
        return SingletonStruct(launcher_id=self.plotnft_id).struct_hash()

    @property
    def plotnft_id(self) -> bytes32:
        return bytes32.from_hexstr(self.wallet_info.data)

    @property
    def p2_singleton_puzzle_hash(self) -> bytes32:
        return RewardPuzzle(singleton_id=self.plotnft_id).puzzle_hash()

    @property
    def rewards_claim_puzhash(self) -> bytes32:
        return decode_puzzle_hash(self.wallet_state_manager.config["plotnft2_claim_address"])

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.PLOTNFT_2

    def id(self) -> uint32:
        return self.wallet_info.id

    def get_name(self) -> str:
        return self.wallet_info.name

    # Actions
    @classmethod
    async def create_new(
        cls,
        *,
        wallet_state_manager: WalletStateManager,
        xch_wallet: Wallet,
        action_scope: WalletActionScope,
        fee: uint64,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> None:
        target_puzzle_hash = await action_scope.get_puzzle_hash(wallet_state_manager)
        target_pubkey = G1Element.from_bytes(await wallet_state_manager.get_public_key(target_puzzle_hash))
        origin_coins = await xch_wallet.select_coins(amount=uint64(fee + 1), action_scope=action_scope)
        announcement_assertions, coin_spends, new_plotnft = PlotNFT.launch(
            origin_coins=list(origin_coins),
            user_config=UserConfig(synthetic_pubkey=xch_wallet.convert_public_key_to_synthetic(target_pubkey)),
            genesis_challenge=wallet_state_manager.constants.GENESIS_CHALLENGE,
            hint=target_puzzle_hash,
        )
        async with action_scope.use() as interface:
            interface.side_effects.extra_spends.append(WalletSpendBundle(coin_spends, G2Element()))
        await xch_wallet.generate_signed_transaction(
            amounts=[uint64(1)],
            puzzle_hashes=[new_plotnft.singleton_struct.singleton_puzzles.singleton_launcher_hash],
            action_scope=action_scope,
            fee=fee,
            coins=origin_coins,
            extra_conditions=(*announcement_assertions, *extra_conditions),
            origin_id=coin_spends[0].coin.parent_coin_info,
        )

    async def claim_rewards(
        self,
        *,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> None:
        rewards_to_claim = await self.wallet_state_manager.plotnft2_store.get_pool_rewards(plotnft_id=self.plotnft_id)
        if len(rewards_to_claim) == 0:
            raise ValueError("No rewards to claim")
        total_reward_amount = uint64(sum(reward.coin.amount for reward in rewards_to_claim))
        if fee > total_reward_amount:
            raise ValueError("Fee is greater than the total amount of rewards")

        plotnft = await self.get_current_plotnft()
        coin_spends = plotnft.claim_pool_rewards(
            rewards_to_claim=rewards_to_claim,
            reward_delegated_puzzles_and_solutions=[
                DelegatedPuzzleAndSolution(
                    puzzle=self.xch_wallet.make_solution(
                        primaries=[
                            CreateCoin(
                                puzzle_hash=self.rewards_claim_puzhash,
                                amount=uint64(total_reward_amount - fee),
                            ),
                        ],
                        fee=fee,
                        conditions=(*extra_conditions, CreateCoinAnnouncement(b""))
                        if len(rewards_to_claim) > 1
                        else extra_conditions,
                    ).at("rf"),  # strips away to just the delegated puzzle (bit of a hack)
                    solution=Program.to(None),
                )
                if i == 0
                else DelegatedPuzzleAndSolution(
                    puzzle=Program.to(
                        (
                            1,
                            [
                                AssertCoinAnnouncement(
                                    asserted_id=rewards_to_claim[0].coin.name(), asserted_msg=b""
                                ).to_program()
                            ],
                        )
                    ),
                    solution=Program.to(None),
                )
                for i, reward in enumerate(rewards_to_claim)
            ],
        )

        spend_bundle = WalletSpendBundle(coin_spends, G2Element())

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                self.wallet_state_manager.new_outgoing_transaction(
                    wallet_id=self.id(),
                    puzzle_hash=self.rewards_claim_puzhash,
                    amount=total_reward_amount,
                    fee=fee,
                    spend_bundle=spend_bundle,
                    additions=[
                        Coin(
                            parent_coin_info=rewards_to_claim[0].coin.name(),
                            puzzle_hash=self.rewards_claim_puzhash,
                            amount=uint64(total_reward_amount - fee),
                        ),
                        Coin(
                            parent_coin_info=plotnft.coin.name(),
                            puzzle_hash=plotnft.puzzle_hash(nonce=uint64(0)),
                            amount=uint64(1),
                        ),
                    ],
                    removals=[reward.coin for reward in rewards_to_claim],
                    name=spend_bundle.name(),
                    extra_conditions=extra_conditions,
                )
            )

    async def join_pool(
        self,
        *,
        pool_config: PoolConfig,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        pool_url: str,
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> None:
        plotnft = await self.get_current_plotnft()
        fee_hook = CreateCoinAnnouncement(msg=b"", coin_id=plotnft.coin.name())
        url_remark = Remark(rest=Program.to(pool_url))
        coin_spends = plotnft.join_pool(
            user_config=plotnft.user_config,
            pool_config=pool_config,
            extra_conditions=(*extra_conditions, fee_hook, url_remark),
        )
        await self.xch_wallet.create_tandem_xch_tx(
            fee=fee,
            action_scope=action_scope,
            extra_conditions=(fee_hook.corresponding_assertion(),),
        )

        spend_bundle = WalletSpendBundle(coin_spends, G2Element())

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                self.wallet_state_manager.new_outgoing_transaction(
                    wallet_id=self.id(),
                    puzzle_hash=pool_config.pool_puzzle_hash,
                    amount=uint64(1),
                    fee=fee,
                    spend_bundle=spend_bundle,
                    additions=[
                        Coin(
                            parent_coin_info=plotnft.coin.name(),
                            puzzle_hash=dataclasses.replace(plotnft, pool_config=pool_config).puzzle_hash(nonce=0),
                            amount=uint64(1),
                        )
                    ],
                    removals=[plotnft.coin],
                    name=spend_bundle.name(),
                    extra_conditions=extra_conditions,
                )
            )

    async def leave_pool(
        self,
        *,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        finish_leaving_fee: uint64 = uint64(0),
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> None:
        plotnft = await self.get_current_plotnft()
        next_plotnft = dataclasses.replace(plotnft, exiting=True)
        fee_hook = CreateCoinAnnouncement(msg=b"", coin_id=plotnft.coin.name())
        exit_create_coin = plotnft.exit_to_waiting_room_condition()
        exit_to_waiting_room_dpuz_and_sol = DelegatedPuzzleAndSolution(
            puzzle=self.xch_wallet.make_solution(
                primaries=[exit_create_coin],
                conditions=(*extra_conditions, fee_hook),
            ).at("rf"),  # strips away to just the delegated puzzle (bit of a hack)
            solution=Program.to(None),
        )
        coin_spends = plotnft.exit_to_waiting_room(exit_to_waiting_room_dpuz_and_sol)
        await self.xch_wallet.create_tandem_xch_tx(
            fee=fee,
            action_scope=action_scope,
            extra_conditions=(fee_hook.corresponding_assertion(),),
        )

        spend_bundle = WalletSpendBundle(coin_spends, G2Element())

        async with action_scope.use() as interface:
            interface.side_effects.plotnft_exiting_info = self.id(), finish_leaving_fee
            interface.side_effects.transactions.append(
                self.wallet_state_manager.new_outgoing_transaction(
                    wallet_id=self.id(),
                    puzzle_hash=exit_create_coin.puzzle_hash,
                    amount=uint64(1),
                    fee=fee,
                    spend_bundle=spend_bundle,
                    additions=[
                        Coin(
                            parent_coin_info=plotnft.coin.name(),
                            puzzle_hash=next_plotnft.puzzle_hash(nonce=0),
                            amount=uint64(1),
                        )
                    ],
                    removals=[plotnft.coin],
                    name=spend_bundle.name(),
                    extra_conditions=extra_conditions,
                )
            )

    async def _finish_leaving_pool(
        self,
        *,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> None:
        plotnft = await self.get_current_plotnft()
        fee_hook = CreateCoinAnnouncement(msg=b"", coin_id=plotnft.coin.name())
        heightlock, exit_create_coin = plotnft.exit_from_waiting_room_conditions()
        exit_to_waiting_room_dpuz_and_sol = DelegatedPuzzleAndSolution(
            puzzle=self.xch_wallet.make_solution(
                primaries=[exit_create_coin],
                conditions=(fee_hook, heightlock, *extra_conditions),
            ).at("rf"),  # strips away to just the delegated puzzle (bit of a hack)
            solution=Program.to(None),
        )
        coin_spends = plotnft.exit_waiting_room(exit_to_waiting_room_dpuz_and_sol)
        await self.xch_wallet.create_tandem_xch_tx(
            fee=fee,
            action_scope=action_scope,
            extra_conditions=(fee_hook.corresponding_assertion(),),
        )

        spend_bundle = WalletSpendBundle(coin_spends, G2Element())

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                self.wallet_state_manager.new_outgoing_transaction(
                    wallet_id=self.id(),
                    puzzle_hash=exit_create_coin.puzzle_hash,
                    amount=uint64(1),
                    fee=fee,
                    spend_bundle=spend_bundle,
                    additions=[
                        Coin(
                            parent_coin_info=plotnft.coin.name(),
                            puzzle_hash=dataclasses.replace(plotnft, pool_config=None, exiting=False).puzzle_hash(
                                nonce=0
                            ),
                            amount=uint64(1),
                        )
                    ],
                    removals=[plotnft.coin],
                    name=spend_bundle.name(),
                    extra_conditions=(heightlock,),
                )
            )

    # Syncing
    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: object | None) -> None:
        if isinstance(coin_data, PlotNFT):
            await self.wallet_state_manager.plotnft2_store.add_plotnft(plotnft=coin_data, created_height=height)
            if coin_data.exiting:
                await self.wallet_state_manager.plotnft2_store.add_exiting_height(
                    wallet_id=self.id(), height=uint32(height + coin_data.guaranteed_pool_config.heightlock)
                )
            else:
                finish_height = await self.wallet_state_manager.plotnft2_store.get_exiting_height(wallet_id=self.id())
                if finish_height is not None and finish_height < height:
                    await self.wallet_state_manager.plotnft2_store.clear_exiting_info(wallet_id=self.id())
        elif coin_data is None and coin.puzzle_hash == self.p2_singleton_puzzle_hash:
            if coin.parent_coin_info[0:16] == self.wallet_state_manager.constants.GENESIS_CHALLENGE[0:16]:
                await self.wallet_state_manager.plotnft2_store.add_pool_reward(
                    pool_reward=PoolReward(
                        singleton_id=self.plotnft_id, coin=coin, height=uint32.from_bytes(coin.parent_coin_info[28:32])
                    )
                )
            else:
                raise ValueError(f"A non-pooling reward coin was paid to PlotNFT with id: {self.plotnft_id}")

    async def new_peak(self, height: uint32) -> None:
        finish_height = await self.wallet_state_manager.plotnft2_store.get_exiting_height(wallet_id=self.id())
        if finish_height is not None and finish_height <= height - 2:  # 2 blocks for a little reorg safety
            if await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_id=self.id()) != []:
                self.log.info(f"Not finishing plotnft from wallet {self.id()} due to unconfirmed transactions")
                return None
            finish_fee = await self.wallet_state_manager.plotnft2_store.get_exiting_fee(wallet_id=self.id())
            if finish_fee is None:
                self.log.warning(f"Not finishing plotnft from wallet {self.id()}, no finish fee set")
                return None
            async with self.wallet_state_manager.new_action_scope(
                self.wallet_state_manager.tx_config, push=True, sign=True
            ) as action_scope:
                await self._finish_leaving_pool(action_scope=action_scope, fee=finish_fee)

    # State
    async def get_current_plotnft(self) -> PlotNFT:
        return await self.wallet_state_manager.plotnft2_store.get_latest_plotnft(self.plotnft_id)

    async def get_confirmed_balance(self, record_list: set[WalletCoinRecord] | None = None) -> uint128:
        return uint128(
            sum(
                cr.coin.amount
                for cr in await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())
                if cr.coin.amount != 1  # bit of a hack, but should work well enough to filter out the plotnft
            )
        )

    async def get_unconfirmed_balance(self, unspent_records: set[WalletCoinRecord] | None = None) -> uint128:
        # bit of a hack, but should work well enough to filter out the plotnft
        if unspent_records is None:
            unspent_records = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())
        unspent_records = set(cr for cr in unspent_records if cr.coin.amount != 1)

        return await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(self.id(), unspent_records)

    async def get_spendable_balance(self, unspent_records: set[WalletCoinRecord] | None = None) -> uint128:
        return await self.get_unconfirmed_balance(unspent_records=unspent_records)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, records: set[WalletCoinRecord] | None = None) -> uint128:
        return await self.get_spendable_balance(records)

    async def get_current_state(self) -> PoolWalletInfo:  # backwards compat with previous pool wallet
        plotnft = await self.get_current_plotnft()
        if plotnft.pool_config is None:
            singleton_state = PoolSingletonState.SELF_POOLING
            rewards_claim_ph = self.rewards_claim_puzhash
        else:
            rewards_claim_ph = plotnft.pool_config.pool_puzzle_hash
            if plotnft.exiting:
                singleton_state = PoolSingletonState.LEAVING_POOL
            else:
                singleton_state = PoolSingletonState.FARMING_TO_POOL
        return PoolWalletInfo(
            current=PoolState(
                version=uint8(2),
                state=uint8(singleton_state.value),
                target_puzzle_hash=rewards_claim_ph,
                owner_pubkey=plotnft.user_config.synthetic_pubkey,
                pool_url=await self.wallet_state_manager.plotnft2_store.get_latest_remark(plotnft.launcher_id),
                relative_lock_height=plotnft.pool_config.heightlock if plotnft.pool_config is not None else uint32(0),
            ),
            target=PoolState(
                version=uint8(2),
                state=uint8(PoolSingletonState.FARMING_TO_POOL.value),
                target_puzzle_hash=self.rewards_claim_puzhash,
                owner_pubkey=plotnft.user_config.synthetic_pubkey,
                pool_url=None,
                relative_lock_height=uint32(0),
            )
            if plotnft.exiting
            else None,
            launcher_coin=Coin(bytes32.zeros, bytes32.zeros, uint64(0)),
            launcher_id=plotnft.launcher_id,
            p2_singleton_puzzle_hash=RewardPuzzle(singleton_id=plotnft.launcher_id).puzzle_hash(),
            tip_singleton_coin_id=plotnft.coin.name(),
            singleton_block_height=await self.wallet_state_manager.plotnft2_store.get_plotnft_created_height(
                coin_id=plotnft.coin.name()
            ),
        )

    # Wallet Protocol Stubs
    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        # We're choosing not to implement this for now as it shouldn't be necessary
        return False

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise RuntimeError("puzzle_hash_for_pk is not implemented for PlotNFT2Wallet")

    def require_derivation_paths(self) -> bool:
        return False

    async def generate_signed_transaction(
        self,
        amounts: list[uint64],
        puzzle_hashes: list[bytes32],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: set[Coin] | None = None,
        memos: list[list[bytes]] | None = None,
        extra_conditions: tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> None:
        raise RuntimeError(
            "generate_signed_transaction is not implemented for PlotNFT2Wallet. Try join/leave/exit_pool instead."
        )

    async def select_coins(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> set[Coin]:
        raise RuntimeError("PlotNFT2Wallet does not support select_coins()")
