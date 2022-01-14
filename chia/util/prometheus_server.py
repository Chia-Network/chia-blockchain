from contextlib import contextmanager
from dataclasses import dataclass
import logging
import traceback
from typing import Tuple
from prometheus_client import start_http_server, Counter, Gauge


@dataclass
class PrometheusServer:
    """
    PrometheusServer wraps functionality from prometheus-client to ensure consistent usage for all metrics exported by
    chia-blockchain

    This class and its helper methods should be used rather than calling methods in prometheus-client directly to ensure
    metric names are consistently prefixed with the chia namespace and the proper subsystem.

    Parameters
    ----------
    service_name : str
        The name of the service to export metrics for (full_node, wallet, etc)
    server_enabled : bool
        Set to true to start the prometheus metrics server
    server_port: int
        The port number to use for the prometheus http server
    log: logging.Logger
        An instance of logging.Logger to use for logging within PrometheusServer
    """

    service_name: str
    server_enabled: bool
    server_port: int
    log: logging.Logger
    _started: bool

    @classmethod
    def create(cls, service_name: str, server_enabled: bool, server_port: int, log: logging.Logger):
        return cls(
            service_name=service_name, server_enabled=server_enabled, server_port=server_port, log=log, _started=False
        )

    async def start_if_enabled(self):
        # Start prometheus exporter server for the full node
        if self.server_enabled and not self._started:
            self.log.info(f"Starting full_node prometheus server on port {self.server_port}")
            start_http_server(self.server_port)
            self._started = True

    def new_gauge(self, name: str, description: str, labelnames: Tuple = ()) -> Gauge:
        """
        Returns a new prometheus Gauge with proper namespace and subsystem values set for consistent metric names

        This method should be used rather than creating a new Gauge directly to ensure consistency in exported metric
        names
        """
        with self.log_errors():
            return Gauge(name, description, labelnames, "chia", self.service_name)

    def new_counter(self, name: str, description: str, labelnames: Tuple = ()) -> Counter:
        """
        Returns a new prometheus Counter with proper namespace and subsystem values set for consistent metric names

        This method should be used rather than creating a new Counter directly to ensure consistency in exported metric
        names
        """
        with self.log_errors():
            return Counter(name, description, labelnames, "chia", self.service_name)

    @contextmanager
    def log_errors(self):
        try:
            yield
        except Exception as e:
            self.log.error(f"Prometheus Metrics Exception: {e}. Traceback: {traceback.format_exc()}")
