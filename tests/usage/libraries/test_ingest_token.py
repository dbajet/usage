from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from usage.libraries.ingest_token import IngestToken
from usage.structures.app_exception import AppException


def helper_instance() -> IngestToken:
    return IngestToken(MagicMock())


def test___init__() -> None:
    database = MagicMock()
    tested = IngestToken(database)
    assert tested._database is database
    assert database.mock_calls == []


@patch.object(IngestToken, "hashed")
def test_house_id(hashed: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        hashed.reset_mock()
        database.reset_mock()

    exp_query = "SELECT id FROM houses WHERE ingest_token_hash = %s AND ingest_token_hash <> ''"

    # no token
    for authorization in ["", "  ", "Bearer", "bearer  "]:
        with pytest.raises(AppException) as exc_info:
            tested.house_id(authorization)
        assert exc_info.value.status_code == 401
        assert exc_info.value.message == "A sensor token is required."
        assert hashed.mock_calls == []
        assert database.mock_calls == []
        reset_mocks()

    # unknown token
    hashed.side_effect = ["the-hash"]
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.house_id("Bearer the-token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "The sensor token is not valid."
    assert hashed.mock_calls == [call("the-token")]
    assert database.mock_calls == [call.fetch_one(exp_query, ("the-hash",))]
    reset_mocks()

    # known token, with or without the scheme
    for authorization in ["Bearer the-token", "bearer  the-token ", " the-token"]:
        hashed.side_effect = ["the-hash"]
        database.fetch_one.side_effect = [{"id": 3}]
        result = tested.house_id(authorization)
        expected = 3
        assert result == expected
        assert hashed.mock_calls == [call("the-token")]
        assert database.mock_calls == [call.fetch_one(exp_query, ("the-hash",))]
        reset_mocks()


def test_hashed() -> None:
    tested = IngestToken
    result = tested.hashed("the-token")
    expected = "c2a73fcf61dfbdcadc79a10ba330b2ef5eb66fc0a6735ed69b796bb3c97b97ae"
    assert result == expected
