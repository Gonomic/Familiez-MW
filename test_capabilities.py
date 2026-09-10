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


@patch("main.verify_sso_token", return_value={"sub": "capability-test"})
@patch("main.STACK_MANIFEST_PATH", "")
@patch("main.engine")
def test_capabilities_returns_registry_and_no_manifest(mock_engine, _verify):
    connection = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = connection
    proxy = MagicMock()
    proxy.fetchall.return_value = [capability_row({"functions": [{"name": "get_person"}], "dependencies": []})]
    connection.execute.return_value = proxy

    response = client.get("/capabilities", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()["capabilities"]["functions"][0]["name"] == "get_person"
    assert response.json()["stackManifest"] is None
    connection.execute.assert_called_once()
    assert "GetFunctionCapabilities" in str(connection.execute.call_args.args[0])


@patch("main.verify_sso_token", return_value={"sub": "capability-test"})
@patch("main.engine")
def test_capabilities_returns_stack_manifest(mock_engine, _verify, tmp_path, monkeypatch):
    manifest = {"stackBuildNumber": 42, "compatibilityCheck": "passed"}
    manifest_path = tmp_path / "stack-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr("main.STACK_MANIFEST_PATH", str(manifest_path))

    connection = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = connection
    proxy = MagicMock()
    proxy.fetchall.return_value = [capability_row({"functions": [], "dependencies": []})]
    connection.execute.return_value = proxy

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