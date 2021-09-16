#!/usr/bin/env python3
import logging


def pytest_configure(config):
    # Disable logging of the following modules to reduce log spam
    for logger in ["aiosqlite", "fsevents", "watchdog"]:
        logging.getLogger(logger).propagate = False
