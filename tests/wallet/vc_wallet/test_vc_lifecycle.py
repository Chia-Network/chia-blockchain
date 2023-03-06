import pytest

from chia.clvm.spend_sim import sim_and_client


# NEED FAKE SINGLETON FOR TESTING


@pytest.mark.asyncio
async def test_covenant_layer() -> None:
    async with sim_and_client() as (sim, client):
        pass


@pytest.mark.asyncio
async def test_did_tp() -> None:
    async with sim_and_client() as (sim, client):
        pass


@pytest.mark.asyncio
async def test_did_backdoor() -> None:
    async with sim_and_client() as (sim, client):
        pass


@pytest.mark.asyncio
async def test_p2_puzzle_or_hidden_puzzle() -> None:
    async with sim_and_client() as (sim, client):
        pass


@pytest.mark.asyncio
async def test_vc_lifecycle() -> None:
    async with sim_and_client() as (sim, client):
        pass
