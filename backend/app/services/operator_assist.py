"""Operator assist: next-best-question + alerts.

Inputs: current IncidentCard, recent transcript, metrics. Outputs OperatorAssist
and discrete `alert` events. Keep deterministic-first (rules over critical
fields), then layer LLM polish for phrasing.
"""

from __future__ import annotations

from app.models.call import OperatorAssist
from app.models.incident import IncidentCard
from app.models.transcript import TranscriptSegment

# Order matters: highest-priority missing field first.
PRIORITY: tuple[str, ...] = (
    "breathing",
    "consciousness",
    "location",
    "incident_type",
    "immediate_danger",
    "weapons",
    "fire_or_smoke",
    "number_of_people",
    "injury_status",
    "caller_callback",
    "access_instructions",
)


async def compute_assist(
    incident: IncidentCard, transcript: list[TranscriptSegment]
) -> OperatorAssist:
    """Pick next question + critical-missing list. TODO."""
    raise NotImplementedError
