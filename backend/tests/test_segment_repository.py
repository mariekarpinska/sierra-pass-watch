"""Tests the segment repository's real SQL against a real Postgres.

test_segments_endpoint.py fakes the repository to test the HTTP layer. This test
runs the actual query, so it checks the column aliases, the route filter, and the
ordering really work and map onto the Segment model. It needs Docker
(Testcontainers), so it is marked `integration` and left out of the default run.
"""
from __future__ import annotations

import pytest
from psycopg_pool import AsyncConnectionPool
from testcontainers.postgres import PostgresContainer

from api.segments import SegmentRepository

# Label every test in this file `integration`. The default run
# (pytest -m "not integration") skips them; run them with `pytest -m integration`
# when Docker is available.
pytestmark = pytest.mark.integration

# A small stand-in for the real analytics.segments table: the same columns plus a
# few rows. The rows are inserted out of order on purpose, so the ordering test
# proves the query sorts them.
_SEED = """
    create schema analytics;
    create table analytics.segments (
        segment_id   text,
        segment_name text,
        route_id     text,
        lat          double precision,
        lon          double precision
    );
    insert into analytics.segments values
        ('I-80:truckee',       'Truckee',       'I-80',  39.3280, -120.1833),
        ('I-80:colfax',        'Colfax',        'I-80',  39.1002, -120.9533),
        ('SR-88:kirkwood',     'Kirkwood',      'SR-88', 38.6868, -120.0657);
"""


@pytest.fixture(scope="module")
def database_url():
    """Start a throwaway Postgres in Docker and hand back its connection URL.

    Testcontainers starts the container when the `with` block is entered and stops
    it when the block exits, so the database is cleaned up on its own.
    scope="module" means one container is shared by every test in this file.
    """
    with PostgresContainer("postgres:17-alpine") as postgres:
        # driver=None gives a plain postgresql:// URL (psycopg v3, not psycopg2).
        yield postgres.get_connection_url(driver=None)


@pytest.fixture()
async def repository(database_url):
    """Build a SegmentRepository pointed at the test database, then clean up.

    What happens, in order: open a connection pool, run the seed SQL to create the
    table and rows, give the test a repository, and afterwards drop the table and
    close the pool so the next test starts from a fresh table.
    """
    # The pool the repository borrows connections from. open=False means we open
    # it ourselves on the next line.
    pool = AsyncConnectionPool(database_url, open=False)
    await pool.open()

    # Create the analytics.segments table and insert the seed rows.
    async with pool.connection() as connection:
        await connection.execute(_SEED)

    try:
        # Hand the test a repository that reads from this database.
        yield SegmentRepository(pool)
    finally:
        # Runs after the test even if it failed: drop the table and close the pool
        # so the next test seeds a clean one.
        async with pool.connection() as connection:
            await connection.execute("drop schema analytics cascade")
        await pool.close()


async def test_get_all_returns_every_segment_ordered(repository) -> None:
    segments = await repository.get(None)

    # Ordered by (route_id, segment_id): I-80 before SR-88, colfax before truckee.
    assert [s.id for s in segments] == ["I-80:colfax", "I-80:truckee", "SR-88:kirkwood"]
    assert segments[0].name == "Colfax"


async def test_get_filters_to_one_route(repository) -> None:
    # Passing a route id returns only that route's segments.
    segments = await repository.get("SR-88")

    (segment,) = segments
    assert segment.route_id == "SR-88"
    assert segment.name == "Kirkwood"


async def test_get_unknown_route_is_empty(repository) -> None:
    # A route with no segments comes back as an empty list, not an error.
    assert await repository.get("SR-0") == []
