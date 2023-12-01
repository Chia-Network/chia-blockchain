from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Union

import zstd

from chia.protocols.full_node_protocol import NewPeak, RespondSignagePoint
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.streamable import Streamable, streamable

STRUCTURED_LOG_VERSION = uint8(0)


class MessageType(IntEnum):
    # msg_body is LogHeader
    START = 0

    # msg_body is PeerConnected
    NEW_PEER_CONNECTION = 1

    # msg_body is UnfinishedBlock
    INCOMING_UNFINISHED_BLOCK = 2
    OUTGOING_UNFINISHED_BLOCK = 3

    # msg_body is RespondSignagePoint
    INCOMING_SIGNAGE_POINT = 4

    # msg_type is SpendBundle
    INCOMING_TRANSACTION = 5

    # msg_type is full_node_protocol.NewPeak
    NEW_PEAK = 6


@streamable
@dataclass(frozen=True)
class LogHeader(Streamable):
    # version of the structured log format
    version: uint8
    # start time (unix time)
    start_time: uint64


@streamable
@dataclass(frozen=True)
class PeerConnected(Streamable):
    version: str
    protocol_version: str
    outbound: bool
    port: uint16
    peer_node_id: bytes32
    host: str
    connection_type: uint8


@streamable
@dataclass(frozen=True)
class Message(Streamable):
    # timestamp of event
    timestamp: uint32

    # the index of the peer involved in this event (0 if no peer was involved)
    peer: uint32

    # that type to expect in msg_body
    msg_type: uint16

    # Streamable encoded message whose type is determined by msg_type
    msg_body: bytes


@dataclass
class StructuredLog:
    # the log file, opened in append-mode
    file: io.BufferedWriter

    # timestamp of when we started logging. Timestamps on events are relative to
    # this
    start_time: int

    # the mutex is used to synchronize updates to the log file, and log file
    # rotation
    mutex: asyncio.Lock = field(default_factory=asyncio.Lock)

    # the number of bytes written to file. This is used for log rotation
    byte_count: int = 0

    @staticmethod
    async def create() -> StructuredLog:
        ts = uint64(time.time())
        ret = StructuredLog(open(DEFAULT_ROOT_PATH / "log" / f"event-log-{ts:010}", "ab"), int(time.monotonic()))
        await ret.log(MessageType.START, uint32(0), LogHeader(STRUCTURED_LOG_VERSION, ts))
        return ret

    async def log(
        self,
        msg_type: MessageType,
        peer_id: uint32,
        body: Union[LogHeader, PeerConnected, SpendBundle, UnfinishedBlock, RespondSignagePoint, NewPeak],
    ) -> None:
        ts = uint32(time.monotonic() - self.start_time)

        msg = Message(ts, peer_id, uint16(msg_type.value), zstd.compress(bytes(body)))
        msg_bytes = bytes(msg)

        if msg_type == MessageType.START:
            assert isinstance(body, LogHeader)
        elif msg_type == MessageType.NEW_PEER_CONNECTION:
            assert isinstance(body, PeerConnected)
        elif msg_type == MessageType.INCOMING_UNFINISHED_BLOCK:
            assert isinstance(body, UnfinishedBlock)
        elif msg_type == MessageType.OUTGOING_UNFINISHED_BLOCK:
            assert isinstance(body, UnfinishedBlock)
        elif msg_type == MessageType.INCOMING_SIGNAGE_POINT:
            assert isinstance(body, RespondSignagePoint)
        elif msg_type == MessageType.INCOMING_TRANSACTION:
            assert isinstance(body, SpendBundle)
        elif msg_type == MessageType.NEW_PEAK:
            assert isinstance(body, NewPeak)
        else:
            assert False

        async with self.mutex:
            if self.byte_count > 100_000_000:
                # rotate file
                self.byte_count = 0
                self.file.close()
                self.file = open(DEFAULT_ROOT_PATH / "log" / f"event-log-{int(time.time()):010}", "ab")
            self.file.write(msg_bytes)
            self.byte_count += len(msg_bytes)
