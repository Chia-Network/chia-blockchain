from __future__ import annotations

import logging
from logging.handlers import SysLogHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

import colorlog
from concurrent_log_handler import ConcurrentRotatingFileHandler

from chia.cmds.init_funcs import chia_full_version_str
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root

default_log_level = "WARNING"


def get_beta_logging_config() -> Dict[str, Any]:
    return {
        "log_filename": f"{chia_full_version_str()}/chia-blockchain/beta.log",
        "log_level": "DEBUG",
        "log_stdout": False,
        "log_maxfilesrotation": 100,
        "log_maxbytesrotation": 100 * 1024 * 1024,
        "log_use_gzip": True,
    }


def get_file_log_handler(
    formatter: logging.Formatter, root_path: Path, logging_config: Dict[str, object]
) -> ConcurrentRotatingFileHandler:
    log_path = path_from_root(root_path, str(logging_config.get("log_filename", "log/debug.log")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    maxrotation = logging_config.get("log_maxfilesrotation", 7)
    maxbytesrotation = logging_config.get("log_maxbytesrotation", 50 * 1024 * 1024)
    use_gzip = logging_config.get("log_use_gzip", False)
    handler = ConcurrentRotatingFileHandler(
        log_path, "a", maxBytes=maxbytesrotation, backupCount=maxrotation, use_gzip=use_gzip
    )
    handler.setFormatter(formatter)
    return handler


def initialize_logging(service_name: str, logging_config: Dict, root_path: Path, beta_root_path: Optional[Path] = None):
    log_level = logging_config.get("log_level", default_log_level)
    file_name_length = 33 - len(service_name)
    log_date_format = "%Y-%m-%dT%H:%M:%S"
    file_log_formatter = logging.Formatter(
        fmt=f"%(asctime)s.%(msecs)03d {service_name} %(name)-{file_name_length}s: %(levelname)-8s %(message)s",
        datefmt=log_date_format,
    )
    handlers: List[logging.Handler] = []
    if logging_config["log_stdout"]:
        stdout_handler = colorlog.StreamHandler()
        stdout_handler.setFormatter(
            colorlog.ColoredFormatter(
                f"%(asctime)s.%(msecs)03d {service_name} %(name)-{file_name_length}s: "
                f"%(log_color)s%(levelname)-8s%(reset)s %(message)s",
                datefmt=log_date_format,
                reset=True,
            )
        )
        handlers.append(stdout_handler)
    else:
        handlers.append(get_file_log_handler(file_log_formatter, root_path, logging_config))

    if logging_config.get("log_syslog", False):
        log_syslog_host = logging_config.get("log_syslog_host", "localhost")
        log_syslog_port = logging_config.get("log_syslog_port", 514)
        log_syslog_handler = SysLogHandler(address=(log_syslog_host, log_syslog_port))
        log_syslog_handler.setFormatter(logging.Formatter(fmt=f"{service_name} %(message)s", datefmt=log_date_format))
        handlers.append(log_syslog_handler)

    if beta_root_path is not None:
        handlers.append(get_file_log_handler(file_log_formatter, beta_root_path, get_beta_logging_config()))

    root_logger = logging.getLogger()
    log_level_exceptions = {}
    for handler in handlers:
        try:
            handler.setLevel(log_level)
        except Exception as e:
            handler.setLevel(default_log_level)
            log_level_exceptions[handler] = e
        root_logger.addHandler(handler)

    for handler, exception in log_level_exceptions.items():
        root_logger.error(
            f"Handler {handler}: Invalid log level '{log_level}' found in {service_name} config. "
            f"Defaulting to: {default_log_level}. Error: {exception}"
        )

    # Adjust the root logger to the smallest used log level since its default level is WARNING which would overwrite
    # the potentially smaller log levels of specific handlers.
    root_logger.setLevel(min(handler.level for handler in handlers))

    if root_logger.level <= logging.DEBUG:
        logging.getLogger("aiosqlite").setLevel(logging.INFO)  # Too much logging on debug level


def initialize_service_logging(service_name: str, config: Dict[str, Any]) -> None:
    logging_root_path = DEFAULT_ROOT_PATH
    if service_name == "daemon":
        # TODO: Maybe introduce a separate `daemon` section in the config instead of having `daemon_port`, `logging`
        #  and the daemon related stuff as top level entries.
        logging_config = config["logging"]
    else:
        logging_config = config[service_name]["logging"]
    beta_config = config.get("beta", {})
    beta_config_path = beta_config.get("path") if beta_config.get("enabled", False) else None
    initialize_logging(
        service_name=service_name,
        logging_config=logging_config,
        root_path=logging_root_path,
        beta_root_path=beta_config_path,
    )
