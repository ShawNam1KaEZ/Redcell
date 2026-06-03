"""
hemogrid/storage.py — Storage interface and in-memory implementation.

Repository[T] is the canonical storage contract. InMemoryRepository is used
during development and for offline demos.

Day-of cloud swap: subclass Repository[T] and implement the five abstract
methods. Nothing in the rest of the codebase changes. Typical candidates:
    S3Repository          — objects serialized as JSON in an S3 bucket
    GCSRepository         — same on Google Cloud Storage
    DynamoDBRepository    — each object as a DynamoDB item
    PostgresRepository    — serialized with model_dump_json() into a JSONB column
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Repository(ABC, Generic[T]):
    """Abstract storage contract for canonical objects."""

    @abstractmethod
    def save(self, key: str, obj: T) -> None:
        """Upsert an object under `key`."""

    @abstractmethod
    def get(self, key: str) -> Optional[T]:
        """Return the object for `key`, or None if absent."""

    @abstractmethod
    def list_all(self) -> list[T]:
        """Return all stored objects (order unspecified)."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove the object for `key`. Returns True if it existed."""

    @abstractmethod
    def count(self) -> int:
        """Number of objects currently stored."""


class InMemoryRepository(Repository[T]):
    """
    In-memory store backed by a dict of JSON strings.

    Objects are round-tripped through model_dump_json / model_validate_json so
    fidelity matches a real persistence backend: dates become ISO strings,
    enums become their .value, Pydantic validators run on retrieval.

    To target a cloud backend, replace this class with a Repository[T] subclass
    that writes to S3 / GCS / DynamoDB / Postgres. No callers change.
    """

    def __init__(self, model_class: type[T]) -> None:
        self._model_class = model_class
        self._store: dict[str, str] = {}

    def save(self, key: str, obj: T) -> None:
        self._store[key] = obj.model_dump_json()

    def get(self, key: str) -> Optional[T]:
        raw = self._store.get(key)
        return None if raw is None else self._model_class.model_validate_json(raw)

    def list_all(self) -> list[T]:
        return [self._model_class.model_validate_json(v) for v in self._store.values()]

    def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    def count(self) -> int:
        return len(self._store)
