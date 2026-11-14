"""Pure checks for video retrieval helpers; the database-backed tests live in tests/integration."""

from uuid import uuid4

import pytest
from repovox.api.routes import byte_range
from repovox.core.errors import DomainError
from repovox.media.store import KEY, media_key


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, None),
        ("bytes=0-99", (0, 99)),
        ("bytes=10-", (10, 999)),
        ("bytes=990-5000", (990, 999)),
        ("bytes=1000-1001", None),
        ("bytes=5-2", None),
        ("bytes=-100", None),
        ("bytes=0-1,5-9", None),
        ("items=0-1", None),
        ("bytes=a-b", None),
    ],
)
def test_byte_range(header: str | None, expected: tuple[int, int] | None) -> None:
    assert byte_range(header, 1000) == expected


def test_media_keys_cannot_leave_their_owner_and_job_prefix() -> None:
    owner, job, artifact = uuid4(), uuid4(), uuid4()
    key = media_key(owner, job, 14, artifact, "a" * 64)
    assert key == f"media/{owner}/{job}/14/{artifact}/{'a' * 64}" and KEY.fullmatch(key)
    for bad in [
        (owner, job, 9, artifact, "a" * 64),
        (owner, job, 16, artifact, "a" * 64),
        (owner, job, 14, artifact, "A" * 64),
        (owner, job, 14, "../../other", "a" * 64),
        ("..", job, 14, artifact, "a" * 64),
        (owner, f"{job}/../{uuid4()}", 14, artifact, "a" * 64),
    ]:
        with pytest.raises(DomainError):
            media_key(*bad)
    for hostile in [
        f"development/{owner}/{job}/analysis/{artifact}/{'a' * 64}",
        f"media/{owner}/{job}/14/{artifact}/{'a' * 64}/extra",
        f"/media/{owner}/{job}/14/{artifact}/{'a' * 64}",
    ]:
        assert not KEY.fullmatch(hostile)
