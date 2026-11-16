from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, computed_field, model_validator

from app.domain.models import DiagnosticSeverity


class AlertStatus(StrEnum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    ATTENDED = "ATTENDED"
    DISMISSED = "DISMISSED"


class StatusChange(BaseModel):
    status: AlertStatus
    changed_at: datetime
    changed_by: str
    reason: str | None = None


class AlertOccurrence(BaseModel):
    telemetry_id: str
    detected_at: datetime
    severity: DiagnosticSeverity
    sensor_values: dict[str, float] = Field(default_factory=dict)


class PreventiveAlert(BaseModel):
    id: str
    vehicle_id: str
    timestamp: datetime
    code: str
    description: str
    severity: DiagnosticSeverity
    status: AlertStatus = AlertStatus.PENDING
    history: list[StatusChange] = Field(default_factory=list)
    event_history: list[AlertOccurrence] = Field(default_factory=list)
    appointment_id: UUID | None = None
    appointment_request: dict[str, str | int] | None = Field(default=None, exclude=True)


    @computed_field
    @property
    def bay_number(self) -> int | None:
        value = (self.appointment_request or {}).get("bay_number")
        return value if isinstance(value, int) else None

    @computed_field
    @property
    def technician_id(self) -> str | None:
        value = (self.appointment_request or {}).get("technician_id")
        return value if isinstance(value, str) else None


class UpdateAlertStatus(BaseModel):
    status: AlertStatus
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_dismissal_reason(self):
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        if self.status == AlertStatus.DISMISSED and not self.reason:
            raise ValueError("Indicate a reason to dismiss the alert")
        return self


class ScheduleService(BaseModel):
    branch_id: UUID
    scheduled_start: AwareDatetime
    scheduled_end: AwareDatetime
    bay_number: int | None = Field(default=None, gt=0, le=2147483647)
    technician_id: UUID | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if (self.bay_number is None) != (self.technician_id is None):
            raise ValueError("Select both a bay and a technician")
        self.scheduled_start = self.scheduled_start.astimezone(timezone.utc)
        self.scheduled_end = self.scheduled_end.astimezone(timezone.utc)
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("The end time must be after the start time")
        return self
