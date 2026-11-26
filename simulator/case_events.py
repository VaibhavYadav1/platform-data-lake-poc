"""
Case event publisher (task A7): publishes case lifecycle events to Pub/Sub.

Each case event represents a state change in a case (opened, updated, closed). The events are published to
the poc-case-events topic with Avro schema validation. About 2% of events are published twice (same event_id,
different message_id) to simulate DQ35 duplicate detection in staging.

The JSON encoding uses WRAPPED format for union types as required by Google Pub/Sub schema validation:
  - Non-null union values: {"type": value}, e.g. {"string": "tok-123"}, {"double": 99.99}
  - Null values: plain JSON null
  - ALL fields must be present, even nullable ones with defaults

Event types map to G2 incident lifecycle:
  - CASE_OPENED: incident created (NOT_STARTED → IN_REVIEW/MONITORED → CASE_OPENED)
  - CASE_UPDATED: incident progressed (CASE_OPENED → CASE_UPDATED, or CASE_UPDATED → CASE_UPDATED)
  - CASE_CLOSED: incident resolved (any status → RESOLVED)

About 1% of events use an unknown store (DQ44) to test staging validation.
"""

import json
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from google.cloud import pubsub_v1


def _wrap_union_value(value: Any, field_type: str) -> dict[str, Any] | None:
    """Wrap a value for Avro union type encoding, or return None if value is None."""
    if value is None:
        return None
    return {field_type: value}


def _generate_event_id() -> str:
    """Generate a unique event ID."""
    return f"evt-{uuid.uuid4().hex[:12]}"


def _generate_case_id() -> str:
    """Generate a case ID."""
    return f"case-{uuid.uuid4().hex[:8]}"


def _map_event_type(action: str) -> str:
    """Map G2 incident action to case event type.
    
    Maps from G2 incident lifecycle to LPOS case event types:
    - New incidents (opened) → CASE_OPENED
    - Updated incidents → CASE_UPDATED  
    - Closed incidents (resolved) → CASE_CLOSED
    """
    if action == "opened":
        return "CASE_OPENED"
    elif action == "closed":
        return "CASE_CLOSED"
    else:  # updated
        return "CASE_UPDATED"


def _map_case_status(action: str) -> str:
    """Map G2 incident action to case status.
    
    Returns the status AFTER the event:
    - opened → OPEN
    - updated → UNDER_REVIEW
    - closed → CLOSED
    """
    if action == "opened":
        return "OPEN"
    elif action == "closed":
        return "CLOSED"
    else:  # updated
        return "UNDER_REVIEW"


def _build_case_event_message(
    event_id: str,
    case_id: str,
    event_type: str,
    event_ts: datetime,
    g2_store_id: str,
    case_status: str,
    offender_token: str | None = None,
    loss_amount: float | None = None,
    items_count: int | None = None,
) -> dict[str, Any]:
    """Build a case event message with proper Avro union wrapping.
    
    Uses WRAPPED format for union types as required by Pub/Sub schema validation:
    - Non-null union values must be wrapped: {"string": value}, {"double": value}, {"int": value}
    - Null values use plain JSON null
    - ALL fields must be present, even nullable ones
    
    Args:
        event_id: Unique event identifier
        case_id: Case identifier (multiple events per case)
        event_type: CASE_OPENED, CASE_UPDATED, or CASE_CLOSED
        event_ts: Event timestamp
        g2_store_id: Store ID from G2
        case_status: OPEN, UNDER_REVIEW, or CLOSED
        offender_token: Optional opaque offender identifier (PII)
        loss_amount: Optional monetary loss amount
        items_count: Optional number of items involved
        
    Returns:
        Message dict ready for JSON encoding and Pub/Sub publishing
    """
    # Convert timestamp to microseconds (Avro timestamp-micros)
    event_ts_micros = int(event_ts.timestamp() * 1_000_000)
    
    message = {
        "event_id": event_id,
        "case_id": case_id,
        "event_type": event_type,
        "event_ts": event_ts_micros,
        "g2_store_id": g2_store_id,
        "case_status": case_status,
        # Wrap non-null union values, or use null
        "offender_token": _wrap_union_value(offender_token, "string"),
        "loss_amount": _wrap_union_value(loss_amount, "double"),
        "items_count": _wrap_union_value(items_count, "int"),
    }
    
    return message


def publish_case_events(topic: str, n: int, rng: random.Random) -> int:
    """Publish n case events to the given Pub/Sub topic.
    
    Generates synthetic case events matching the G2 incident lifecycle. About 2% of events are
    published twice (same event_id) to simulate DQ35 duplicate detection. About 1% use an unknown
    store ID to test DQ44 validation in staging.
    
    Args:
        topic: Full Pub/Sub topic path (e.g., "projects/PROJECT/topics/poc-case-events")
        n: Number of events to publish
        rng: Random number generator for reproducibility
        
    Returns:
        Number of messages published (may be > n due to duplicates)
        
    Raises:
        Exception: If publishing fails
    """
    if n == 0:
        return 0
    
    publisher = pubsub_v1.PublisherClient()
    now = datetime.now(timezone.utc)
    
    # Store IDs for sampling (avoid probe store S999 per specs)
    store_ids = [f"S{i:03d}" for i in range(1, 41)]  # S001-S040 from baseline
    unknown_store_id = "S990"  # Unknown store for DQ44 testing
    
    # Event actions to simulate
    actions = ["opened", "updated", "closed"]
    
    # Generate and publish events
    messages_published = 0
    futures = []
    
    for _ in range(n):
        # Generate case event data
        event_id = _generate_event_id()
        case_id = _generate_case_id()
        action = rng.choice(actions)
        event_type = _map_event_type(action)
        case_status = _map_case_status(action)
        
        # About 1% use unknown store for DQ44 testing
        if rng.random() < 0.01:
            g2_store_id = unknown_store_id
        else:
            g2_store_id = rng.choice(store_ids)
        
        # Generate optional fields with some probability
        offender_token = f"off-{uuid.uuid4().hex[:8]}" if rng.random() < 0.3 else None
        loss_amount = round(rng.uniform(10.0, 500.0), 2) if rng.random() < 0.4 else None
        items_count = rng.randint(1, 10) if rng.random() < 0.5 else None
        
        # Build message with proper union wrapping
        message = _build_case_event_message(
            event_id=event_id,
            case_id=case_id,
            event_type=event_type,
            event_ts=now,
            g2_store_id=g2_store_id,
            case_status=case_status,
            offender_token=offender_token,
            loss_amount=loss_amount,
            items_count=items_count,
        )
        
        # Publish message
        data = json.dumps(message).encode("utf-8")
        future = publisher.publish(topic, data)
        futures.append(future)
        messages_published += 1
        
        # About 2% of events are published twice (DQ35 duplicate testing)
        if rng.random() < 0.02:
            # Same event_id, will get different message_id from Pub/Sub
            future = publisher.publish(topic, data)
            futures.append(future)
            messages_published += 1
    
    # Wait for all publishes to complete
    for future in futures:
        future.result()  # Raises if publish failed
    
    return messages_published
