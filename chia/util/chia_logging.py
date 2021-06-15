import logging
from pathlib import Path
from typing import Dict

import colorlog
from concurrent_log_handler import ConcurrentRotatingFileHandler
from logging.handlers import SysLogHandler

from chia.util.path import mkdir, path_from_root


def initialize_logging(service_name: str, logging_config: Dict, root_path: Path):
    log_path = path_from_root(root_path, logging_config.get("log_filename", "log/debug.log"))
    log_date_format = "%Y-%m-%dT%H:%M:%S"

    mkdir(str(log_path.parent))
    file_name_length = 33 - len(service_name)
    if logging_config["log_stdout"]:
        handler = colorlog.StreamHandler()
        handler.setFormatter(
            colorlog.ColoredFormatter(
                f"%(asctime)s.%(msecs)03d {service_name} %(name)-{file_name_length}s: "
                f"%(log_color)s%(levelname)-8s%(reset)s %(message)s",
                datefmt=log_date_format,
                reset=True,
            )
        )

        logger = colorlog.getLogger()
        logger.addHandler(handler)
    else:
        logger = logging.getLogger()
        maxrotation = logging_config.get("log_maxfilesrotation", 7)
        handler = ConcurrentRotatingFileHandler(log_path, "a", maxBytes=20 * 1024 * 1024, backupCount=maxrotation)
        handler.setFormatter(
            logging.Formatter(
                fmt=f"%(asctime)s.%(msecs)03d {service_name} %(name)-{file_name_length}s: %(levelname)-8s %(message)s",
                datefmt=log_date_format,
            )
        )
        logger.addHandler(handler)

    if logging_config.get("log_syslog", False):
        log_syslog_host = logging_config.get("log_syslog_host", "localhost")
        log_syslog_port = logging_config.get("log_syslog_port", 514)
        log_syslog_handler = SysLogHandler(address=(log_syslog_host, log_syslog_port))
        log_syslog_handler.setFormatter(logging.Formatter(fmt=f"{service_name} %(message)s", datefmt=log_date_format))
        logger = logging.getLogger()
        logger.addHandler(log_syslog_handler)

    if "log_level" in logging_config:
        if logging_config["log_level"] == "CRITICAL":
            logger.setLevel(logging.CRITICAL)
        elif logging_config["log_level"] == "ERROR":
            logger.setLevel(logging.ERROR)
        elif logging_config["log_level"] == "WARNING":
            logger.setLevel(logging.WARNING)
        elif logging_config["log_level"] == "INFO":
            logger.setLevel(logging.INFO)
        elif logging_config["log_level"] == "DEBUG":
            logger.setLevel(logging.DEBUG)
            logging.getLogger("aiosqlite").setLevel(logging.INFO)  # Too much logging on debug level
            logging.getLogger("websockets").setLevel(logging.INFO)  # Too much logging on debug level
        else:
            logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.INFO)
