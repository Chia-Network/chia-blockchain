from __future__ import annotations

import dataclasses
import logging
import time
from collections import Counter
from typing import Dict, List

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.server.outbound_message import Message
from chia.server.rate_limit_numbers import RLSettings, get_rate_limits_to_use

log = logging.getLogger(__name__)


# TODO: only full node disconnects based on rate limits
class RateLimiter:
    incoming: bool
    reset_seconds: int
    current_minute: int
    message_counts: Counter
    message_cumulative_sizes: Counter
    percentage_of_limit: int
    non_tx_message_counts: int = 0
    non_tx_cumulative_size: int = 0

    def __init__(self, incoming: bool, reset_seconds=60, percentage_of_limit=100):
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
        self, message: Message, our_capabilities: List[Capability], peer_capabilities: List[Capability]
    ) -> bool:
        """
        Returns True if message can be processed successfully, false if a rate limit is passed.
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
            return True

        new_message_counts: int = self.message_counts[message_type] + 1
        new_cumulative_size: int = self.message_cumulative_sizes[message_type] + len(message.data)
        new_non_tx_count: int = self.non_tx_message_counts
        new_non_tx_size: int = self.non_tx_cumulative_size
        proportion_of_limit: float = self.percentage_of_limit / 100

        ret: bool = False
        rate_limits: Dict = get_rate_limits_to_use(our_capabilities, peer_capabilities)

        try:

            limits: RLSettings = rate_limits["default_settings"]
            if message_type in rate_limits["rate_limits_tx"]:
                limits = rate_limits["rate_limits_tx"][message_type]
            elif message_type in rate_limits["rate_limits_other"]:
                limits = rate_limits["rate_limits_other"][message_type]
                non_tx_freq = rate_limits["non_tx_freq"]
                non_tx_max_total_size = rate_limits["non_tx_max_total_size"]
                new_non_tx_count = self.non_tx_message_counts + 1
                new_non_tx_size = self.non_tx_cumulative_size + len(message.data)
                if new_non_tx_count > non_tx_freq * proportion_of_limit:
                    return False
                if new_non_tx_size > non_tx_max_total_size * proportion_of_limit:
                    return False
            else:
                log.warning(f"Message type {message_type} not found in rate limits")

            if limits.max_total_size is None:
                limits = dataclasses.replace(limits, max_total_size=limits.frequency * limits.max_size)
            assert limits.max_total_size is not None

            if new_message_counts > limits.frequency * proportion_of_limit:
                return False
            if len(message.data) > limits.max_size:
                return False
            if new_cumulative_size > limits.max_total_size * proportion_of_limit:
                return False

            ret = True
            return True
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
