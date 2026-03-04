from __future__ import annotations

import asyncio
import time

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.timelord import timelord as timelord_module
from chia.timelord.timelord_service import TimelordService
from chia.timelord.types import Chain
from chia.types.blockchain_format.classgroup import ClassgroupElement


@pytest.mark.anyio
async def test_timelord_has_no_server(timelord_service: TimelordService) -> None:
    timelord_server = timelord_service._node.server
    assert timelord_server.webserver is None


class _NullTransport(asyncio.Transport):
    def write(self, data: bytes) -> None:
        pass

    def is_closing(self) -> bool:
        return False


def _make_null_writer() -> asyncio.StreamWriter:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    return asyncio.StreamWriter(_NullTransport(), protocol, reader, loop)


@pytest.mark.anyio
async def test_invalid_vdf_proof_is_ignored_in_process_communication(
    timelord_service: TimelordService, monkeypatch: pytest.MonkeyPatch
) -> None:
    timelord = timelord_service._node
    chain = Chain.CHALLENGE_CHAIN
    challenge = bytes32.zeros
    initial_form = ClassgroupElement.get_default_element()
    timelord.chain_start_time[chain] = time.time()

    state_changed_calls: list[object] = []
    monkeypatch.setattr(timelord_module, "validate_vdf", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(timelord, "state_changed", lambda *args, **kwargs: state_changed_calls.append((args, kwargs)))

    iterations_needed = uint64(10)
    y_bytes = initial_form.data
    witness_type = 0
    proof_bytes = b"\x01\x02"
    proof_payload = (
        int(iterations_needed).to_bytes(8, "big", signed=True)
        + len(y_bytes).to_bytes(8, "big", signed=True)
        + y_bytes
        + bytes([witness_type])
        + proof_bytes
    )
    encoded_payload = proof_payload.hex().encode()

    reader = asyncio.StreamReader()
    reader.feed_data(b"OK")
    reader.feed_data(len(encoded_payload).to_bytes(4, "big"))
    reader.feed_data(encoded_payload)
    reader.feed_data(b"STOP")
    reader.feed_eof()

    writer = _make_null_writer()
    await timelord._do_process_communication(chain, challenge, initial_form, "127.0.0.1", reader, writer, proof_label=1)

    assert timelord.proofs_finished == []
    assert state_changed_calls == []
