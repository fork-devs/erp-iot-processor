from dataclasses import dataclass
from typing import Dict, Optional
from app.domain.models import DiagnosticSeverity


@dataclass(frozen=True)
class DTCEntry:
    code: str
    severity: DiagnosticSeverity
    system: str
    title: str
    description: str


# Pre-configured automotive OBD-II DTC reference catalog
_KNOWN_DTCS: Dict[str, DTCEntry] = {
    # Critical Powertrain
    "P0300": DTCEntry("P0300", DiagnosticSeverity.CRITICAL, "Powertrain", "Random/Multiple Cylinder Misfire", "Severe engine misfire detected which may damage catalytic converter."),
    "P0301": DTCEntry("P0301", DiagnosticSeverity.CRITICAL, "Powertrain", "Cylinder 1 Misfire", "Cylinder 1 misfire detected."),
    "P0302": DTCEntry("P0302", DiagnosticSeverity.CRITICAL, "Powertrain", "Cylinder 2 Misfire", "Cylinder 2 misfire detected."),
    "P0303": DTCEntry("P0303", DiagnosticSeverity.CRITICAL, "Powertrain", "Cylinder 3 Misfire", "Cylinder 3 misfire detected."),
    "P0304": DTCEntry("P0304", DiagnosticSeverity.CRITICAL, "Powertrain", "Cylinder 4 Misfire", "Cylinder 4 misfire detected."),
    "P0217": DTCEntry("P0217", DiagnosticSeverity.CRITICAL, "Powertrain", "Engine Coolant Over Temperature", "Engine operating temperature exceeded maximum critical safety threshold."),
    "P0219": DTCEntry("P0219", DiagnosticSeverity.CRITICAL, "Powertrain", "Engine Overspeed Condition", "Engine RPM exceeded manufacturer maximum safety limit."),

    # Warnings Powertrain
    "P0117": DTCEntry("P0117", DiagnosticSeverity.WARNING, "Powertrain", "Engine Coolant Temp Circuit Low", "Engine coolant temperature sensor signal is below expected operating range."),
    "P0118": DTCEntry("P0118", DiagnosticSeverity.WARNING, "Powertrain", "Engine Coolant Temp Circuit High", "Engine coolant temperature sensor signal is above expected operating range."),
    "P0171": DTCEntry("P0171", DiagnosticSeverity.WARNING, "Powertrain", "System Too Lean (Bank 1)", "Air-fuel mixture has excess oxygen; fuel injection or vacuum leak suspected."),
    "P0172": DTCEntry("P0172", DiagnosticSeverity.WARNING, "Powertrain", "System Too Rich (Bank 1)", "Air-fuel mixture has excess fuel; injector or sensor malfunction."),
    "P0420": DTCEntry("P0420", DiagnosticSeverity.WARNING, "Powertrain", "Catalyst System Efficiency Below Threshold", "Catalytic converter efficiency is degraded."),
    "P0562": DTCEntry("P0562", DiagnosticSeverity.WARNING, "Electrical", "System Voltage Low", "Charging system voltage is below standard operating range (< 12V)."),
    "P0563": DTCEntry("P0563", DiagnosticSeverity.WARNING, "Electrical", "System Voltage High", "Alternator regulator failure resulting in overvoltage (> 15V)."),

    # Network / Communication
    "U0100": DTCEntry("U0100", DiagnosticSeverity.CRITICAL, "Network", "Lost Communication with ECM/PCM", "CAN bus communication loss with the primary Engine Control Module."),
    "U0101": DTCEntry("U0101", DiagnosticSeverity.CRITICAL, "Network", "Lost Communication with TCM", "CAN bus communication loss with the Transmission Control Module."),
    "U0121": DTCEntry("U0121", DiagnosticSeverity.WARNING, "Network", "Lost Communication with Anti-Lock Brake System", "CAN bus communication loss with ABS module."),

    # Chassis & Safety
    "C0035": DTCEntry("C0035", DiagnosticSeverity.WARNING, "Chassis", "Left Front Wheel Speed Sensor", "ABS wheel speed sensor signal circuit malfunction."),
    "B0001": DTCEntry("B0001", DiagnosticSeverity.CRITICAL, "Body", "Driver Frontal Stage 1 Deployment Control", "Driver airbag deployment circuit open or grounded."),
}


def lookup_dtc(code: str) -> DTCEntry:
    """Classify an OBD-II code. If unknown, infer category and default to WARNING for P/U and INFO otherwise."""
    cleaned = code.strip().upper()
    if cleaned in _KNOWN_DTCS:
        return _KNOWN_DTCS[cleaned]

    prefix = cleaned[0] if cleaned else "P"
    if prefix == "P":
        system = "Powertrain"
        severity = DiagnosticSeverity.WARNING
    elif prefix == "U":
        system = "Network"
        severity = DiagnosticSeverity.WARNING
    elif prefix == "C":
        system = "Chassis"
        severity = DiagnosticSeverity.WARNING
    elif prefix == "B":
        system = "Body"
        severity = DiagnosticSeverity.INFO
    else:
        system = "General"
        severity = DiagnosticSeverity.INFO

    return DTCEntry(
        code=cleaned,
        severity=severity,
        system=system,
        title=f"Diagnostic Code {cleaned}",
        description=f"Automotive diagnostic trouble code in {system} system."
    )
