"""Identifiers. Charge and refund ids are random UUIDs, generated here and nowhere else."""

import uuid


def new_id() -> str:
    return str(uuid.uuid4())


def parse(value: str) -> uuid.UUID:
    """Raise ValueError unless `value` is a UUID."""
    return uuid.UUID(value)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:20]}"
