"""Reads the anchor waypoints from the dbt seed analytics.segments.

The query is plain SQL (no ORM). %(route_id)s is a bound parameter, never built
by string formatting, so the route filter cannot be used for SQL injection.

Ordered by (route_id, segment_id): stable, but not travel order. Travel order
comes from GET /api/routes; /api/segments is the flat list the map plots.
"""
from __future__ import annotations

from fastapi import Depends
from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from api.db import get_pool
from api.schemas import Segment

_SQL = """
    select
        segment_id   as id,
        route_id,
        segment_name as name,
        lat,
        lon
    from analytics.segments
    where (%(route_id)s::text is null or route_id = %(route_id)s)
    order by route_id, segment_id
"""


class SegmentRepository:
    """Endpoints depend on this class; tests swap in a fake via
    FastAPI's dependency_overrides."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get(self, route_id: str | None) -> list[Segment]:
        """Anchor waypoints, optionally filtered to one route."""
        async with self._pool.connection() as connection:
            # class_row builds a Segment from each row; the SQL aliases above
            # match the model's field names.
            async with connection.cursor(row_factory=class_row(Segment)) as cursor:
                await cursor.execute(_SQL, {"route_id": route_id})
                return await cursor.fetchall()


def get_segment_repository(
    pool: AsyncConnectionPool = Depends(get_pool),
) -> SegmentRepository:
    return SegmentRepository(pool)
