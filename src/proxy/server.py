import functools
import logging

from aiter import join_aiters, map_aiter
from aiter.event_stream import rws_to_event_aiter

from .messages import reader_to_cbor_stream, xform_to_cbor_message

log = logging.getLogger(__name__)


def _transform_args(kwarg_transformers, message):
    """
    Transform keys of message as specified by kwarg_transformers and return
    a new message where keys are transformed.
    """
    assert isinstance(message, dict)
    new_message = dict(message)
    for k, v in kwarg_transformers.items():
        new_message[k] = v(message[k])
    return new_message


def _make_response_map_for_root_object(root_object):
    """
    This is intended to be used with map_aiter. It takes a message, parses it,
    invokes "do_XXX" on the given API, then packs up the response and sends it
    back to the remote.
    """

    async def responses_for_message(message):
        try:
            # {"c": "command"}
            c = message.get("c")
            nonce = message.get("n")
            f = getattr(root_object, c, None)
            if not f:
                d = dict(e="Missing or invalid command: %s" % c)
                log.error("failure in %s message" % c)
                return
        except Exception as ex:
            log.exception("failure in %s message" % c)
            d = dict(e="exception: %s" % ex)

        args = message.get("q", {})
        try:
            log.debug("handling %s message" % c)
            async for r in f(**args):
                if nonce is not None:
                    d = dict(r=r)
                    d["n"] = nonce
                    yield d
            log.debug("handling %s message complete" % c)
        except Exception as ex:
            log.exception("failure in %s message" % c)
            d = dict(e="exception: %s" % ex)

    async def response_writer_for_event(event):
        message = event["message"]
        async for response in responses_for_message(message):
            yield response, event["writer"]

    return response_writer_for_event


def api_request(**kwarg_transformers):
    """
    This decorator will transform the arguments for the given keywords by the corresponding
    function.

    @api_request(block=Block.from_bytes)
    def accept_block(block):
        # do some stuff with block as Block rather than bytes
    """
    def inner(f):
        @functools.wraps(f)
        def f_substitute(*args, **message):
            return f(*args, **_transform_args(kwarg_transformers, message))
        return f_substitute
    return inner


async def api_server(rws_aiter, root_object, worker_count=1):
    """
    An rws_aiter is an aiter which streams a (StreamReader, StreamWriter) tuples.
    For a given rws_aiter, create a task which fetches messages from the StreamReader, parses them,
    and turns them into api calls on api.

    You can wait forever on this task. If you close the socket, once all connected clients drop off, the
    task will complete.
    """
    event_aiter = rws_to_event_aiter(rws_aiter, reader_to_cbor_stream)

    response_writer_for_event = _make_response_map_for_root_object(root_object)

    response_writer_aiter = map_aiter(response_writer_for_event, event_aiter, worker_count=worker_count)

    def to_cbor(response_writer_pair):
        response, writer = response_writer_pair
        try:
            msg = xform_to_cbor_message(response)
        except Exception as ex:
            msg = xform_to_cbor_message("problem streaming message: %s" % ex)
        return msg, writer

    cbor_msg_aiter = map_aiter(to_cbor, join_aiters(response_writer_aiter))

    async for cbor_msg, writer in cbor_msg_aiter:
        writer.write(cbor_msg)


"""
Copyright 2019 Chia Network Inc

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
