import asyncio
import pytest
import time
import math
import aiosqlite
from src.types.peer_info import PeerInfo, TimestampedPeerInfo
from src.server.address_manager import ExtendedPeerInfo, AddressManager
from src.server.address_manager_store import AddressManagerStore
from pathlib import Path


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class AddressManagerTest(AddressManager):
    def __init__(self, make_deterministic=True):
        super().__init__()
        if make_deterministic:
            self.make_deterministic()
        self.make_private_subnets_valid()

    def make_deterministic(self):
        # Fix seed.
        self.key = 2 ** 256 - 1

    async def simulate_connection_fail(self, peer):
        await self.mark_good(peer.peer_info, True, 1)
        await self.attempt(peer.peer_info, False, time.time() - 61)

    async def add_peer_info(self, peers, peer_src=None):
        timestamped_peers = [
            TimestampedPeerInfo(
                peer.host,
                peer.port,
                0,
            )
            for peer in peers
        ]
        added = await self.add_to_new_table(timestamped_peers, peer_src)
        return added


class TestPeerManager:
    @pytest.mark.asyncio
    async def test_addr_manager(self):
        addrman = AddressManagerTest()
        # Test: Does Addrman respond correctly when empty.
        none_peer = await addrman.select_peer()
        assert none_peer is None
        assert await addrman.size() == 0
        # Test: Does Add work as expected.
        peer1 = PeerInfo("250.1.1.1", 8444)
        assert await addrman.add_peer_info([peer1])
        assert await addrman.size() == 1
        peer1_ret = await addrman.select_peer()
        assert peer1_ret.peer_info == peer1

        # Test: Does IP address deduplication work correctly.
        peer1_duplicate = PeerInfo("250.1.1.1", 8444)
        assert not await addrman.add_peer_info([peer1_duplicate])
        assert await addrman.size() == 1

        # Test: New table has one addr and we add a diff addr we should
        # have at least one addr.
        # Note that addrman's size cannot be tested reliably after insertion, as
        # hash collisions may occur. But we can always be sure of at least one
        # success.

        peer2 = PeerInfo("250.1.1.2", 8444)
        assert await addrman.add_peer_info([peer2])
        assert await addrman.size() >= 1

        # Test: AddrMan::Add multiple addresses works as expected
        addrman2 = AddressManagerTest()
        peers = [peer1, peer2]
        assert await addrman2.add_peer_info(peers)
        assert await addrman2.size() >= 1

    @pytest.mark.asyncio
    async def test_addr_manager_ports(self):
        addrman = AddressManagerTest()
        assert await addrman.size() == 0
        source = PeerInfo("252.2.2.2", 8444)

        # Test: Addr with same IP but diff port does not replace existing addr.
        peer1 = PeerInfo("250.1.1.1", 8444)
        assert await addrman.add_peer_info([peer1], source)
        assert await addrman.size() == 1

        peer2 = PeerInfo("250.1.1.1", 8445)
        assert not await addrman.add_peer_info([peer2], source)
        assert await addrman.size() == 1
        peer3 = await addrman.select_peer()
        assert peer3.peer_info == peer1

        # Test: Add same IP but diff port to tried table, it doesn't get added.
        # Perhaps this is not ideal behavior but it is the current behavior.
        await addrman.mark_good(peer2)
        assert await addrman.size() == 1
        peer3_ret = await addrman.select_peer(True)
        assert peer3_ret.peer_info == peer1

    # This is a fleaky test, since it uses randomness.
    # TODO: Make sure it always succeeds.
    @pytest.mark.asyncio
    async def test_addrman_select(self):
        addrman = AddressManagerTest()
        source = PeerInfo("252.2.2.2", 8444)

        # Test: Select from new with 1 addr in new.
        peer1 = PeerInfo("250.1.1.1", 8444)
        assert await addrman.add_peer_info([peer1], source)
        assert await addrman.size() == 1

        peer1_ret = await addrman.select_peer(True)
        assert peer1_ret.peer_info == peer1

        # Test: move addr to tried, select from new expected nothing returned.
        await addrman.mark_good(peer1)
        assert await addrman.size() == 1

        peer2_ret = await addrman.select_peer(True)
        assert peer2_ret is None
        peer3_ret = await addrman.select_peer()
        assert peer3_ret.peer_info == peer1

        # Add three addresses to new table.
        peer2 = PeerInfo("250.3.1.1", 8444)
        peer3 = PeerInfo("250.3.2.2", 9999)
        peer4 = PeerInfo("250.3.3.3", 9999)

        assert await addrman.add_peer_info([peer2], PeerInfo("250.3.1.1", 8444))
        assert await addrman.add_peer_info([peer3], PeerInfo("250.3.1.1", 8444))
        assert await addrman.add_peer_info([peer4], PeerInfo("250.4.1.1", 8444))

        # Add three addresses to tried table.
        peer5 = PeerInfo("250.4.4.4", 8444)
        peer6 = PeerInfo("250.4.5.5", 7777)
        peer7 = PeerInfo("250.4.6.6", 8444)

        assert await addrman.add_peer_info([peer5], PeerInfo("250.3.1.1", 8444))
        await addrman.mark_good(peer5)
        assert await addrman.add_peer_info([peer6], PeerInfo("250.3.1.1", 8444))
        await addrman.mark_good(peer6)
        assert await addrman.add_peer_info([peer7], PeerInfo("250.1.1.3", 8444))
        await addrman.mark_good(peer7)

        # Test: 6 addrs + 1 addr from last test = 7.
        assert await addrman.size() == 7

        # Test: Select pulls from new and tried regardless of port number.
        ports = []
        for _ in range(200):
            peer = await addrman.select_peer()
            if peer.peer_info.port not in ports:
                ports.append(peer.peer_info.port)
            if len(ports) == 3:
                break
        assert len(ports) == 3

    @pytest.mark.asyncio
    async def test_addrman_collisions_new(self):
        addrman = AddressManagerTest()
        assert await addrman.size() == 0
        source = PeerInfo("252.2.2.2", 8444)

        for i in range(1, 8):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            assert await addrman.add_peer_info([peer], source)
            assert await addrman.size() == i

        # Test: new table collision!
        peer1 = PeerInfo("250.1.1.8", 8444)
        assert await addrman.add_peer_info([peer1], source)
        assert await addrman.size() == 7

        peer2 = PeerInfo("250.1.1.9", 8444)
        assert await addrman.add_peer_info([peer2], source)
        assert await addrman.size() == 8

    @pytest.mark.asyncio
    async def test_addrman_collisions_tried(self):
        addrman = AddressManagerTest()
        assert await addrman.size() == 0
        source = PeerInfo("252.2.2.2", 8444)

        for i in range(1, 77):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            assert await addrman.add_peer_info([peer], source)
            await addrman.mark_good(peer)
            # Test: No collision in tried table yet.
            assert await addrman.size() == i

        # Test: tried table collision!
        peer1 = PeerInfo("250.1.1.77", 8444)
        assert await addrman.add_peer_info([peer1], source)
        assert await addrman.size() == 76

        peer2 = PeerInfo("250.1.1.78", 8444)
        assert await addrman.add_peer_info([peer2], source)
        assert await addrman.size() == 77

    @pytest.mark.asyncio
    async def test_addrman_find(self):
        addrman = AddressManagerTest()
        assert await addrman.size() == 0

        peer1 = PeerInfo("250.1.2.1", 8333)
        peer2 = PeerInfo("250.1.2.1", 9999)
        peer3 = PeerInfo("251.255.2.1", 8333)

        source1 = PeerInfo("250.1.2.1", 8444)
        source2 = PeerInfo("250.1.2.2", 8444)

        assert await addrman.add_peer_info([peer1], source1)
        assert not await addrman.add_peer_info([peer2], source2)
        assert await addrman.add_peer_info([peer3], source1)

        # Test: ensure Find returns an IP matching what we searched on.
        info1 = addrman.find_(peer1)
        assert info1[0] is not None and info1[1] is not None
        assert info1[0].peer_info == peer1

        # Test: Find does not discriminate by port number.
        info2 = addrman.find_(peer2)
        assert info2[0] is not None and info2[1] is not None
        assert info2 == info1

        # Test: Find returns another IP matching what we searched on.
        info3 = addrman.find_(peer3)
        assert info3[0] is not None and info3[1] is not None
        assert info3[0].peer_info == peer3

    @pytest.mark.asyncio
    async def test_addrman_create(self):
        addrman = AddressManagerTest()
        assert await addrman.size() == 0

        peer1 = PeerInfo("250.1.2.1", 8444)
        t_peer = TimestampedPeerInfo("250.1.2.1", 8444, 0)
        info, node_id = addrman.create_(t_peer, peer1)
        assert info.peer_info == peer1
        info, _ = addrman.find_(peer1)
        assert info.peer_info == peer1

    @pytest.mark.asyncio
    async def test_addrman_delete(self):
        addrman = AddressManagerTest()
        assert await addrman.size() == 0

        peer1 = PeerInfo("250.1.2.1", 8444)
        t_peer = TimestampedPeerInfo("250.1.2.1", 8444, 0)
        info, node_id = addrman.create_(t_peer, peer1)

        # Test: Delete should actually delete the addr.
        assert await addrman.size() == 1
        addrman.delete_new_entry_(node_id)
        assert await addrman.size() == 0
        info2, _ = addrman.find_(peer1)
        assert info2 is None

    @pytest.mark.asyncio
    async def test_addrman_get_peers(self):
        addrman = AddressManagerTest()
        assert await addrman.size() == 0
        peers1 = await addrman.get_peers()
        assert len(peers1) == 0

        peer1 = TimestampedPeerInfo("250.250.2.1", 8444, time.time())
        peer2 = TimestampedPeerInfo("250.250.2.2", 9999, time.time())
        peer3 = TimestampedPeerInfo("251.252.2.3", 8444, time.time())
        peer4 = TimestampedPeerInfo("251.252.2.4", 8444, time.time())
        peer5 = TimestampedPeerInfo("251.252.2.5", 8444, time.time())
        source1 = PeerInfo("250.1.2.1", 8444)
        source2 = PeerInfo("250.2.3.3", 8444)

        # Test: Ensure GetPeers works with new addresses.
        assert await addrman.add_to_new_table([peer1], source1)
        assert await addrman.add_to_new_table([peer2], source2)
        assert await addrman.add_to_new_table([peer3], source1)
        assert await addrman.add_to_new_table([peer4], source1)
        assert await addrman.add_to_new_table([peer5], source1)

        # GetPeers returns 23% of addresses, 23% of 5 is 2 rounded up.
        peers2 = await addrman.get_peers()
        assert len(peers2) == 2

        # Test: Ensure GetPeers works with new and tried addresses.
        await addrman.mark_good(PeerInfo(peer1.host, peer1.port))
        await addrman.mark_good(PeerInfo(peer2.host, peer2.port))
        peers3 = await addrman.get_peers()
        assert len(peers3) == 2

        # Test: Ensure GetPeers still returns 23% when addrman has many addrs.
        for i in range(1, 8 * 256):
            octet1 = i % 256
            octet2 = i >> 8 % 256
            peer = TimestampedPeerInfo(str(octet1) + "." + str(octet2) + ".1.23", 8444, time.time())
            await addrman.add_to_new_table([peer])
            if i % 8 == 0:
                await addrman.mark_good(PeerInfo(peer.host, peer.port))

        peers4 = await addrman.get_peers()
        percent = await addrman.size()
        percent = math.ceil(percent * 23 / 100)
        assert len(peers4) == percent

    @pytest.mark.asyncio
    async def test_addrman_tried_bucket(self):
        peer1 = PeerInfo("250.1.1.1", 8444)
        t_peer1 = TimestampedPeerInfo("250.1.1.1", 8444, 0)
        peer2 = PeerInfo("250.1.1.1", 9999)
        t_peer2 = TimestampedPeerInfo("250.1.1.1", 9999, 0)
        source1 = PeerInfo("250.1.1.1", 8444)
        peer_info1 = ExtendedPeerInfo(t_peer1, source1)
        # Test: Make sure key actually randomizes bucket placement. A fail on
        # this test could be a security issue.
        key1 = 2 ** 256 - 1
        key2 = 2 ** 128 - 1
        bucket1 = peer_info1.get_tried_bucket(key1)
        bucket2 = peer_info1.get_tried_bucket(key2)
        assert bucket1 != bucket2

        # Test: Two addresses with same IP but different ports can map to
        # different buckets because they have different keys.
        peer_info2 = ExtendedPeerInfo(t_peer2, source1)
        assert peer1.get_key() != peer2.get_key()
        assert peer_info1.get_tried_bucket(key1) != peer_info2.get_tried_bucket(key1)

        # Test: IP addresses in the same group (\16 prefix for IPv4) should
        # never get more than 8 buckets
        buckets = []
        for i in range(255):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            t_peer = TimestampedPeerInfo("250.1.1." + str(i), 8444, 0)
            extended_peer_info = ExtendedPeerInfo(t_peer, peer)
            bucket = extended_peer_info.get_tried_bucket(key1)
            if bucket not in buckets:
                buckets.append(bucket)

        assert len(buckets) == 8

        # Test: IP addresses in the different groups should map to more than
        # 8 buckets.
        buckets = []
        for i in range(255):
            peer = PeerInfo("250." + str(i) + ".1.1", 8444)
            t_peer = TimestampedPeerInfo("250." + str(i) + ".1.1", 8444, 0)
            extended_peer_info = ExtendedPeerInfo(t_peer, peer)
            bucket = extended_peer_info.get_tried_bucket(key1)
            if bucket not in buckets:
                buckets.append(bucket)
        assert len(buckets) > 8

    @pytest.mark.asyncio
    async def test_addrman_new_bucket(self):
        t_peer1 = TimestampedPeerInfo("250.1.2.1", 8444, 0)
        source1 = PeerInfo("250.1.2.1", 8444)
        t_peer2 = TimestampedPeerInfo("250.1.2.1", 9999, 0)
        peer_info1 = ExtendedPeerInfo(t_peer1, source1)
        # Test: Make sure key actually randomizes bucket placement. A fail on
        # this test could be a security issue.
        key1 = 2 ** 256 - 1
        key2 = 2 ** 128 - 1
        bucket1 = peer_info1.get_new_bucket(key1)
        bucket2 = peer_info1.get_new_bucket(key2)
        assert bucket1 != bucket2

        # Test: Ports should not affect bucket placement in the addr
        peer_info2 = ExtendedPeerInfo(t_peer2, source1)
        assert peer_info1.get_new_bucket(key1) == peer_info2.get_new_bucket(key1)

        # Test: IP addresses in the same group (\16 prefix for IPv4) should
        # always map to the same bucket.
        buckets = []
        for i in range(255):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            t_peer = TimestampedPeerInfo("250.1.1." + str(i), 8444, 0)
            extended_peer_info = ExtendedPeerInfo(t_peer, peer)
            bucket = extended_peer_info.get_new_bucket(key1)
            if bucket not in buckets:
                buckets.append(bucket)
        assert len(buckets) == 1

        # Test: IP addresses in the same source groups should map to no more
        # than 64 buckets.
        buckets = []
        for i in range(4 * 255):
            src = PeerInfo("251.4.1.1", 8444)
            peer = PeerInfo(str(250 + i // 255) + "." + str(i % 256) + ".1.1", 8444)
            t_peer = TimestampedPeerInfo(str(250 + i // 255) + "." + str(i % 256) + ".1.1", 8444, 0)
            extended_peer_info = ExtendedPeerInfo(t_peer, src)
            bucket = extended_peer_info.get_new_bucket(key1)
            if bucket not in buckets:
                buckets.append(bucket)
        assert len(buckets) <= 64

        # Test: IP addresses in the different source groups should map to more
        # than 64 buckets.
        buckets = []
        for i in range(255):
            src = PeerInfo("250." + str(i) + ".1.1", 8444)
            peer = PeerInfo("250.1.1.1", 8444)
            t_peer = TimestampedPeerInfo("250.1.1.1", 8444, 0)
            extended_peer_info = ExtendedPeerInfo(t_peer, src)
            bucket = extended_peer_info.get_new_bucket(key1)
            if bucket not in buckets:
                buckets.append(bucket)

        assert len(buckets) > 64

    @pytest.mark.asyncio
    async def test_addrman_select_collision_no_collision(self):
        addrman = AddressManagerTest()
        collision = await addrman.select_tried_collision()
        assert collision is None

        # Add 17 addresses.
        source = PeerInfo("252.2.2.2", 8444)
        for i in range(1, 18):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            assert await addrman.add_peer_info([peer], source)
            await addrman.mark_good(peer)

            # No collisions yet.
            assert await addrman.size() == i
            collision = await addrman.select_tried_collision()
            assert collision is None

        # Ensure Good handles duplicates well.
        for i in range(1, 18):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            await addrman.mark_good(peer)
            assert await addrman.size() == 17
            collision = await addrman.select_tried_collision()
            assert collision is None

    @pytest.mark.asyncio
    async def test_addrman_no_evict(self):
        addrman = AddressManagerTest()

        # Add 17 addresses.
        source = PeerInfo("252.2.2.2", 8444)
        for i in range(1, 18):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            assert await addrman.add_peer_info([peer], source)
            await addrman.mark_good(peer)
            # No collision yet.
            assert await addrman.size() == i
            collision = await addrman.select_tried_collision()
            assert collision is None

        peer18 = PeerInfo("250.1.1.18", 8444)
        assert await addrman.add_peer_info([peer18], source)
        await addrman.mark_good(peer18)
        assert await addrman.size() == 18
        collision = await addrman.select_tried_collision()
        assert collision.peer_info == PeerInfo("250.1.1.16", 8444)
        await addrman.resolve_tried_collisions()
        collision = await addrman.select_tried_collision()
        assert collision is None

        # Lets create two collisions.
        for i in range(19, 37):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            assert await addrman.add_peer_info([peer], source)
            await addrman.mark_good(peer)
            assert await addrman.size() == i
            assert await addrman.select_tried_collision() is None

        # Cause a collision.
        peer37 = PeerInfo("250.1.1.37", 8444)
        assert await addrman.add_peer_info([peer37], source)
        await addrman.mark_good(peer37)
        assert await addrman.size() == 37

        # Cause a second collision.
        assert not await addrman.add_peer_info([peer18], source)
        await addrman.mark_good(peer18)
        assert await addrman.size() == 37

        collision = await addrman.select_tried_collision()
        assert collision is not None
        await addrman.resolve_tried_collisions()
        collision = await addrman.select_tried_collision()
        assert collision is None

    @pytest.mark.asyncio
    async def test_addrman_eviction_works(self):
        addrman = AddressManagerTest()
        assert await addrman.size() == 0
        # Empty addrman should return blank addrman info.
        assert await addrman.select_tried_collision() is None

        # Add twenty two addresses.
        source = PeerInfo("252.2.2.2", 8444)
        for i in range(1, 18):
            peer = PeerInfo("250.1.1." + str(i), 8444)
            assert await addrman.add_peer_info([peer], source)
            await addrman.mark_good(peer)
            # No collision yet.
            assert await addrman.size() == i
            assert await addrman.select_tried_collision() is None

        # Collision between 18 and 16.
        peer18 = PeerInfo("250.1.1.18", 8444)
        assert await addrman.add_peer_info([peer18], source)
        await addrman.mark_good(peer18)
        assert await addrman.size() == 18
        collision = await addrman.select_tried_collision()
        assert collision.peer_info == PeerInfo("250.1.1.16", 8444)
        await addrman.simulate_connection_fail(collision)
        # Should swap 18 for 16.
        await addrman.resolve_tried_collisions()
        assert await addrman.select_tried_collision() is None

        # If 18 was swapped for 16, then this should cause no collisions.
        assert not await addrman.add_peer_info([peer18], source)
        await addrman.mark_good(peer18)
        assert await addrman.select_tried_collision() is None

        # If we insert 16 is should collide with 18.
        addr16 = PeerInfo("250.1.1.16", 8444)
        assert not await addrman.add_peer_info([addr16], source)
        await addrman.mark_good(addr16)
        collision = await addrman.select_tried_collision()
        assert collision.peer_info == PeerInfo("250.1.1.18", 8444)
        await addrman.resolve_tried_collisions()
        assert await addrman.select_tried_collision() is None

    @pytest.mark.asyncio
    async def test_serialization(self):
        addrman = AddressManagerTest()
        now = int(math.floor(time.time()))
        t_peer1 = TimestampedPeerInfo("250.7.1.1", 8333, now - 10000)
        t_peer2 = TimestampedPeerInfo("250.7.2.2", 9999, now - 20000)
        t_peer3 = TimestampedPeerInfo("250.7.3.3", 9999, now - 30000)
        source = PeerInfo("252.5.1.1", 8333)
        await addrman.add_to_new_table([t_peer1, t_peer2, t_peer3], source)
        await addrman.mark_good(PeerInfo("250.7.1.1", 8333))

        db_filename = Path("peer_table.db")
        if db_filename.exists():
            db_filename.unlink()
        connection = await aiosqlite.connect(db_filename)
        address_manager_store = await AddressManagerStore.create(connection)
        await address_manager_store.serialize(addrman)
        addrman2 = await address_manager_store.deserialize()

        retrieved_peers = []
        for _ in range(50):
            peer = await addrman2.select_peer()
            if peer not in retrieved_peers:
                retrieved_peers.append(peer)
            if len(retrieved_peers) == 3:
                break
        assert len(retrieved_peers) == 3
        wanted_peers = [
            ExtendedPeerInfo(t_peer1, source),
            ExtendedPeerInfo(t_peer2, source),
            ExtendedPeerInfo(t_peer3, source),
        ]
        recovered = 0
        for target_peer in wanted_peers:
            for current_peer in retrieved_peers:
                if (
                    current_peer.peer_info == target_peer.peer_info
                    and current_peer.src == target_peer.src
                    and current_peer.timestamp == target_peer.timestamp
                ):
                    recovered += 1
        assert recovered == 3
        await connection.close()
        db_filename.unlink()

    @pytest.mark.asyncio
    async def test_cleanup(self):
        addrman = AddressManagerTest()
        peer1 = TimestampedPeerInfo("250.250.2.1", 8444, 100000)
        peer2 = TimestampedPeerInfo("250.250.2.2", 9999, time.time())
        source = PeerInfo("252.5.1.1", 8333)
        assert await addrman.add_to_new_table([peer1], source)
        assert await addrman.add_to_new_table([peer2], source)
        await addrman.mark_good(PeerInfo("250.250.2.2", 9999))
        assert await addrman.size() == 2
        for _ in range(5):
            await addrman.attempt(peer1, True, time.time() - 61)
        addrman.cleanup(7 * 3600 * 24, 5)
        assert await addrman.size() == 1
