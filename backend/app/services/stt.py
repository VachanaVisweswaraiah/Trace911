"""Gladia streaming STT client.

Consumes the enhanced audio stream and emits TranscriptSegment events through
`store.publish('transcript', ...)`. Track partial→final revisions for the
transcript-health metric.
"""

from __future__ import annotations


async def stream_transcribe(call_id: str) -> None:
    """Open Gladia WS, push enhanced PCM frames, publish transcript events. TODO."""
    raise NotImplementedError
