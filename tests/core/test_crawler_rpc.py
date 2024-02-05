from __future__ import annotations

import pytest

from chia.rpc.crawler_rpc_api import CrawlerRpcApi
from chia.seeder.crawler import Crawler


@pytest.mark.anyio
async def test_get_ips_after_timestamp(bt):
    crawler = Crawler(bt.config.get("seeder", {}), bt.root_path, constants=bt.constants)
    crawler_rpc_api = CrawlerRpcApi(crawler)

    # Should raise ValueError when `after` is not supplied
    with pytest.raises(ValueError):
        await crawler_rpc_api.get_ips_after_timestamp({})

    # Crawler isn't actually crawling, so this should return zero IPs
    response = await crawler_rpc_api.get_ips_after_timestamp({"after": 0})
    assert len(response["ips"]) == 0

    # Add some known data
    # IPs are listed here out of order (by time) to test consistent sorting
    # Timestamps increase as the IP value increases
    crawler.best_timestamp_per_peer["0.0.0.0"] = 0
    crawler.best_timestamp_per_peer["2.2.2.2"] = 1644300000
    crawler.best_timestamp_per_peer["1.1.1.1"] = 1644213600
    crawler.best_timestamp_per_peer["7.7.7.7"] = 1644732000
    crawler.best_timestamp_per_peer["3.3.3.3"] = 1644386400
    crawler.best_timestamp_per_peer["4.4.4.4"] = 1644472800
    crawler.best_timestamp_per_peer["9.9.9.9"] = 1644904800
    crawler.best_timestamp_per_peer["5.5.5.5"] = 1644559200
    crawler.best_timestamp_per_peer["6.6.6.6"] = 1644645600
    crawler.best_timestamp_per_peer["8.8.8.8"] = 1644818400

    response = await crawler_rpc_api.get_ips_after_timestamp({"after": 0})
    assert len(response["ips"]) == 9

    response = await crawler_rpc_api.get_ips_after_timestamp({"after": 1644473000})
    assert len(response["ips"]) == 5

    # Test offset/limit functionality
    response = await crawler_rpc_api.get_ips_after_timestamp({"after": 0, "limit": 2})
    assert len(response["ips"]) == 2
    assert response["total"] == 9
    assert response["ips"][0] == "1.1.1.1"
    assert response["ips"][1] == "2.2.2.2"

    response = await crawler_rpc_api.get_ips_after_timestamp({"after": 0, "offset": 2, "limit": 2})
    assert len(response["ips"]) == 2
    assert response["total"] == 9
    assert response["ips"][0] == "3.3.3.3"
    assert response["ips"][1] == "4.4.4.4"
