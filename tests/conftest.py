"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from overseer import Process, Runtime
from overseer.persistence.store import Store


@pytest.fixture
def tmp_store(tmp_path: Path) -> Iterator[Store]:
    store = Store(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def runtime(tmp_store: Store) -> Runtime:
    return Runtime(store=tmp_store)


@pytest.fixture
def empty_process() -> Process:
    return Process("test")
