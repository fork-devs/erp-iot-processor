from pathlib import Path
from fastapi.testclient import TestClient


def execute_rest_step(client: TestClient, ctx: dict, method: str, path: str, json_body: dict | None = None):
    """Execute a REST step and store the response in scenario context."""
    resp = client.request(method=method.upper(), url=path, headers=ctx.get("headers", {}), json=json_body)
    ctx["last_response"] = resp
    return resp


def test_bdd_feature_files_follow_gherkin_conventions():
    """Verify all .feature files exist and contain formal English Gherkin structure."""
    features_dir = Path(__file__).parent / "features"
    feature_files = list(features_dir.glob("*.feature"))
    assert feature_files, "Expected at least one .feature file"
    for f in feature_files:
        content = f.read_text(encoding="utf-8")
        for keyword in ("Feature:", "Scenario:", "Given ", "When ", "Then "):
            assert keyword in content, f"{f.name} is missing Gherkin keyword {keyword!r}"
