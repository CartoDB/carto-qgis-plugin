import re

import pytest
import requests

from carto.core.api import CartoApi

UUID_COMMENT = re.compile(
    r"^-- [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


@pytest.fixture
def api(fake_session):
    api = CartoApi()
    api.session = fake_session
    api.token = "tok"
    api.workspace_url = "https://workspace.example.com/"
    api.base_url = "https://api.example.com/"
    api.is_self_hosted = False
    return api


def _query_text(sent_query):
    return [line.strip() for line in sent_query.strip().splitlines()]


class TestGet:
    def test_sends_auth_header_and_client_param(self, api, fake_session):
        api.get("connections", params={"a": 1, "b": None})

        args, kwargs = fake_session.get.call_args
        assert args == ("https://workspace.example.com/connections",)
        assert kwargs["headers"] == {"Authorization": "Bearer tok"}
        assert kwargs["params"] == {"a": 1, "client": "carto-qgis-plugin"}
        assert "verify" not in kwargs

    def test_self_hosted_disables_ssl_verification(self, api, fake_session):
        api.is_self_hosted = True
        api.get("connections")

        assert fake_session.get.call_args.kwargs["verify"] is False

    def test_verify_false_disables_ssl_verification(self, api, fake_session):
        api.get("connections", verify=False)

        assert fake_session.get.call_args.kwargs["verify"] is False


class TestPost:
    def test_sends_auth_header_client_param_and_body(self, api, fake_session):
        api.post("v3/sql/conn/query", data={"q": "SELECT 1"})

        args, kwargs = fake_session.post.call_args
        assert args == ("https://workspace.example.com/v3/sql/conn/query",)
        assert kwargs["headers"] == {"Authorization": "Bearer tok"}
        assert kwargs["params"] == {"client": "carto-qgis-plugin"}
        assert kwargs["data"] == {"q": "SELECT 1"}
        assert "verify" not in kwargs
        fake_session.get.assert_not_called()

    def test_self_hosted_disables_ssl_verification(self, api, fake_session):
        api.is_self_hosted = True
        api.post("v3/sql/conn/query", data={"q": "SELECT 1"})

        assert fake_session.post.call_args.kwargs["verify"] is False

    def test_verify_false_disables_ssl_verification(self, api, fake_session):
        api.post("v3/sql/conn/query", data={"q": "SELECT 1"}, verify=False)

        assert fake_session.post.call_args.kwargs["verify"] is False


class TestExecuteQuery:
    def test_uses_get_with_query_in_url_params(self, api, fake_session):
        result = api.execute_query("conn", "SELECT 1")

        fake_session.post.assert_not_called()
        args, kwargs = fake_session.get.call_args
        assert args == ("https://api.example.com/v3/sql/conn/query",)
        lines = _query_text(kwargs["params"]["q"])
        assert UUID_COMMENT.match(lines[0])
        assert lines[1:] == ["SELECT 1"]
        assert result == {"rows": []}


class TestExecuteQueryPost:
    def test_sends_query_in_body(self, api, fake_session):
        result = api.execute_query_post("conn", "SELECT 1")

        fake_session.get.assert_not_called()
        args, kwargs = fake_session.post.call_args
        assert args == ("https://api.example.com/v3/sql/conn/query",)
        assert "q" not in kwargs["params"]
        lines = _query_text(kwargs["data"]["q"])
        assert UUID_COMMENT.match(lines[0])
        assert lines[1:] == ["SELECT 1"]
        assert result == {"rows": []}

    def test_tags_request_with_client_param(self, api, fake_session):
        api.execute_query_post("conn", "SELECT 1")

        assert fake_session.post.call_args.kwargs["params"] == {
            "client": "carto-qgis-plugin"
        }

    def test_self_hosted_disables_ssl_verification(self, api, fake_session):
        api.is_self_hosted = True
        api.execute_query_post("conn", "SELECT 1")

        assert fake_session.post.call_args.kwargs["verify"] is False

    def test_uuid_comment_is_unique_per_call(self, api, fake_session):
        api.execute_query_post("conn", "SELECT 1")
        api.execute_query_post("conn", "SELECT 1")

        first, second = (
            _query_text(c.kwargs["data"]["q"])[0]
            for c in fake_session.post.call_args_list
        )
        assert first != second

    def test_large_query_is_not_put_in_url(self, api, fake_session):
        query = "SELECT '" + "ab" * 10_000 + "'"
        api.execute_query_post("conn", query)

        kwargs = fake_session.post.call_args.kwargs
        assert query in kwargs["data"]["q"]
        assert all(len(str(v)) < 100 for v in kwargs["params"].values())

    def test_http_error_propagates(self, api, fake_session):
        fake_session.post.return_value.raise_for_status.side_effect = (
            requests.HTTPError("414 Client Error: URI Too Long")
        )

        with pytest.raises(requests.HTTPError, match="414"):
            api.execute_query_post("conn", "SELECT 1")
