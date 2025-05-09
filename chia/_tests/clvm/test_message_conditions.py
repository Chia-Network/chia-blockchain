from __future__ import annotations

import dataclasses

import pytest
from chia_rs import Coin, G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia._tests.util.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.conditions import MessageParticipant, ReceiveMessage, SendMessage
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mode",
    [i for i in range(0b001001, 0b111111 + 1) if i % 8 != 0],  # skipping anything ending in 000
)
async def test_basic_message_send_receive(mode: int, cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, client):
        # Farm two ACS coins
        await sim.farm_block(ACS_PH)
        [sender_coin, receiver_coin] = await client.get_coin_records_by_puzzle_hash(ACS_PH)

        # Try only a sent message
        send_condition = SendMessage(
            b"foo",
            mode_integer=uint8(mode),
            receiver=MessageParticipant(
                parent_id_committed=receiver_coin.coin.parent_coin_info if mode & 0b000100 else None,
                puzzle_hash_committed=receiver_coin.coin.puzzle_hash if mode & 0b000010 else None,
                amount_committed=receiver_coin.coin.amount if mode & 0b000001 else None,
                coin_id_committed=receiver_coin.coin.name() if mode & 0b000111 == 0b000111 else None,
            ),
        )
        only_sender = WalletSpendBundle(
            [
                make_spend(
                    sender_coin.coin,
                    ACS,
                    Program.to([send_condition.to_program()]),
                ),
            ],
            G2Element(),
        )
        result = await client.push_tx(only_sender)
        assert result == (MempoolInclusionStatus.FAILED, Err.MESSAGE_NOT_SENT_OR_RECEIVED)

        # Try only a received message
        receive_condition = ReceiveMessage(
            b"foo",
            mode_integer=uint8(mode),
            sender=MessageParticipant(
                parent_id_committed=sender_coin.coin.parent_coin_info if mode & 0b100000 else None,
                puzzle_hash_committed=sender_coin.coin.puzzle_hash if mode & 0b010000 else None,
                amount_committed=sender_coin.coin.amount if mode & 0b001000 else None,
                coin_id_committed=sender_coin.coin.name() if mode & 0b111000 == 0b111000 else None,
            ),
        )
        only_receiver = WalletSpendBundle(
            [
                make_spend(
                    receiver_coin.coin,
                    ACS,
                    Program.to([receive_condition.to_program()]),
                ),
            ],
            G2Element(),
        )
        result = await client.push_tx(only_receiver)
        assert result == (MempoolInclusionStatus.FAILED, Err.MESSAGE_NOT_SENT_OR_RECEIVED)

        # Make sure they succeed together
        result = await client.push_tx(WalletSpendBundle.aggregate([only_sender, only_receiver]))
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # Quickly test back and forth parsing
        assert SendMessage.from_program(send_condition.to_program()).to_program() == send_condition.to_program()
        assert (
            ReceiveMessage.from_program(receive_condition.to_program()).to_program() == receive_condition.to_program()
        )

        # Quickly test mode calculation
        assert (
            dataclasses.replace(send_condition, sender=receive_condition.sender, mode_integer=None).mode
            == send_condition.mode
        )
        assert (
            dataclasses.replace(receive_condition, receiver=send_condition.receiver, mode_integer=None).mode
            == receive_condition.mode
        )


def test_message_error_conditions() -> None:
    with pytest.raises(ValueError, match="Must specify at least one committment"):
        MessageParticipant()

    test_coin = Coin(bytes32.zeros, bytes32.zeros, uint64(0))
    with pytest.raises(ValueError, match="You must specify all or none"):
        MessageParticipant(coin_id_committed=test_coin.name(), parent_id_committed=bytes32.zeros)

    with pytest.raises(AssertionError, match="The value for coin_id_committed must be equal"):
        MessageParticipant(
            coin_id_committed=test_coin.name(),
            parent_id_committed=bytes32.zeros,
            puzzle_hash_committed=bytes32.zeros,
            amount_committed=uint64(1),
        )

    for mode in range(0b001, 0b111 + 1):
        with pytest.raises(AssertionError, match="If mode_integer is manually specified"):
            MessageParticipant(
                mode_integer=uint8(mode),
                parent_id_committed=test_coin.parent_coin_info if not mode & 0b100 else None,
                puzzle_hash_committed=test_coin.puzzle_hash if not mode & 0b010 else None,
                amount_committed=test_coin.amount if (not mode & 0b001) or (mode == 0b111) else None,
            )

    with pytest.raises(ValueError, match="without committment information"):
        MessageParticipant(
            mode_integer=uint8(0b111),
        ).necessary_args

    with pytest.raises(ValueError, match="Must specify either mode_integer or both sender and receiver"):
        SendMessage(
            msg=b"foo",
            sender=MessageParticipant(coin_id_committed=test_coin.name()),
        )

    with pytest.raises(ValueError, match="Must specify either mode_integer or both sender and receiver"):
        SendMessage(
            msg=b"foo",
            receiver=MessageParticipant(coin_id_committed=test_coin.name()),
        )

    with pytest.raises(AssertionError, match="don't match the sender's mode"):
        SendMessage(
            msg=b"foo",
            mode_integer=uint8(0b111111),
            sender=MessageParticipant(mode_integer=uint8(0b001)),
        )

    with pytest.raises(AssertionError, match="don't match the receiver's mode"):
        SendMessage(
            msg=b"foo",
            mode_integer=uint8(0b111111),
            receiver=MessageParticipant(mode_integer=uint8(0b001)),
        )

    with pytest.raises(ValueError, match="Must specify either var_args or receiver"):
        SendMessage(
            msg=b"foo",
            mode_integer=uint8(0b111111),
        )

    with pytest.raises(ValueError, match="Must specify either var_args or sender"):
        ReceiveMessage(
            msg=b"foo",
            mode_integer=uint8(0b111111),
        )

    with pytest.raises(AssertionError, match="do not match the specified arguments"):
        SendMessage(
            msg=b"foo",
            mode_integer=uint8(0b111111),
            var_args=[Program.to(test_coin.name())],
            receiver=MessageParticipant(coin_id_committed=bytes32.zeros),
        )

    with pytest.raises(AssertionError, match="do not match the specified arguments"):
        ReceiveMessage(
            msg=b"foo",
            mode_integer=uint8(0b111111),
            var_args=[Program.to(test_coin.name())],
            sender=MessageParticipant(coin_id_committed=bytes32.zeros),
        )
