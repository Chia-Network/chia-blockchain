from __future__ import annotations

import dataclasses
import logging
import time
from collections import Counter
from typing import Optional

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.server.outbound_message import Message
from chia.server.rate_limit_numbers import RLSettings, Unlimited, get_rate_limits_to_use

log = logging.getLogger(__name__)


# TODO: only full node disconnects based on rate limits
class RateLimiter:
    incoming: bool
    reset_seconds: int
    current_minute: int
    message_counts: Counter[ProtocolMessageTypes]
    message_cumulative_sizes: Counter[ProtocolMessageTypes]
    percentage_of_limit: int
    non_tx_message_counts: int = 0
    non_tx_cumulative_size: int = 0

    def __init__(self, incoming: bool, reset_seconds: int = 60, percentage_of_limit: int = 100):
        """
        The incoming parameter affects whether counters are incremented
        unconditionally or not. For incoming messages, the counters are always
        incremented. For outgoing messages, the counters are only incremented
        if they are allowed to be sent by the rate limiter, since we won't send
        the messages otherwise.
        """
        self.incoming = incoming
        self.reset_seconds = reset_seconds
        self.current_minute = int(time.time() // reset_seconds)
        self.message_counts = Counter()
        self.message_cumulative_sizes = Counter()
        self.percentage_of_limit = percentage_of_limit
        self.non_tx_message_counts = 0
        self.non_tx_cumulative_size = 0

    def process_msg_and_check(
        self, message: Message, our_capabilities: list[Capability], peer_capabilities: list[Capability]
    ) -> Optional[str]:
        """
        Returns a string indicating which limit was hit if a rate limit is
        exceeded, and the message should be blocked. Returns None if the limit was not
        hit and the message is good to be sent or received.
        """

        current_minute = int(time.time() // self.reset_seconds)
        if current_minute != self.current_minute:
            self.current_minute = current_minute
            self.message_counts = Counter()
            self.message_cumulative_sizes = Counter()
            self.non_tx_message_counts = 0
            self.non_tx_cumulative_size = 0
        try:
            message_type = ProtocolMessageTypes(message.type)
        except Exception as e:
            log.warning(f"Invalid message: {message.type}, {e}")
            return None

        new_message_counts: int = self.message_counts[message_type] + 1
        new_cumulative_size: int = self.message_cumulative_sizes[message_type] + len(message.data)
        new_non_tx_count: int = self.non_tx_message_counts
        new_non_tx_size: int = self.non_tx_cumulative_size
        proportion_of_limit: float = self.percentage_of_limit / 100

        ret: bool = False
        rate_limits = get_rate_limits_to_use(our_capabilities, peer_capabilities)

        try:
            limits: RLSettings = rate_limits["default_settings"]
            if message_type in rate_limits["rate_limits_tx"]:
                limits = rate_limits["rate_limits_tx"][message_type]
            elif message_type in rate_limits["rate_limits_other"]:
                limits = rate_limits["rate_limits_other"][message_type]
                if isinstance(limits, RLSettings):
                    non_tx_freq = rate_limits["non_tx_freq"]
                    non_tx_max_total_size = rate_limits["non_tx_max_total_size"]
                    new_non_tx_count = self.non_tx_message_counts + 1
                    new_non_tx_size = self.non_tx_cumulative_size + len(message.data)
                    if new_non_tx_count > non_tx_freq * proportion_of_limit:
                        return " ".join(
                            [
                                f"non-tx count: {new_non_tx_count}",
                                f"> {non_tx_freq * proportion_of_limit}",
                                f"(scale factor: {proportion_of_limit})",
                            ]
                        )
                    if new_non_tx_size > non_tx_max_total_size * proportion_of_limit:
                        return " ".join(
                            [
                                f"non-tx size: {new_non_tx_size}",
                                f"> {non_tx_max_total_size * proportion_of_limit}",
                                f"(scale factor: {proportion_of_limit})",
                            ]
                        )
            else:  # pragma: no cover
                log.warning(
                    f"Message type {message_type} not found in rate limits (scale factor: {proportion_of_limit})",
                )

            if isinstance(limits, Unlimited):
                # this message type is not rate limited. This is used for
                # response messages and must be combined with banning peers
                # sending unsolicited responses of this type
                if len(message.data) > limits.max_size:
                    return f"message size: {len(message.data)} > {limits.max_size}"
                ret = True
                return None
            elif isinstance(limits, RLSettings):
                if limits.max_total_size is None:
                    limits = dataclasses.replace(limits, max_total_size=limits.frequency * limits.max_size)
                assert limits.max_total_size is not None

                if new_message_counts > limits.frequency * proportion_of_limit:
                    return " ".join(
                        [
                            f"message count: {new_message_counts}"
                            f"> {limits.frequency * proportion_of_limit}"
                            f"(scale factor: {proportion_of_limit})"
                        ]
                    )
                if len(message.data) > limits.max_size:
                    return f"message size: {len(message.data)} > {limits.max_size}"
                if new_cumulative_size > limits.max_total_size * proportion_of_limit:
                    return " ".join(
                        [
                            f"cumulative size: {new_cumulative_size}",
                            f"> {limits.max_total_size * proportion_of_limit}",
                            f"(scale factor: {proportion_of_limit})",
                        ]
                    )

                ret = True
                return None
            else:  # pragma: no cover
                return f"Internal Error, unknown rate limit for message: {message_type}, limit: {limits}"
        finally:
            if self.incoming or ret:
                # now that we determined that it's OK to send the message, commit the
                # updates to the counters. Alternatively, if this was an
                # incoming message, we already received it and it should
                # increment the counters unconditionally
                self.message_counts[message_type] = new_message_counts
                self.message_cumulative_sizes[message_type] = new_cumulative_size
                self.non_tx_message_counts = new_non_tx_count
                self.non_tx_cumulative_size = new_non_tx_size
