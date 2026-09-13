import json
from unittest.mock import MagicMock, Mock, patch

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def capability_row(payload):
    row = Mock()
    row._asdict.return_value = {
        "CompletedOk": 0,
        "Result": 200,
        "ErrorMessage": None,
        "Capabilities": json.dumps(payload),
    }
    return row


def stack_manifest_row(payload):
    row = Mock()
    row._asdict.return_value = {
        "CompletedOk": 0,
        "Result": 200,
        "ErrorMessage": None,
        "StackManifest": json.dumps(payload) if payload is not None else None,
    }
    return row


@patch("main.verify_sso_token", return_value={"sub": "capability-test"})
@patch("main.engine")
def test_capabilities_returns_registry_and_no_manifest(mock_engine, _verify):
    connection = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = connection
    proxy = MagicMock()
    proxy.fetchall.return_value = [capability_row({"functions": [{"name": "get_person"}], "dependencies": []})]
    stack_proxy = MagicMock()
    stack_proxy.fetchone.return_value = stack_manifest_row(None)
    connection.execute.side_effect = [proxy, stack_proxy]

    response = client.get("/capabilities", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()["capabilities"]["functions"][0]["name"] == "get_person"
    assert response.json()["stackManifest"] is None
    assert connection.execute.call_count == 2
    executed_sql = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert any("GetFunctionCapabilities" in statement for statement in executed_sql)


@patch("main.verify_sso_token", return_value={"sub": "capability-test"})
@patch("main.engine")
def test_capabilities_returns_stack_manifest(mock_engine, _verify):
    manifest = {"stackBuildNumber": 42, "compatibilityCheck": "passed"}

    connection = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = connection
    proxy = MagicMock()
    proxy.fetchall.return_value = [capability_row({"functions": [], "dependencies": []})]
    stack_proxy = MagicMock()
    stack_proxy.fetchone.return_value = stack_manifest_row(manifest)
    connection.execute.side_effect = [proxy, stack_proxy]

    response = client.get("/capabilities", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()["stackManifest"] == manifest


@patch("main.verify_sso_token", return_value={"sub": "capability-test"})
@patch("main.engine")
def test_capabilities_hides_database_error(mock_engine, _verify):
    mock_engine.connect.return_value.__enter__.side_effect = Exception("secret database detail")

    response = client.get("/capabilities", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Capabilities registry lookup failed"
    assert "secret" not in response.text