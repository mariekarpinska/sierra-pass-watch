"""Response models — the wire contract, one base class for the convention.

Code is snake_case Python; the wire is camelCase JSON (what the frontend's
TypeScript types declare). `CamelModel` centralizes that translation so no
endpoint ever hand-writes an alias.

→ validate, serialize, and structure the data passing between the client and the server
"""
# keeps type hints as strings so they never eval at runtime
from __future__ import annotations

# BaseModel gives us validation and serialization, ConfigDict holds the settings
from pydantic import BaseModel, ConfigDict
# ready made helper that turns snake_case field names into camelCase
from pydantic.alias_generators import to_camel


# shared base so the snake to camel rule lives in one place, not on every model
class CamelModel(BaseModel):
    """Base for every response model: `timestamp_utc` here, `timestampUtc` on the wire."""

    # per model config, pydantic reads this to change default behavior
    model_config = ConfigDict(
        # run every field name through to_camel to produce the json alias
        alias_generator=to_camel,
        # also accept the pythonic name on input so tests can build models
        # with snake_case while the wire still stays camelCase
        populate_by_name=True,
    )


# concrete payload returned by the health endpoint, inherits the camel rule
class Health(CamelModel):
    """Contract for GET /api/health, mirrored by the frontend."""

    # ok marker string, healthy when things are fine
    status: str
    # name of the service that answered
    service: str
    # iso 8601 timestamp, serializes out as timestampUtc
    timestamp_utc: str
