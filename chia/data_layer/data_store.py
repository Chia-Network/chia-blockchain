import logging
import aiosqlite
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

from chia.data_layer.data_layer_errors import (
    InternalKeyValueError,
    InternalLeftRightNotBytes32Error,
    NodeHashError,
    TerminalLeftRightError,
    TreeGenerationIncrementingError,
)
from chia.data_layer.data_layer_types import (
    InternalNode,
    Node,
    NodeType,
    Root,
    ProofOfInclusion,
    ProofOfInclusionLayer,
    Side,
    TerminalNode,
    Status,
    InsertionData,
    DeletionData,
)
from chia.data_layer.data_layer_util import row_to_node
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper

log = logging.getLogger(__name__)


# TODO: review exceptions for values that shouldn't be displayed
# TODO: pick exception types other than Exception


@dataclass
class DataStore:
    """A key/value store with the pairs being terminal nodes in a CLVM object tree."""

    db: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper) -> "DataStore":
        self = cls(db=db_wrapper.db, db_wrapper=db_wrapper)
        self.db.row_factory = aiosqlite.Row

        await self.db.execute("pragma journal_mode=wal")
        # Setting to FULL despite other locations being configurable.  If there are
        # performance issues we can consider other the implications of other options.
        await self.db.execute("pragma synchronous=FULL")
        # If foreign key checking gets turned off, please add corresponding check
        # methods.
        await self.db.execute("PRAGMA foreign_keys=ON")

        async with self.db_wrapper.locked_transaction():
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS node(
                    hash TEXT PRIMARY KEY NOT NULL,
                    node_type INTEGER NOT NULL,
                    left TEXT REFERENCES node,
                    right TEXT REFERENCES node,
                    key TEXT,
                    value TEXT
                )
                """
            )
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS root(
                    tree_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    node_hash TEXT,
                    status INTEGER NOT NULL,
                    PRIMARY KEY(tree_id, generation),
                    FOREIGN KEY(node_hash) REFERENCES node(hash)
                )
                """
            )

        return self

    async def _insert_root(
        self, tree_id: bytes32, node_hash: Optional[bytes32], status: Status, generation: Optional[int] = None
    ) -> None:
        if generation is None:
            existing_generation = await self.get_tree_generation(tree_id=tree_id, lock=False)

            if existing_generation is None:
                generation = 0
            else:
                generation = existing_generation + 1

        await self.db.execute(
            """
            INSERT INTO root(tree_id, generation, node_hash, status) VALUES(:tree_id, :generation, :node_hash, :status)
            """,
            {
                "tree_id": tree_id.hex(),
                "generation": generation,
                "node_hash": None if node_hash is None else node_hash.hex(),
                "status": status.value,
            },
        )

    async def _insert_node(
        self,
        node_hash: str,
        node_type: NodeType,
        left_hash: Optional[str],
        right_hash: Optional[str],
        key: Optional[str],
        value: Optional[str],
        tree_id: str,
    ) -> None:
        # TODO: can we get sqlite to do this check?
        values = {
            "hash": node_hash,
            "node_type": node_type,
            "left": left_hash,
            "right": right_hash,
            "key": key,
            "value": value,
        }

        cursor = await self.db.execute("SELECT * FROM node WHERE hash == :hash", {"hash": node_hash})
        result = await cursor.fetchone()

        if result is None:
            await self.db.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                values,
            )
        else:
            result_dict = dict(result)
            if result_dict != values:
                raise Exception(f"Requested insertion of node with matching hash but other values differ: {node_hash}")

    async def _insert_internal_node(self, left_hash: bytes32, right_hash: bytes32, tree_id: bytes32) -> bytes32:
        node_hash = Program.to((left_hash, right_hash)).get_tree_hash(left_hash, right_hash)

        await self._insert_node(
            node_hash=node_hash.hex(),
            node_type=NodeType.INTERNAL,
            left_hash=left_hash.hex(),
            right_hash=right_hash.hex(),
            key=None,
            value=None,
            tree_id=tree_id.hex(),
        )

        return node_hash  # type: ignore[no-any-return]

    async def _insert_terminal_node(self, key: bytes, value: bytes, tree_id: bytes32) -> bytes32:
        node_hash = Program.to((key, value)).get_tree_hash()

        await self._insert_node(
            node_hash=node_hash.hex(),
            node_type=NodeType.TERMINAL,
            left_hash=None,
            right_hash=None,
            key=key.hex(),
            value=value.hex(),
            tree_id=tree_id.hex(),
        )

        return node_hash  # type: ignore[no-any-return]

    async def change_root_status(self, root: Root, status: Status = Status.PENDING) -> None:
        async with self.db_wrapper.locked_transaction(lock=True):
            await self.db.execute(
                "UPDATE root SET status = ? WHERE tree_id=? and generation = ?",
                (
                    status.value,
                    root.tree_id.hex(),
                    root.generation,
                ),
            )

    async def check(self) -> None:
        for check in self._checks:
            await check(self)

    async def _check_internal_key_value_are_null(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT * FROM node WHERE node_type == :node_type AND (key NOT NULL OR value NOT NULL)",
                {"node_type": NodeType.INTERNAL},
            )
            hashes = [bytes32.fromhex(row["hash"]) async for row in cursor]

        if len(hashes) > 0:
            raise InternalKeyValueError(node_hashes=hashes)

    async def _check_internal_left_right_are_bytes32(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT * FROM node WHERE node_type == :node_type",
                {"node_type": NodeType.INTERNAL},
            )

            hashes = []
            async for row in cursor:
                try:
                    bytes32.fromhex(row["left"])
                    bytes32.fromhex(row["right"])
                except ValueError:
                    hashes.append(bytes32.fromhex(row["hash"]))

        if len(hashes) > 0:
            raise InternalLeftRightNotBytes32Error(node_hashes=hashes)

    async def _check_terminal_left_right_are_null(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT * FROM node WHERE node_type == :node_type AND (left NOT NULL OR right NOT NULL)",
                {"node_type": NodeType.TERMINAL},
            )
            hashes = [bytes32.fromhex(row["hash"]) async for row in cursor]

        if len(hashes) > 0:
            raise TerminalLeftRightError(node_hashes=hashes)

    async def _check_roots_are_incrementing(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT * FROM root ORDER BY tree_id, generation")
            roots = [Root.from_row(row=row) async for row in cursor]

            roots_by_tree: Dict[bytes32, List[Root]] = defaultdict(list)
            for root in roots:
                roots_by_tree[root.tree_id].append(root)

            bad_trees = []
            for tree_id, roots in roots_by_tree.items():
                current_generation = roots[-1].generation
                expected_generations = list(range(current_generation + 1))
                actual_generations = [root.generation for root in roots]
                if actual_generations != expected_generations:
                    bad_trees.append(tree_id)

            if len(bad_trees) > 0:
                raise TreeGenerationIncrementingError(tree_ids=bad_trees)

    async def _check_hashes(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT * FROM node")

            bad_node_hashes: List[bytes32] = []
            async for row in cursor:
                node = row_to_node(row=row)
                if isinstance(node, InternalNode):
                    expected_hash = Program.to((node.left_hash, node.right_hash)).get_tree_hash(
                        node.left_hash, node.right_hash
                    )
                elif isinstance(node, TerminalNode):
                    expected_hash = Program.to((node.key, node.value)).get_tree_hash()

                if node.hash != expected_hash:
                    bad_node_hashes.append(node.hash)

        if len(bad_node_hashes) > 0:
            raise NodeHashError(node_hashes=bad_node_hashes)

    _checks: Tuple[Callable[["DataStore"], Awaitable[None]], ...] = (
        _check_internal_key_value_are_null,
        _check_internal_left_right_are_bytes32,
        _check_terminal_left_right_are_null,
        _check_roots_are_incrementing,
        _check_hashes,
    )

    async def create_tree(self, tree_id: bytes32, *, lock: bool = True, status: Status = Status.PENDING) -> bool:
        async with self.db_wrapper.locked_transaction(lock=lock):
            await self._insert_root(tree_id=tree_id, node_hash=None, status=status)

        return True

    async def table_is_empty(self, tree_id: bytes32, *, lock: bool = True) -> bool:
        async with self.db_wrapper.locked_transaction(lock=lock):
            tree_root = await self.get_tree_root(tree_id=tree_id, lock=False)

        return tree_root.node_hash is None

    async def get_tree_ids(self, *, lock: bool = True) -> Set[bytes32]:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT DISTINCT tree_id FROM root")

        tree_ids = {bytes32(hexstr_to_bytes(row["tree_id"])) async for row in cursor}

        return tree_ids

    async def get_tree_generation(self, tree_id: bytes32, *, lock: bool = True) -> int:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT MAX(generation) FROM root WHERE tree_id == :tree_id",
                {"tree_id": tree_id.hex()},
            )
            row = await cursor.fetchone()

        if row is None:
            raise Exception(f"No generations found for tree ID: {tree_id.hex()}")
        generation: int = row["MAX(generation)"]
        return generation

    async def get_tree_root(self, tree_id: bytes32, *, lock: bool = True) -> Root:
        async with self.db_wrapper.locked_transaction(lock=lock):
            generation = await self.get_tree_generation(tree_id=tree_id, lock=False)
            cursor = await self.db.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id AND generation == :generation",
                {"tree_id": tree_id.hex(), "generation": generation},
            )
            [root_dict] = [row async for row in cursor]

        return Root.from_row(row=root_dict)

    async def get_roots_between(
        self, tree_id: bytes32, generation_begin: int, generation_end: int, *, lock: bool = True
    ) -> List[Root]:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id "
                "AND generation >= :generation_begin AND generation < :generation_end ORDER BY generation ASC",
                {"tree_id": tree_id.hex(), "generation_begin": generation_begin, "generation_end": generation_end},
            )
            roots = [Root.from_row(row=row) async for row in cursor]

        return roots

    async def get_ancestors(self, node_hash: bytes32, tree_id: bytes32, *, lock: bool = True) -> List[InternalNode]:
        async with self.db_wrapper.locked_transaction(lock=lock):
            root = await self.get_tree_root(tree_id=tree_id, lock=False)
            if root.node_hash is None:
                raise Exception(f"Root hash is unspecified for tree ID: {tree_id.hex()}")
            cursor = await self.db.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key, value, depth) AS (
                        SELECT node.*, 0 AS depth FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT node.*, tree_from_root_hash.depth + 1 AS depth FROM node, tree_from_root_hash
                        WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                    ),
                    ancestors(hash, node_type, left, right, key, value, depth) AS (
                        SELECT node.*, NULL AS depth FROM node
                        WHERE node.left == :reference_hash OR node.right == :reference_hash
                        UNION ALL
                        SELECT node.*, NULL AS depth FROM node, ancestors
                        WHERE node.left == ancestors.hash OR node.right == ancestors.hash
                    )
                SELECT * FROM tree_from_root_hash INNER JOIN ancestors
                WHERE tree_from_root_hash.hash == ancestors.hash
                ORDER BY tree_from_root_hash.depth DESC
                """,
                {"reference_hash": node_hash.hex(), "root_hash": root.node_hash.hex()},
            )

            # The resulting rows must represent internal nodes.  InternalNode.from_row()
            # does some amount of validation in the sense that it will fail if left
            # or right can't turn into a bytes32 as expected.  There is room for more
            # validation here if desired.
            ancestors = [InternalNode.from_row(row=row) async for row in cursor]

        return ancestors

    async def get_keys_values(self, tree_id: bytes32, *, lock: bool = True) -> List[TerminalNode]:
        async with self.db_wrapper.locked_transaction(lock=lock):
            root = await self.get_tree_root(tree_id=tree_id, lock=False)

            if root.node_hash is None:
                return []

            cursor = await self.db.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key, value, depth, rights) AS (
                        SELECT node.*, 0 AS depth, 0 AS rights FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT
                            node.*,
                            tree_from_root_hash.depth + 1 AS depth,
                            CASE
                                WHEN node.hash == tree_from_root_hash.right
                                THEN tree_from_root_hash.rights + (1 << (62 - tree_from_root_hash.depth))
                                ELSE tree_from_root_hash.rights
                                END AS rights
                            FROM node, tree_from_root_hash
                        WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                    )
                SELECT * FROM tree_from_root_hash
                WHERE node_type == :node_type
                ORDER BY depth ASC, rights ASC
                """,
                {"root_hash": root.node_hash.hex(), "node_type": NodeType.TERMINAL},
            )

            terminal_nodes: List[TerminalNode] = []
            async for row in cursor:
                if row["depth"] > 62:
                    # TODO: Review the value and implementation of left-to-right order
                    #       reporting.  Initial use is for balanced insertion with the
                    #       work done in the query.

                    # This is limited based on the choice of 63 for the maximum left
                    # shift in the query.  This is in turn based on the SQLite integers
                    # ranging in size up to signed 8 bytes, 64 bits.  If we exceed this then
                    # we no longer guarantee the left-to-right ordering of the node
                    # list.  While 63 allows for a lot of nodes in a balanced tree, in
                    # the worst case it allows only 62 terminal nodes.
                    raise Exception("Tree depth exceeded 62, unable to guarantee left-to-right node order.")
                node = row_to_node(row=row)
                if not isinstance(node, TerminalNode):
                    raise Exception(f"Unexpected internal node found: {node.hash.hex()}")
                terminal_nodes.append(node)

        return terminal_nodes

    async def get_node_type(self, node_hash: bytes32, *, lock: bool = True) -> NodeType:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT node_type FROM node WHERE hash == :hash", {"hash": node_hash.hex()})
            raw_node_type = await cursor.fetchone()

        if raw_node_type is None:
            raise Exception(f"No node found for specified hash: {node_hash.hex()}")

        return NodeType(raw_node_type["node_type"])

    async def autoinsert(
        self,
        key: bytes,
        value: bytes,
        tree_id: bytes32,
        *,
        lock: bool = True,
    ) -> bytes32:
        async with self.db_wrapper.locked_transaction(lock=lock):
            pairs = await self.get_keys_values(tree_id=tree_id, lock=False)

            if len(pairs) == 0:
                reference_node_hash = None
                side = None
            else:
                reference_node_hash = pairs[0].hash
                side = Side.RIGHT

            return await self.insert(
                key=key,
                value=value,
                tree_id=tree_id,
                reference_node_hash=reference_node_hash,
                side=side,
                lock=False,
            )

    async def insert(
        self,
        key: bytes,
        value: bytes,
        tree_id: bytes32,
        reference_node_hash: Optional[bytes32],
        side: Optional[Side],
        *,
        lock: bool = True,
        status: Status = Status.PENDING,
    ) -> bytes32:
        async with self.db_wrapper.locked_transaction(lock=lock):
            was_empty = await self.table_is_empty(tree_id=tree_id, lock=False)
            root = await self.get_tree_root(tree_id=tree_id, lock=False)

            if not was_empty:
                # TODO: is there any way the db can enforce this?
                pairs = await self.get_keys_values(tree_id=tree_id, lock=False)
                if any(key == node.key for node in pairs):
                    raise Exception(f"Key already present: {key.hex()}")

            if reference_node_hash is None:
                if not was_empty:
                    raise Exception(f"Reference node hash must be specified for non-empty tree: {tree_id.hex()}")
            else:
                reference_node_type = await self.get_node_type(node_hash=reference_node_hash, lock=False)
                if reference_node_type == NodeType.INTERNAL:
                    raise Exception("can not insert a new key/value on an internal node")

            # create new terminal node
            new_terminal_node_hash = await self._insert_terminal_node(key=key, value=value, tree_id=tree_id)

            if was_empty:
                if side is not None:
                    raise Exception("Tree was empty so side must be unspecified, got: {side!r}")

                await self._insert_root(tree_id=tree_id, node_hash=new_terminal_node_hash, status=status)
            else:
                if side is None:
                    raise Exception("Tree was not empty, side must be specified.")
                if reference_node_hash is None:
                    raise Exception("Tree was not empty, reference node hash must be specified.")
                if root.node_hash is None:
                    raise Exception("Internal error.")

                ancestors: List[InternalNode] = await self.get_ancestors(
                    node_hash=reference_node_hash, tree_id=tree_id, lock=False
                )

                if side == Side.LEFT:
                    left = new_terminal_node_hash
                    right = reference_node_hash
                elif side == Side.RIGHT:
                    left = reference_node_hash
                    right = new_terminal_node_hash

                # create first new internal node
                new_hash = await self._insert_internal_node(left_hash=left, right_hash=right, tree_id=tree_id)

                traversal_node_hash = reference_node_hash

                # create updated replacements for the rest of the internal nodes
                for ancestor in ancestors:
                    if not isinstance(ancestor, InternalNode):
                        raise Exception(f"Expected an internal node but got: {type(ancestor).__name__}")

                    if ancestor.left_hash == traversal_node_hash:
                        left = new_hash
                        right = ancestor.right_hash
                    elif ancestor.right_hash == traversal_node_hash:
                        left = ancestor.left_hash
                        right = new_hash

                    traversal_node_hash = ancestor.hash

                    new_hash = await self._insert_internal_node(left_hash=left, right_hash=right, tree_id=tree_id)

                await self._insert_root(tree_id=tree_id, node_hash=new_hash, status=status)

        return new_terminal_node_hash

    async def delete(
        self,
        key: bytes,
        tree_id: bytes32,
        *,
        lock: bool = True,
        status: Status = Status.PENDING,
    ) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            node = await self.get_node_by_key(key=key, tree_id=tree_id, lock=False)
            ancestors = await self.get_ancestors(node_hash=node.hash, tree_id=tree_id, lock=False)

            if len(ancestors) == 0:
                # the only node is being deleted
                await self._insert_root(tree_id=tree_id, node_hash=None, status=status)

                return

            parent = ancestors[0]
            other_hash = parent.other_child_hash(hash=node.hash)

            if len(ancestors) == 1:
                # the parent is the root so the other side will become the new root
                await self._insert_root(tree_id=tree_id, node_hash=other_hash, status=status)

                return

            old_child_hash = parent.hash
            new_child_hash = other_hash
            # more parents to handle so let's traverse them
            for ancestor in ancestors[1:]:
                if ancestor.left_hash == old_child_hash:
                    left_hash = new_child_hash
                    right_hash = ancestor.right_hash
                elif ancestor.right_hash == old_child_hash:
                    left_hash = ancestor.left_hash
                    right_hash = new_child_hash
                else:
                    raise Exception("Internal error.")

                new_child_hash = await self._insert_internal_node(
                    left_hash=left_hash, right_hash=right_hash, tree_id=tree_id
                )

                old_child_hash = ancestor.hash

            await self._insert_root(tree_id=tree_id, node_hash=new_child_hash, status=status)

        return

    async def get_node_by_key(self, key: bytes, tree_id: bytes32, *, lock: bool = True) -> TerminalNode:
        async with self.db_wrapper.locked_transaction(lock=lock):
            nodes = await self.get_keys_values(tree_id=tree_id, lock=False)

        for node in nodes:
            if node.key == key:
                return node

        raise Exception(f"Key not found: {key.hex()}")

    async def get_node(self, node_hash: bytes32, *, lock: bool = True) -> Node:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT * FROM node WHERE hash == :hash", {"hash": node_hash.hex()})
            row = await cursor.fetchone()

        if row is None:
            raise Exception(f"Node not found for requested hash: {node_hash.hex()}")

        node = row_to_node(row=row)
        return node

    async def get_tree_as_program(self, tree_id: bytes32, *, lock: bool = True) -> Program:
        async with self.db_wrapper.locked_transaction(lock=lock):
            root = await self.get_tree_root(tree_id=tree_id, lock=False)
            # TODO: consider actual proper behavior
            assert root.node_hash is not None
            root_node = await self.get_node(node_hash=root.node_hash, lock=False)

            cursor = await self.db.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key, value) AS (
                        SELECT node.* FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT node.* FROM node, tree_from_root_hash
                        WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                    )
                SELECT * FROM tree_from_root_hash
                """,
                {"root_hash": root_node.hash.hex()},
            )
            nodes = [row_to_node(row=row) async for row in cursor]
            hash_to_node: Dict[bytes32, Node] = {}
            for node in reversed(nodes):
                if isinstance(node, InternalNode):
                    node = replace(node, pair=(hash_to_node[node.left_hash], hash_to_node[node.right_hash]))
                hash_to_node[node.hash] = node

            root_node = hash_to_node[root_node.hash]
            # TODO: Remove ignore when done.
            #       https://github.com/Chia-Network/clvm/pull/102
            #       https://github.com/Chia-Network/clvm/pull/106
            program: Program = Program.to(root_node)

        return program

    async def get_proof_of_inclusion_by_hash(
        self,
        node_hash: bytes32,
        tree_id: bytes32,
        *,
        lock: bool = True,
    ) -> ProofOfInclusion:
        """Collect the information for a proof of inclusion of a hash in the Merkle
        tree.
        """
        async with self.db_wrapper.locked_transaction(lock=lock):
            ancestors = await self.get_ancestors(node_hash=node_hash, tree_id=tree_id, lock=False)

        if len(ancestors) > 0:
            root_hash = ancestors[-1].hash
        else:
            root_hash = node_hash

        layers: List[ProofOfInclusionLayer] = []
        child_hash = node_hash
        for parent in ancestors:
            layer = ProofOfInclusionLayer.from_internal_node(internal_node=parent, traversal_child_hash=child_hash)
            layers.append(layer)
            child_hash = parent.hash

        return ProofOfInclusion(node_hash=node_hash, root_hash=root_hash, layers=layers)

    async def get_proof_of_inclusion_by_key(
        self,
        key: bytes,
        tree_id: bytes32,
        *,
        lock: bool = True,
    ) -> ProofOfInclusion:
        """Collect the information for a proof of inclusion of a key and its value in
        the Merkle tree.
        """
        async with self.db_wrapper.locked_transaction(lock=lock):
            node = await self.get_node_by_key(key=key, tree_id=tree_id, lock=False)
            return await self.get_proof_of_inclusion_by_hash(node_hash=node.hash, tree_id=tree_id, lock=False)

    async def get_left_to_right_ordering(
        self,
        node_hash: bytes32,
        tree_id: bytes32,
        *,
        lock: bool = True,
        num_nodes: int = 2500,
    ) -> List[Node]:
        ancestors = await self.get_ancestors(node_hash, tree_id, lock=True)
        path_hashes = {node_hash, *(ancestor.hash for ancestor in ancestors)}
        # The hashes that need to be traversed, initialized here as the hashes to the right of the ancestors
        # ordered from shallowest (root) to deepest (leaves) so .pop() from the end gives the deepest first.
        stack = [ancestor.right_hash for ancestor in reversed(ancestors) if ancestor.right_hash not in path_hashes]
        nodes: List[Node] = []
        while len(nodes) < num_nodes:
            try:
                node = await self.get_node(node_hash)
            except Exception:
                return []
            if isinstance(node, TerminalNode):
                nodes.append(node)
                if len(stack) > 0:
                    node_hash = stack.pop()
                else:
                    break
            elif isinstance(node, InternalNode):
                nodes.append(node)
                stack.append(node.right_hash)
                node_hash = node.left_hash
        return nodes

    # Returns the operation that got us from `root_hash_1` to `root_hash_2`.
    async def get_single_operation(
        self,
        root_hash_begin: Optional[bytes32],
        root_hash_end: Optional[bytes32],
        root_status: Status,
        *,
        lock: bool = False,
    ) -> Union[InsertionData, DeletionData]:
        async with self.db_wrapper.locked_transaction(lock=lock):
            if root_hash_begin is None:
                assert root_hash_end is not None
                node = await self.get_node(root_hash_end, lock=False)
                assert isinstance(node, TerminalNode)
                return InsertionData(node.hash, node.key, node.value, None, None, root_status)
            if root_hash_end is None:
                assert root_hash_begin is not None
                node = await self.get_node(root_hash_begin, lock=False)
                assert isinstance(node, TerminalNode)
                return DeletionData(None, node.key, root_status)
            copy_root_hash_end = root_hash_end
            while True:
                node_1 = await self.get_node(root_hash_begin, lock=False)
                node_2 = await self.get_node(root_hash_end, lock=False)
                if isinstance(node_1, TerminalNode):
                    assert isinstance(node_2, InternalNode)
                    if node_2.left_hash == node_1.hash:
                        new_terminal_node = await self.get_node(node_2.right_hash, lock=False)
                        side = Side.RIGHT
                    else:
                        assert node_2.right_hash == node_1.hash
                        new_terminal_node = await self.get_node(node_2.left_hash, lock=False)
                        side = Side.LEFT
                    reference_node_hash = node_1.hash
                    assert isinstance(new_terminal_node, TerminalNode)
                    return InsertionData(
                        copy_root_hash_end,
                        new_terminal_node.key,
                        new_terminal_node.value,
                        reference_node_hash,
                        side,
                        root_status,
                    )
                elif isinstance(node_2, TerminalNode):
                    assert isinstance(node_1, InternalNode)
                    if node_1.left_hash == node_2.hash:
                        new_terminal_node = await self.get_node(node_1.right_hash, lock=False)
                    else:
                        assert node_1.right_hash == node_2.hash
                        new_terminal_node = await self.get_node(node_1.left_hash, lock=False)
                    assert isinstance(new_terminal_node, TerminalNode)
                    return DeletionData(copy_root_hash_end, new_terminal_node.key, root_status)
                else:
                    if node_1.left_hash == node_2.left_hash:
                        root_hash_begin = node_1.right_hash
                        root_hash_end = node_2.right_hash
                    elif node_1.right_hash == node_2.right_hash:
                        root_hash_begin = node_1.left_hash
                        root_hash_end = node_2.left_hash
                    else:
                        assert node_1.left_hash == node_2.hash or node_1.right_hash == node_2.hash
                        if node_1.left_hash == node_2.hash:
                            new_terminal_node = await self.get_node(node_1.right_hash, lock=False)
                        else:
                            new_terminal_node = await self.get_node(node_1.left_hash, lock=False)
                        assert isinstance(new_terminal_node, TerminalNode)
                        return DeletionData(copy_root_hash_end, new_terminal_node.key, root_status)

    async def get_operations(
        self,
        tree_id: bytes32,
        generation_begin: int,
        num_generations: int = 10,
        *,
        lock: bool = True,
    ) -> List[Union[InsertionData, DeletionData]]:
        result: List[Union[InsertionData, DeletionData]] = []
        async with self.db_wrapper.locked_transaction(lock=lock):
            query_generation_begin = max(generation_begin - 1, 0)
            query_generation_end = min(
                generation_begin + num_generations, await self.get_tree_generation(tree_id=tree_id, lock=False) + 1
            )
            roots = await self.get_roots_between(tree_id, query_generation_begin, query_generation_end, lock=False)
            previous_root = None
            for current_root in roots:
                if previous_root is None:
                    previous_root = current_root
                    continue
                else:
                    operation = await self.get_single_operation(
                        previous_root.node_hash, current_root.node_hash, current_root.status, lock=False
                    )
                    result.append(operation)
                previous_root = current_root

        return result
