"""Transcript → IncidentCard extraction.

Runs an LLM over the rolling transcript whenever a final segment lands (or after
a small debounce). Updates field values + status + confidence. Never sets
`confirmed_by_operator` — only the operator can do that via PATCH.
"""

from __future__ import annotations

from app.models.incident import IncidentCard
from app.models.transcript import TranscriptSegment


async def update_from_transcript(
    incident: IncidentCard,
    transcript: list[TranscriptSegment],
) -> IncidentCard:
    """Mutate-and-return the IncidentCard based on transcript so far. TODO."""
    raise NotImplementedError


async def build_summary(transcript: list[TranscriptSegment], incident: IncidentCard) -> str:
    """Generate the dispatch handoff narrative. TODO."""
    raise NotImplementedError
