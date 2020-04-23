import os
import signal

from .start import pid_path_for_service, SERVICES_FOR_GROUP


def make_parser(parser):

    parser.add_argument(
        "group", choices=SERVICES_FOR_GROUP.keys(), type=str, nargs="+",
    )
    parser.set_defaults(function=stop)


def find_kill_signal():
    for signal_name in "SIGHUP CTRL_C_EVENT".split():
        try:
            return getattr(signal, signal_name)
        except AttributeError:
            pass
    raise RuntimeError("can't find a kill signal")


def stop(args, parser):
    kill_signal = find_kill_signal()

    return_val = 0

    for group in args.group:
        for service in SERVICES_FOR_GROUP[group]:
            if stop_service(args.root_path, service, kill_signal):
                return_val = 1

    return return_val


def stop_service(root_path, service, kill_signal):
    try:
        pid_path = pid_path_for_service(root_path, service)
        with open(pid_path) as f:
            pid = int(f.readline())
        print(f"sending signal to pid {pid:>5} for {service}")
        os.kill(pid, kill_signal)
    except Exception:
        print(f"can't open PID file {pid_path} for {service}, is it running?")
        return 1
    return 0
