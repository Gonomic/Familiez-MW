import json

from versioning.scan_mw_functions import scan


def write_fixture(tmp_path, filename, content):
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_scan_routes_and_builds_deterministic_signature(tmp_path):
    write_fixture(
        tmp_path,
        "routes.py",
        """
from fastapi import FastAPI

app = FastAPI()

@app.put('/marriages/{marriage_id}')
async def update_marriage(marriage_id: int, payload: dict) -> dict:
    return payload

@app.api_route('/search', methods=['POST', 'GET'], tags=['search'])
def search(query: str = ''):
    return {'query': query}
""",
    )

    result = scan(tmp_path)

    assert result["diagnostics"] == []
    assert [item["name"] for item in result["functions"]] == ["update_marriage", "search"]
    update = result["functions"][0]
    assert update["methods"] == ["PUT"]
    assert update["path"] == "/marriages/{marriage_id}"
    assert update["parameters"][0]["name"] == "marriage_id"
    assert update["isAsync"] is True
    assert update["signatureHash"].startswith("sha256:")
    assert len(update["signatureHash"]) == 71

    search = result["functions"][1]
    assert search["methods"] == ["GET", "POST"]
    assert search["options"]["tags"] == ["search"]
    assert scan(tmp_path) == result


def test_dynamic_route_values_are_reported_without_crashing(tmp_path):
    write_fixture(
        tmp_path,
        "dynamic_routes.py",
        """
from fastapi import FastAPI

app = FastAPI()
prefix = '/dynamic'

@app.get(prefix)
def dynamic_route():
    return None
""",
    )

    result = scan(tmp_path)

    assert result["diagnostics"] == []
    assert result["functions"][0]["path"] == "<dynamic>"


def test_syntax_errors_become_diagnostics(tmp_path):
    write_fixture(tmp_path, "broken.py", "def broken(:\n    pass\n")
    write_fixture(
        tmp_path,
        "valid.py",
        """
from fastapi import FastAPI
app = FastAPI()
@app.get('/ping')
def ping():
    return {'ok': True}
""",
    )

    result = scan(tmp_path)

    assert result["diagnostics"][0]["file"] == "broken.py"
    assert result["diagnostics"][0]["error"] == "SyntaxError"
    assert [item["name"] for item in result["functions"]] == ["ping"]