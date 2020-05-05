import asyncio
import concurrent
import logging
import secrets

from aiter import map_aiter, join_aiters, server

from src.server.connection import Connection
from src.server.outbound_message import Message
from src.util.config import load_config
from src.util.logging import initialize_logging

from .start_stop import start_service


log = logging.getLogger(__name__)


def socket_server_path(root_path):
    return root_path / "run" / "start-daemon.socket"


def socket_server_info_path(root_path):
    return root_path / "run" / "start-daemon.socket.info"


async def server_aiter_for_start_daemon(root_path):
    try:
        raise ValueError()
        socket_path = socket_server_path(root_path)
        s, aiter = await server.start_unix_server_aiter(path=socket_path)
        log.info("listening on %s", socket_path)
        return s, aiter
    except Exception as ex:
        pass

    try:
        # TODO: make this configurable
        socket_server_port = 62191
        s, aiter = await server.start_server_aiter(port=socket_server_port)
        log.info("listening on port %s", socket_server_port)
        return s, aiter
    except Exception as ex:
        pass
    return None


def launch_task(root_path, service):
    try:
        process, pid_path = start_service(root_path, service)
        r = process.wait()
    except (Exception, KeyboardInterrupt) as ex:
        log.exception("launch task %s", service)
        kill_and_wait(process)
    except:
        print("oh boy")
        breakpoint()
    return r


async def kill_and_wait(process, max_nice_wait=30):
    process.terminate()
    log.info("sending term signal to %s", process)
    count = 0
    while count < max_nice_wait:
        if process.poll() is not None:
            break
        await asyncio.sleep(1)
        count += 1
    else:
        process.kill()
        log.info("sending kill signal to %s", process)
    r = process.wait()
    log.info("process %s returned %d", process, r)
    return r


async def run_start_server(root_path):
    config = load_config(root_path, "config.yaml")

    initialize_logging("daemon %(name)-25s", config["logging"], root_path)

    listen_socket, aiter = await server_aiter_for_start_daemon(root_path)

    secret_expected = "hello"

    services = {}

    async def next_message(connection):
        sr = connection.reader
        line = await sr.readline()  # connection.read_one_message()
        p0, p1 = line.split()[:2]
        message = Message(p0.decode(), p1.decode())
        log.info("got message %s", message)
        return message

    async def stream_reader_writer_to_message_stream(pair):
        sr, sw = pair
        connection = Connection(None, sr, sw, 0, None)
        log.info("connection from %s", connection)
        try:
            message = await next_message(connection)
            # this must be an authentication message
            if message.function != "auth" or message.data != secret_expected:
                log.info("auth failed, disconnecting %s", connection)
                return
            did_auth = Message("did_auth", 0)
            await send_message(did_auth, connection)
            while True:
                message = await next_message(connection)
                yield message, server, connection
        except Exception:
            pass
        finally:
            sw.close()

    event_aiter = join_aiters(map_aiter(stream_reader_writer_to_message_stream, aiter))

    async def do_start(service):
        if service in services:
            return Message("already_running", service)
        loop = asyncio.get_event_loop()
        process, pid_path = start_service(root_path, service)
        services[service] = process
        return Message("did_start", service)

    async def do_stop(service):
        process = services.get(service)
        if process is None:
            return Message("not_running", service)
        del services[service]
        r = await kill_and_wait(process)

        msg = "is_stopped"
        return Message(msg, service)

    try:
        async for message, server_1, connection in event_aiter:
            if message.function == "start":
                r = await do_start(message.data)
                await send_message(r, connection)
            if message.function == "stop":
                r = await do_stop(message.data)
                await send_message(r, connection)
            if message.function == "close":
                listen_socket.close()
                r = Message("closed", "listen_socket")
                await send_message(r, connection)
    finally:
        breakpoint()
        jobs = []
        for k in services.keys():
            log.info("killing %s", k)
            jobs.append(do_stop(k))
        if jobs:
            done, pending = await asyncio.wait(jobs)
            log.info("all killed")

    log.info("daemon exiting")


async def send_message(message, connection):
    try:
        log.info("sending message %s", message)
        await connection.send(message)
    except (RuntimeError, TimeoutError, OSError,) as e:
        connection.close()


def main():
    from src.util.default_root import DEFAULT_ROOT_PATH
    return asyncio.get_event_loop().run_until_complete(run_start_server(DEFAULT_ROOT_PATH))


if __name__ == "__main__":
    main()
