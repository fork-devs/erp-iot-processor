import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import jwt
import pytest

from app.api.v1.preventive_alerts import get_alert_repository
from app.domain.preventive_alerts import AlertStatus, PreventiveAlert
from app.main import app
from app.repositories.preventive_alerts import PreventiveAlertRepository
from tests.jwt_helpers import TEST_PRIVATE_KEY

TENANT = str(uuid4())
OTHER_TENANT = str(uuid4())
ACTOR = str(uuid4())
PATH = "/api/v1/iot/alerts"


def headers(tenant=TENANT, roles=("WORKSHOP_ADMIN",)):
    token = jwt.encode(
        {"sub": ACTOR, "tenant_id": tenant, "roles": list(roles), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        TEST_PRIVATE_KEY, algorithm="RS256", headers={"kid": "test-key"},
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alert():
    return PreventiveAlert(
        id=str(uuid4()), vehicle_id=str(uuid4()), timestamp=datetime.now(timezone.utc),
        code="P0300", description="Misfire detected", severity="CRITICAL",
    )


@pytest.fixture
def schedule():
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    return {
        "branch_id": str(uuid4()), "scheduled_start": start.isoformat(),
        "scheduled_end": (start + timedelta(hours=1)).isoformat(),
    }


@pytest.fixture
def repository():
    repo = AsyncMock(spec=PreventiveAlertRepository)
    app.dependency_overrides[get_alert_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_alert_repository, None)


@pytest.fixture
async def client(repository):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as result:
        yield result


async def test_workshop_search_and_permissions(client, repository, alert):
    repository.search.return_value = [alert]
    restricted = await client.get(PATH, headers=headers(roles=("TECHNICIAN",)))
    assert restricted.status_code == 403
    repository.search.assert_not_awaited()

    response = await client.get(
        PATH, headers=headers(),
        params={"vehicle_id": alert.vehicle_id, "severity": "CRITICAL", "status": "PENDING"},
    )
    assert response.status_code == 200
    assert response.json()[0]["id"] == alert.id
    repository.search.assert_awaited_once_with(TENANT, alert.vehicle_id, "CRITICAL", "PENDING", None, None, 0, 20)


async def test_status_records_actor_and_requires_discard_reason(client, repository, alert):
    repository.get.return_value = alert
    path = f"{PATH}/{alert.id}/status"
    response = await client.patch(path, headers=headers(), json={"status": "DISMISSED", "reason": " "})
    assert response.status_code == 422
    repository.change_status.assert_not_awaited()

    async def save(tenant, original, change):
        assert tenant == TENANT
        assert change.changed_by == ACTOR
        assert change.changed_at.tzinfo is not None
        return original.model_copy(update={"status": change.status, "history": [change]})

    repository.change_status.side_effect = save
    response = await client.patch(path, headers=headers(), json={"status": "DISMISSED", "reason": "Sensor replaced"})
    assert response.status_code == 200
    assert response.json()["history"][0]["reason"] == "Sensor replaced"


async def test_another_tenant_cannot_modify_alert(client, repository, alert):
    repository.get.return_value = None
    response = await client.patch(
        f"{PATH}/{alert.id}/status", headers=headers(OTHER_TENANT), json={"status": "IN_REVIEW"},
    )
    assert response.status_code == 404
    repository.get.assert_awaited_once_with(OTHER_TENANT, alert.id)
    repository.change_status.assert_not_awaited()


def fleet_response(monkeypatch, reply):
    monkeypatch.setattr(
        "app.api.v1.preventive_alerts.AsyncClient",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(reply)),
    )


async def test_scheduling_uses_alert_data_and_replay_keeps_one_appointment(client, repository, alert, schedule, monkeypatch):
    repository.get.return_value = alert
    repository.claim_scheduling.return_value = "lease"
    appointment_id = uuid4()
    fleet_requests = []

    def reply(request):
        fleet_requests.append(request)
        payload = json.loads(request.content)
        assert request.method == "PUT"
        assert "/api/v1/fleet/appointments/from-alerts/" in request.url.path
        assert request.headers["X-Tenant-ID"] == TENANT
        assert payload["vehicleId"] == alert.vehicle_id
        assert payload["branchId"] == schedule["branch_id"]
        assert payload["notes"] == "P0300: Misfire detected"
        return httpx.Response(200, json={"id": str(appointment_id)})

    async def complete(tenant, alert_id, lease, receipt, actor, request):
        assert (tenant, alert_id, lease, receipt, actor) == (TENANT, alert.id, "lease", appointment_id, ACTOR)
        updated = alert.model_copy(update={
            "appointment_id": appointment_id, "status": AlertStatus.ATTENDED, "appointment_request": request,
        })
        repository.get.return_value = updated
        return updated

    fleet_response(monkeypatch, reply)
    repository.finish_scheduling.side_effect = complete
    path = f"{PATH}/{alert.id}/schedule-service"
    response = await client.post(path, headers=headers(), json=schedule)
    replay = await client.post(path, headers=headers(), json=schedule)
    different = await client.post(path, headers=headers(), json={**schedule, "branch_id": str(uuid4())})
    assert response.status_code == replay.status_code == 201
    assert response.json()["appointment_id"] == str(appointment_id)
    assert response.json()["status"] == "ATTENDED"
    assert "appointment_request" not in response.json()
    assert different.status_code == 409
    assert len(fleet_requests) == 1


@pytest.mark.parametrize(("fleet_status", "route_status", "retry_only"), [(409, 409, False), (503, 503, True)])
async def test_schedule_failure_does_not_change_status(
    client, repository, alert, schedule, monkeypatch, fleet_status, route_status, retry_only,
):
    repository.get.return_value = alert
    repository.claim_scheduling.return_value = "lease"
    fleet_response(monkeypatch, lambda _: httpx.Response(fleet_status))
    response = await client.post(f"{PATH}/{alert.id}/schedule-service", headers=headers(), json=schedule)
    assert response.status_code == route_status
    repository.release_scheduling.assert_awaited_once_with(TENANT, alert.id, "lease", retry_only=retry_only)
    repository.finish_scheduling.assert_not_awaited()
