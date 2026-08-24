"""Record-level, secret-free sync primitives for Divan.

This module deliberately does not copy SQLite files.  It exports a small
allowlist of logical records and keeps sync identity/version information in
shadow tables, so it can be added to databases created by older Divan builds.

Integration contract
--------------------
Call ``initialize_sync(conn, device_id)`` once after ``server.init_db()``.
After an allowed row is inserted or updated, call
``record_local_change(conn, record_type, local_id, device_id)`` in the same
transaction.  Before the existing deletion flow physically removes a row,
call ``record_local_delete(..., physical=False)`` in that transaction; for a
conversation, the default cascade records tombstones for its syncable child
rows too.

Exchange ``export_change_batch`` results over the authenticated same-Wi-Fi
transport and feed them to ``apply_change_batch``.  Cursors are local change
log positions, not SQLite row ids.  The transport is responsible for peer
authentication, confidentiality, size limits, and replay throttling.

Only RECORD_TYPES below can cross the wire.  In particular ``settings``
(including provider configuration and ``pin_hash``), ``jobs`` and
``chat_requests`` are not addressable by this API.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


BATCH_KIND = "divan-record-sync"
# Protocol v8 keeps the explicitly consented, approved-only Schema Path v4
# projection readable and adds only the shared continuation state required by
# the provider-authored Schema Path v5 chat flow.  Prompt plans/results,
# counterfactual/origin ledgers, checkpoint internals and technique transcripts
# remain device-local.  Keeping this as a hard wire-version boundary prevents
# a v7 peer from acknowledging v5 stages it cannot validate or resume.
BATCH_VERSION = 8
PROJECTION_VERSION = 1
DEFAULT_BATCH_LIMIT = 500
MAX_BATCH_LIMIT = 1000
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_TEXT_FIELD_BYTES = 512 * 1024
MAX_SHORT_TEXT_BYTES = 4096
MAX_IDENTIFIER_BYTES = 128
_PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")
_TURN_PAIR_PUBLIC_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_FORBIDDEN_KEYS = frozenset({
    "api_key", "deepseek_api_key", "openai_api_key",
    "anthropic_api_key", "gemini_api_key", "lmstudio_api_key",
    "ollama_api_key", "pin_hash",
    "password", "secret", "access_token", "refresh_token",
})

# The source database is intentionally more permissive than the wire.  These
# bounds protect a paired device from SQLite's dynamic typing and from records
# which are individually unreasonable even when the whole batch is still under
# MAX_PAYLOAD_BYTES.  Optional legacy columns may be absent, but values which
# are present must have the expected scalar type.
_REQUIRED_PAYLOAD_FIELDS = {
    "conversation": frozenset({"mode"}),
    "message": frozenset({
        "role", "content", "conversation_public_id", "turn_pair_public_id",
    }),
    "note": frozenset({"mode", "content", "conversation_public_id"}),
    "goal": frozenset({"title"}),
    "checkin": frozenset(),
    "memory": frozenset({"therapist", "content"}),
    "session_summary": frozenset({"conversation_public_id"}),
    "session_meta": frozenset({"conversation_public_id"}),
    "adhd_habit": frozenset({
        "conversation_public_id", "title", "target_per_week", "status",
    }),
    "adhd_habit_event": frozenset({
        "habit_public_id", "scheduled_for", "status",
    }),
    "adhd_journal": frozenset({
        "conversation_public_id", "entry_type", "content",
        "share_with_coach", "sensitive",
    }),
    "schema_path": frozenset({
        "conversation_public_id", "path_sequence", "flow_version",
        "clinical_generation", "stage", "step", "status",
        "practice_status", "revision",
    }),
    "schema_candidate": frozenset({
        "conversation_public_id", "source_user_message_public_id",
        "source_assistant_message_public_id", "schema_key", "mode_key",
        "clinical_generation", "status", "revision",
    }),
    "schema_focus_check": frozenset({
        "conversation_public_id", "path_public_id",
        "candidate_public_id", "source_user_message_public_id",
        "source_assistant_message_public_id", "baseline_burden",
        "changed_burden", "fit", "confirmed", "revision",
    }),
    "schema_step": frozenset({
        "conversation_public_id", "path_public_id", "stage", "step",
        "status", "revision",
    }),
    "schema_origin": frozenset({
        "conversation_public_id", "path_public_id", "confidence",
        "authored_by", "status", "source_user_message_public_id",
        "source_assistant_message_public_id",
    }),
    "schema_growth": frozenset({
        "conversation_public_id", "path_public_id", "seq", "status",
        "environment_status",
        "source_user_message_public_id",
        "source_assistant_message_public_id",
    }),
    "schema_healthy_adult": frozenset({
        "conversation_public_id", "path_public_id",
        "source_message_public_id", "source_assistant_message_public_id",
        "source", "evidence", "status",
    }),
    "schema_transfer": frozenset({
        "conversation_public_id", "path_public_id",
        "source_user_message_public_id",
        "source_assistant_message_public_id",
        "trigger_source_user_message_public_id", "trigger_text",
        "trigger_source_assistant_message_public_id",
        "healthy_adult_response", "planned_action", "authored_by", "status",
    }),
    "schema_message_meta": frozenset({
        "conversation_public_id", "message_public_id",
        "source_user_message_public_id",
        "source_assistant_message_public_id", "kind", "status",
        "event_key", "clinical_generation",
    }),
}

# Flow-v4 values remain valid legacy projection data.  Flow-v5 deliberately
# has a smaller reachable graph: no rating/focus approval steps, no method
# approval form and no pre-technique questionnaires.  Keep this mapping local
# to the wire contract instead of importing server.py so sync validation stays
# usable by the standalone secure transport and migration tests.
_SCHEMA_PATH_V4_STEP_STAGE = {
    **{step: "listen" for step in (
        "listen", "candidate_review", "current_impact", "variable_check",
        "focus_confirm",
    )},
    **{step: "depth" for step in (
        "method_select", "method_confirm", "origin_or_unknown",
        "imagery_precheck", "imagery_work", "mode_dialogue",
        "reparent_or_chair_precheck", "reparent_or_chair_work",
        "grounding_review",
    )},
    **{step: "integrate" for step in (
        "healthy_adult_voice", "age_ladder", "environment_rescript",
        "present_transfer", "optional_practice", "followup",
    )},
    "complete": "complete",
}
_SCHEMA_PATH_V5_STEP_STAGE = {
    "listen": "listen",
    "candidate_review": "listen",
    "variable_explore": "explore",
    "origin_sequence": "origin",
    "imagery_work": "work",
    "mode_dialogue": "work",
    "reparent_or_chair_work": "work",
    "grounding_review": "work",
    "healthy_adult_voice": "integrate",
    "age_ladder": "integrate",
    "environment_rescript": "integrate",
    "present_transfer": "integrate",
    "optional_practice": "integrate",
    "followup": "integrate",
    "complete": "complete",
}
_SCHEMA_PATH_STEP_STAGE_BY_FLOW = {
    4: _SCHEMA_PATH_V4_STEP_STAGE,
    5: _SCHEMA_PATH_V5_STEP_STAGE,
}
_SCHEMA_PATH_METHODS_BY_FLOW = {
    4: frozenset({
        "",
        "young:method:imagery-rescripting",
        "young:method:chair-dialogue",
        "young:method:limited-reparenting",
    }),
    # V5's deterministic selector never chooses limited reparenting.  A
    # validated legacy v4 run may still carry it under the v4 contract above.
    5: frozenset({
        "",
        "young:method:imagery-rescripting",
        "young:method:chair-dialogue",
    }),
}
_SCHEMA_PATH_ALL_STAGES = frozenset(
    stage for mapping in _SCHEMA_PATH_STEP_STAGE_BY_FLOW.values()
    for stage in mapping.values())
_SCHEMA_PATH_ALL_STEPS = frozenset(
    step for mapping in _SCHEMA_PATH_STEP_STAGE_BY_FLOW.values()
    for step in mapping)

_ENUM_FIELDS = {
    ("conversation", "mode"): frozenset({"terapi", "ders"}),
    ("message", "role"): frozenset({"user", "assistant", "system"}),
    ("goal", "status"): frozenset({"active", "done", "archived"}),
    ("session_summary", "status"): frozenset({
        "pending", "approved", "rejected",
    }),
    ("note", "scope"): frozenset({
        "therapist", "shared", "private", "excluded",
    }),
    ("memory", "scope"): frozenset({
        "therapist", "shared", "private", "excluded",
    }),
    ("adhd_habit", "status"): frozenset({
        "active", "paused", "archived",
    }),
    ("adhd_habit_event", "status"): frozenset({
        "done", "partial", "skipped", "cancelled_user",
        "suppressed_safety",
    }),
    ("adhd_habit_event", "friction"): frozenset({
        "", "start", "decision", "sustain", "finish", "emotion",
        "environment",
    }),
    ("adhd_journal", "entry_type"): frozenset({
        "capture", "daily_page", "friction", "weekly_review", "freewrite",
    }),
    ("schema_path", "phase"): frozenset({
        "explore", "focus", "method", "work", "practice", "followup",
        "complete",
    }),
    ("schema_path", "status"): frozenset({
        "active", "paused", "stopped", "completed",
    }),
    ("schema_path", "practice_status"): frozenset({
        "none", "active", "invalidated",
    }),
    ("schema_path", "method_node_id"): frozenset({
        "",
        "young:method:imagery-rescripting",
        "young:method:chair-dialogue",
        "young:method:limited-reparenting",
    }),
    ("schema_path", "stage"): _SCHEMA_PATH_ALL_STAGES,
    ("schema_path", "step"): _SCHEMA_PATH_ALL_STEPS,
    ("schema_candidate", "status"): frozenset({
        "offered", "accepted", "rejected", "deferred", "selected",
        "invalidated",
    }),
    ("schema_candidate", "priority"): frozenset({
        "now", "later", "not_now",
    }),
    ("schema_focus_check", "fit"): frozenset({
        "yes", "partial", "no",
    }),
    ("schema_focus_check", "authored_by"): frozenset({"user"}),
    ("schema_step", "stage"): _SCHEMA_PATH_ALL_STAGES,
    ("schema_step", "step"): _SCHEMA_PATH_ALL_STEPS,
    ("schema_step", "status"): frozenset({
        "pending", "active", "completed", "skipped", "paused",
        "invalidated",
    }),
    ("schema_origin", "confidence"): frozenset({
        "reported", "uncertain", "unknown",
    }),
    ("schema_origin", "authored_by"): frozenset({"user"}),
    ("schema_origin", "status"): frozenset({"active", "invalidated"}),
    ("schema_growth", "status"): frozenset({"active", "invalidated"}),
    ("schema_growth", "environment_status"): frozenset({
        "none", "active", "invalidated",
    }),
    ("schema_healthy_adult", "source"): frozenset({"user"}),
    ("schema_healthy_adult", "status"): frozenset({
        "active", "invalidated",
    }),
    ("schema_transfer", "authored_by"): frozenset({"user"}),
    ("schema_transfer", "status"): frozenset({"active", "invalidated"}),
    ("schema_message_meta", "kind"): frozenset({
        "technique", "map_update", "candidate", "progress",
    }),
    ("schema_message_meta", "status"): frozenset({
        "active", "undone", "private", "invalidated",
    }),
}
_BOOLEAN_INTEGER_FIELDS = frozenset({
    "ended", "source_mode", "safety_hold", "approved", "sensitive",
    "safety_ok", "precheck_done", "schema_mode_enabled",
    "schema_clinical_sync_enabled", "share_with_coach", "resume_required",
    "confirmed",
})
_RATING_FIELDS = frozenset({
    "mood", "energy", "happiness", "anxiety", "mood_start", "mood_end",
    "energy_start", "anxiety_start", "intensity_limit", "burden",
    "baseline_burden", "changed_burden",
})
_INTEGER_FIELDS = _BOOLEAN_INTEGER_FIELDS | _RATING_FIELDS | frozenset({
    "available_minutes", "target_per_week", "effort_minutes",
    "path_sequence", "flow_version", "revision", "sort_order",
    "baseline_burden", "changed_burden", "age_reported", "stage_age",
    "seq", "clinical_generation", "schema_clinical_sync_generation",
})
_REAL_FIELDS = frozenset({"review_after", "scheduled_for"})
_TIMESTAMP_FIELDS = frozenset({
    "created", "updated", "approved_at", "archived_at", "last_reviewed_at",
    "started_at", "completed_at", "closed_at", "skipped_at",
    "invalidated_at",
})
_LONG_TEXT_FIELDS = frozenset({
    "content", "draft", "approved_content", "summary", "helpful",
    "next_step", "note", "focus", "avoid_topics",
    "focus_evidence", "evidence", "impact", "variable_text",
    "changed_scenario", "scene", "unmet_need", "then_response",
    "now_response", "difference", "environment_before",
    "environment_rescripted", "healthy_adult_words", "trigger_text",
    "healthy_adult_response", "planned_action", "support_choice",
    "predicted_result", "observed_result",
})

_ADHD_EVENT_SYNC_STATUSES = frozenset({
    "done", "partial", "skipped", "cancelled_user", "suppressed_safety",
})

_SCHEMA_CLINICAL_RECORD_TYPES = frozenset({
    "schema_path", "schema_candidate", "schema_focus_check", "schema_step",
    "schema_origin", "schema_growth", "schema_healthy_adult",
    "schema_transfer", "schema_message_meta",
})


@dataclass(frozen=True)
class RecordSpec:
    table: str
    fields: tuple[str, ...]
    references: tuple[tuple[str, str, str], ...] = ()
    primary_key: str = "id"
    native_public_id: bool = False
    clinical_editable: bool = False
    immutable: bool = False
    timestamp_field: Optional[str] = None


# Keep the wire allowlist intentionally small and auditable. Derived artifacts,
# provider/runtime state, and background work queues do not belong here.
RECORD_TYPES = {
    "conversation": RecordSpec(
        "conversations",
        (
            "mode", "submode", "therapist", "title", "created", "updated",
            "ended", "members", "source_mode", "case_id", "safety_hold",
            "archived_at",
        ),
        (("source_public_id", "source", "conversation"),),
        native_public_id=True,
        timestamp_field="updated",
    ),
    "message": RecordSpec(
        "messages",
        ("role", "content", "created", "turn_pair_public_id"),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("reply_to_public_id", "reply_to", "message"),
        ),
        native_public_id=True,
        immutable=True,
        timestamp_field="created",
    ),
    "note": RecordSpec(
        "notes",
        (
            "mode", "therapist", "content", "created", "approved", "scope",
            "sensitive", "updated",
        ),
        (("conversation_public_id", "conv", "conversation"),),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "goal": RecordSpec(
        "goals",
        ("title", "status", "created", "updated"),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "checkin": RecordSpec(
        "checkins",
        ("mood", "energy", "happiness", "anxiety", "note", "created"),
        (("conversation_public_id", "conv", "conversation"),),
        clinical_editable=True,
        timestamp_field="created",
    ),
    "memory": RecordSpec(
        "memories",
        (
            "therapist", "kind", "content", "approved", "scope",
            "sensitive", "created", "updated",
        ),
        (("conversation_public_id", "source_conv", "conversation"),),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "session_summary": RecordSpec(
        "session_summaries",
        (
            "draft", "approved_content", "status", "created", "approved_at",
            "updated",
        ),
        (("conversation_public_id", "conv", "conversation"),),
        primary_key="conv",
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "session_meta": RecordSpec(
        "session_meta",
        (
            "focus", "mood_start", "mood_end", "summary", "helpful",
            "next_step", "energy_start", "anxiety_start",
            "available_minutes", "intensity_limit", "avoid_topics",
            "preferred_pace", "safety_ok", "precheck_done",
            "schema_mode_enabled", "schema_clinical_sync_enabled", "updated",
            "schema_clinical_sync_generation",
        ),
        (("conversation_public_id", "conv", "conversation"),),
        primary_key="conv",
        clinical_editable=True,
        timestamp_field="updated",
    ),
    # User-authored routine definitions can move between paired devices, but
    # reminder rows, scheduled messages, jobs and native alarm ownership never
    # enter this projection.
    "adhd_habit": RecordSpec(
        "adhd_habits",
        (
            "title", "cue", "tiny_action", "target_per_week",
            "preferred_days_json", "reminder_local_time", "timezone",
            "status", "review_after", "last_reviewed_at", "created",
            "updated",
        ),
        (("conversation_public_id", "source_conv", "conversation"),),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    # Only terminal activity history crosses the wire. Active/scheduled rows
    # remain on their delivery device so a peer cannot duplicate, reschedule,
    # or leave behind an operating-system alarm. Free-text event notes are
    # deliberately not part of the shared projection.
    "adhd_habit_event": RecordSpec(
        "adhd_habit_events",
        (
            "scheduled_for", "status", "effort_minutes", "friction",
            "started_at", "completed_at", "created", "updated",
        ),
        (("habit_public_id", "habit", "adhd_habit"),),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    # Journal text is fail-closed: only an explicit non-sensitive entry which
    # the user also opted to share with the coach is eligible. Private/default
    # entries never receive a sync identity.
    "adhd_journal": RecordSpec(
        "adhd_journal_entries",
        (
            "entry_type", "content", "share_with_coach", "sensitive",
            "created", "updated",
        ),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("habit_public_id", "habit", "adhd_habit"),
            ("event_public_id", "event", "adhd_habit_event"),
        ),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    # Schema Path v4/v5 shares only explicitly approved, source-bound state
    # required to identify the chat flow.  Claim FKs, prompt journals, private
    # practice JSON and local technique pointers are intentionally omitted.
    "schema_path": RecordSpec(
        "schema_paths",
        (
            "therapist", "path_sequence", "phase", "status",
            "clinical_generation", "flow_version", "stage", "step", "pause_reason",
            "resume_required", "focus_candidate_public_id",
            "focus_schema_key", "focus_mode_key", "focus_label",
            "focus_evidence", "focus_source_user_public_id",
            "focus_source_assistant_public_id", "method_node_id",
            "practice_status", "revision", "created", "updated", "closed_at",
        ),
        (("conversation_public_id", "conv", "conversation"),),
        native_public_id=True,
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "schema_candidate": RecordSpec(
        "schema_candidate_queue",
        (
            "schema_key", "mode_key", "evidence", "burden", "impact",
            "clinical_generation", "priority", "status", "sort_order", "revision", "created",
            "updated",
        ),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("path_public_id", "path", "schema_path"),
            ("source_user_message_public_id", "source_user_message",
             "message"),
            ("source_assistant_message_public_id",
             "source_assistant_message", "message"),
        ),
        native_public_id=True,
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "schema_focus_check": RecordSpec(
        "schema_focus_checks",
        (
            "baseline_burden", "variable_text", "changed_scenario",
            "changed_burden", "fit", "confirmed", "authored_by",
            "revision", "created", "updated",
        ),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("path_public_id", "path", "schema_path"),
            ("candidate_public_id", "candidate_queue", "schema_candidate"),
            ("source_user_message_public_id", "source_user_message",
             "message"),
            ("source_assistant_message_public_id",
             "source_assistant_message", "message"),
        ),
        native_public_id=True,
        clinical_editable=True,
        timestamp_field="updated",
    ),
    # payload_json can contain local, experiential or model-derived details;
    # only the durable state and exact message lineage are projected.
    "schema_step": RecordSpec(
        "schema_path_steps",
        (
            "stage", "step", "status", "revision", "created", "updated",
            "completed_at", "skipped_at", "invalidated_at",
        ),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("path_public_id", "path", "schema_path"),
            ("source_user_message_public_id", "source_user_message",
             "message"),
            ("source_assistant_message_public_id",
             "source_assistant_message", "message"),
        ),
        native_public_id=True,
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "schema_origin": RecordSpec(
        "schema_origin",
        (
            "mode_key", "age_reported", "age_range", "scene",
            "unmet_need", "confidence", "authored_by", "status",
            "created", "updated",
        ),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("path_public_id", "path", "schema_path"),
            ("source_user_message_public_id", "source_user_message",
             "message"),
            ("source_assistant_message_public_id",
             "source_assistant_message", "message"),
        ),
        native_public_id=True,
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "schema_growth": RecordSpec(
        "schema_growth",
        (
            "mode_key", "stage_age", "stage_label", "then_response",
            "now_response", "difference", "environment_before",
            "environment_rescripted", "healthy_adult_words", "seq",
            "status", "environment_status", "created", "updated",
        ),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("path_public_id", "path", "schema_path"),
            ("source_user_message_public_id", "source_user_message",
             "message"),
            ("source_assistant_message_public_id",
             "source_assistant_message", "message"),
            ("environment_source_user_message_public_id",
             "environment_source_user_message", "message"),
            ("environment_source_assistant_message_public_id",
             "environment_source_assistant_message", "message"),
        ),
        native_public_id=True,
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "schema_healthy_adult": RecordSpec(
        "healthy_adult_marks",
        ("source", "evidence", "status", "created", "invalidated_at"),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("path_public_id", "path", "schema_path"),
            ("source_message_public_id", "source_message", "message"),
            ("source_assistant_message_public_id",
             "source_assistant_message", "message"),
        ),
        native_public_id=True,
        clinical_editable=True,
        immutable=True,
        timestamp_field="created",
    ),
    "schema_transfer": RecordSpec(
        "schema_transfer_records",
        (
            "trigger_text", "healthy_adult_response", "planned_action",
            "support_choice", "predicted_result", "observed_result",
            "authored_by", "status", "created", "updated",
        ),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("path_public_id", "path", "schema_path"),
            ("source_user_message_public_id", "source_user_message",
             "message"),
            ("source_assistant_message_public_id",
             "source_assistant_message", "message"),
            ("trigger_source_user_message_public_id",
             "trigger_source_user_message", "message"),
            ("trigger_source_assistant_message_public_id",
             "trigger_source_assistant_message", "message"),
        ),
        native_public_id=True,
        clinical_editable=True,
        timestamp_field="updated",
    ),
    # Remote meta events are intentionally read-only: local artifact ids,
    # mutation actions and nested payloads never cross the wire.
    "schema_message_meta": RecordSpec(
        "message_meta_events",
        (
            "event_key", "clinical_generation", "step", "kind", "status",
            "title", "summary",
            "artifact_type", "artifact_public_id", "created", "updated",
            "invalidated_at",
        ),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("message_public_id", "message", "message"),
            ("source_user_message_public_id", "source_user_message",
             "message"),
            ("source_assistant_message_public_id",
             "source_assistant_message", "message"),
            ("path_public_id", "path", "schema_path"),
        ),
        native_public_id=True,
        clinical_editable=True,
        timestamp_field="updated",
    ),
}

_DEPENDENCY_ORDER = {
    "conversation": 0,
    "message": 1,
    "note": 1,
    "checkin": 1,
    "memory": 1,
    "session_summary": 1,
    "session_meta": 1,
    "goal": 0,
    "adhd_habit": 1,
    "adhd_habit_event": 2,
    "adhd_journal": 3,
    "schema_path": 2,
    "schema_candidate": 3,
    "schema_focus_check": 4,
    "schema_step": 3,
    "schema_origin": 3,
    "schema_growth": 3,
    "schema_healthy_adult": 3,
    "schema_transfer": 3,
    "schema_message_meta": 4,
}

# Provenance/context links can outlive their target in legacy databases.  A
# deleted source session or replied-to message must not prevent the surviving
# record from being enrolled in sync; it is transferred with that optional
# link cleared.
_OPTIONAL_REFERENCES = frozenset({
    ("conversation", "source"),
    ("message", "reply_to"),
    ("checkin", "conv"),
    ("memory", "source_conv"),
    ("adhd_journal", "habit"),
    ("adhd_journal", "event"),
    ("schema_candidate", "path"),
    ("schema_step", "source_user_message"),
    ("schema_step", "source_assistant_message"),
    ("schema_origin", "source_user_message"),
    ("schema_origin", "source_assistant_message"),
    ("schema_growth", "source_user_message"),
    ("schema_growth", "source_assistant_message"),
    ("schema_growth", "environment_source_user_message"),
    ("schema_growth", "environment_source_assistant_message"),
    ("schema_message_meta", "path"),
})

# These records are logical singletons under one conversation.  Older builds
# assigned a random shadow public id, so two devices could independently own
# the same one-per-conversation row under different ids.  SQLite would then
# reject the second insert (notes.conv UNIQUE / session_* primary key).  A
# deterministic identity derived from the already-stable conversation id
# makes that natural key explicit on the wire.
_CONVERSATION_SINGLETON_TYPES = frozenset({
    "note", "session_summary", "session_meta",
})
_SYNC_EXCLUSION_REASONS = frozenset({
    "guest_scope", "orphan_parent", "policy_withdrawn",
    "identity_migrated",
})

# Protocol v8 synchronizes the small approved-only record types above after a
# separate per-device clinical-sync confirmation.  Everything in this set is
# still forbidden from the wire, including raw hypotheses/evidence, provider
# state, request journals, prechecks and technique transcripts.
DEVICE_LOCAL_CLINICAL_TABLES = frozenset({
    "psych_observations", "psych_claims", "psych_claim_evidence",
    "psych_claim_history", "schema_path_events", "schema_path_techniques",
    "schema_path_checkpoints", "schema_path_method_choices",
    "schema_variable_trials", "schema_origin_answers",
    "schema_v5_technique_sessions", "schema_v5_technique_turns",
    "schema_v5_integration_answers",
    "schema_clinical_sync_events", "schema_path_sync_conflicts",
    "technique_runs", "technique_checkpoints", "imagery_runs",
    "imagery_steps", "chair_runs", "chair_participants", "chair_turns",
})


class SyncError(ValueError):
    """The caller supplied an invalid or unsafe sync operation."""


class ClinicalSyncConfirmationRequired(SyncError):
    """Live Schema content is pending explicit consent on this device."""


class ClinicalSyncSafetyPause(SyncError):
    """Live Schema content must wait while this conversation is held."""


class _MissingDependency(Exception):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _row_dict(row) -> dict:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(
        "PRAGMA table_info({})".format(table)).fetchall()}


def _validate_device_id(device_id: str) -> str:
    if not isinstance(device_id, str) or not _DEVICE_ID_RE.fullmatch(device_id):
        raise SyncError("invalid device id")
    return device_id


def _validate_public_id(public_id: str) -> str:
    if not isinstance(public_id, str) or not _PUBLIC_ID_RE.fullmatch(public_id):
        raise SyncError("invalid public id")
    return public_id


def _new_public_id() -> str:
    return uuid.uuid4().hex


def _canonical_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _payload_hash(payload, deleted_at=None) -> str:
    content = {"deleted_at": deleted_at, "payload": payload}
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def _timestamp_order_key(value: object) -> tuple[int, str]:
    """Return a timezone-normalized, deterministic timestamp sort key.

    Older databases contain both SQLite-style naive timestamps and ISO-8601
    timestamps with offsets.  Treat naive values as UTC, normalize aware
    values to UTC, and retain a deterministic fallback for legacy strings
    which ``datetime`` cannot parse.  Causal ancestry is evaluated before this
    key, so a real child remains newer even when one device's wall clock moves
    backwards.
    """
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        normalized = parsed.astimezone(timezone.utc).isoformat(
            timespec="microseconds")
        return (1, normalized)
    except (TypeError, ValueError, OverflowError):
        # Wire validation already bounds this string.  The fallback exists for
        # historical local metadata and remains identical on every platform.
        return (0, text)


def _record_order_key(record: dict) -> tuple:
    """Total order used only for genuinely concurrent logical versions.

    Causal ancestry is handled before this function.  For two genuinely
    concurrent branches the user's logical row timestamp is the closest
    available meaning of "the latest edit"; a later safety scan must not win
    merely because it noticed an older row after the other device did.  The
    revision, device id and payload digest are deterministic tie-breakers.
    """
    payload = record.get("payload")
    logical_timestamp = None
    if isinstance(payload, dict):
        spec = RECORD_TYPES.get(record.get("record_type"))
        candidates = (
            (spec.timestamp_field if spec is not None else None),
            "updated", "created", "completed_at",
        )
        for field in candidates:
            if field and payload.get(field):
                logical_timestamp = payload[field]
                break
    return (
        _timestamp_order_key(
            record.get("deleted_at") or logical_timestamp
            or record.get("updated_at")),
        int(record.get("revision") or 0),
        str(record.get("origin_device_id") or ""),
        _payload_hash(record.get("payload"), record.get("deleted_at")),
    )


def _migrate_legacy_message_change_payloads(
        conn: sqlite3.Connection) -> int:
    """Add the v7 empty pair default to queued pre-pair message revisions.

    ``sync_changes`` is a delivery queue, not the authoritative message row.
    Preserve every event/cursor/version field and every existing payload key.
    When the exact live shadow still maps to the same physical message, copy
    its canonical pair proof; otherwise use the additive legacy empty value.
    A later refresh still emits a causal revision when the physical payload
    hash changed during server backfill.
    """
    if not _table_exists(conn, "sync_changes"):
        return 0
    migrated = 0
    for row in conn.execute(
            "SELECT cursor,public_id,payload_json FROM sync_changes "
            "WHERE record_type='message' AND deleted_at IS NULL "
            "AND payload_json IS NOT NULL ORDER BY cursor").fetchall():
        try:
            payload = json.loads(row[2])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if (not isinstance(payload, dict)
                or "turn_pair_public_id" in payload):
            continue
        current = conn.execute(
            "SELECT m.turn_pair_public_id FROM sync_records r "
            "JOIN messages m ON m.id=r.local_id "
            "AND m.public_id=r.public_id WHERE r.record_type='message' "
            "AND r.public_id=? AND r.deleted_at IS NULL",
            (row[1],),
        ).fetchone() if _table_exists(conn, "messages") else None
        current_pair = str(current[0] or "") if current else ""
        payload["turn_pair_public_id"] = (
            current_pair
            if _TURN_PAIR_PUBLIC_ID_RE.fullmatch(current_pair) else ""
        )
        conn.execute(
            "UPDATE sync_changes SET payload_json=? WHERE cursor=?",
            (_canonical_json(payload), int(row[0])),
        )
        migrated += 1
    return migrated


def _sync_tables(conn: sqlite3.Connection) -> None:
    # ``executescript`` commits any transaction that was already open.  These
    # helpers are also called from application delete transactions, so an
    # implicit commit here would turn an all-or-nothing batch delete into a
    # partial delete.  Execute each DDL statement through the caller's
    # connection instead; SQLite then keeps schema creation/migration inside
    # the same transaction.
    statements = (
        """CREATE TABLE IF NOT EXISTS sync_records(
            record_type TEXT NOT NULL,
            local_id INTEGER,
            public_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            origin_device_id TEXT NOT NULL,
            parent_origin_device_id TEXT,
            parent_revision INTEGER,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            payload_hash TEXT NOT NULL,
            PRIMARY KEY(record_type, public_id)
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS sync_records_local
            ON sync_records(record_type, local_id)
            WHERE local_id IS NOT NULL""",
        """CREATE TABLE IF NOT EXISTS sync_changes(
            cursor INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            record_type TEXT NOT NULL,
            public_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            origin_device_id TEXT NOT NULL,
            parent_origin_device_id TEXT,
            parent_revision INTEGER,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            payload_json TEXT
        )""",
        """CREATE INDEX IF NOT EXISTS sync_changes_cursor
            ON sync_changes(cursor)""",
        """CREATE TABLE IF NOT EXISTS sync_seen_versions(
            record_type TEXT NOT NULL,
            public_id TEXT NOT NULL,
            origin_device_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            seen_at TEXT NOT NULL,
            PRIMARY KEY(
                record_type, public_id, origin_device_id, revision)
        )""",
        """CREATE TABLE IF NOT EXISTS sync_conflicts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            public_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            local_json TEXT NOT NULL,
            incoming_json TEXT NOT NULL,
            incoming_event_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            resolved_at TEXT,
            resolution TEXT
        )""",
        """CREATE INDEX IF NOT EXISTS sync_conflicts_open
            ON sync_conflicts(status, id)""",
        """CREATE TABLE IF NOT EXISTS sync_peer_cursors(
            peer_device_id TEXT PRIMARY KEY,
            remote_cursor INTEGER NOT NULL DEFAULT 0,
            acknowledged_local_cursor INTEGER NOT NULL DEFAULT 0,
            offered_local_cursor INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS sync_excluded_records(
            record_type TEXT NOT NULL,
            public_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            excluded_at TEXT NOT NULL,
            PRIMARY KEY(record_type, public_id)
        )""",
        """CREATE TABLE IF NOT EXISTS sync_identity_aliases(
            record_type TEXT NOT NULL,
            alias_public_id TEXT NOT NULL,
            canonical_public_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(record_type, alias_public_id)
        )""",
    )
    for statement in statements:
        conn.execute(statement)
    peer_columns = _columns(conn, "sync_peer_cursors")
    if "acknowledged_local_cursor" not in peer_columns:
        conn.execute(
            "ALTER TABLE sync_peer_cursors ADD COLUMN "
            "acknowledged_local_cursor INTEGER NOT NULL DEFAULT 0")
    if "offered_local_cursor" not in peer_columns:
        conn.execute(
            "ALTER TABLE sync_peer_cursors ADD COLUMN "
            "offered_local_cursor INTEGER NOT NULL DEFAULT 0")
    if _table_exists(conn, "messages"):
        message_columns = _columns(conn, "messages")
        if "turn_pair_public_id" not in message_columns:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN turn_pair_public_id "
                "TEXT NOT NULL DEFAULT ''")
        if "role" in message_columns:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS messages_turn_pair_role "
                "ON messages(turn_pair_public_id,role) "
                "WHERE turn_pair_public_id<>''")
    _migrate_legacy_message_change_payloads(conn)


def _valid_metadata_public_id(value) -> Optional[str]:
    value = str(value or "")
    return value if _PUBLIC_ID_RE.fullmatch(value) else None


def _valid_local_id(value) -> Optional[int]:
    return value if type(value) is int and value > 0 else None


def _has_guest_scope(conn: sqlite3.Connection) -> bool:
    return (
        _table_exists(conn, "conversations")
        and "is_guest" in _columns(conn, "conversations")
    )


def _guest_derived_conversation_local_ids(
        conn: sqlite3.Connection) -> set[int]:
    """Return direct guest conversations and local derivation descendants."""
    if not _has_guest_scope(conn):
        return set()
    columns = _columns(conn, "conversations")
    has_source = "source" in columns
    rows = conn.execute(
        "SELECT id,is_guest{} FROM conversations ORDER BY id".format(
            ",source" if has_source else "")
    ).fetchall()
    guest_ids = {
        local_id for row in rows
        if (local_id := _valid_local_id(row[0])) is not None
        and bool(row[1])
    }
    if not has_source:
        return guest_ids
    # A supervision/derived conversation must not declassify guest content
    # merely because a legacy row forgot to copy its is_guest bit.
    pending = list(rows)
    while pending:
        next_pending = []
        progressed = False
        for row in pending:
            local_id = _valid_local_id(row[0])
            if local_id is None:
                continue
            source_id = row[2]
            if local_id in guest_ids:
                continue
            source_id = _valid_local_id(source_id)
            if source_id is not None and source_id in guest_ids:
                guest_ids.add(local_id)
                progressed = True
            else:
                next_pending.append(row)
        if not progressed:
            break
        pending = next_pending
    return guest_ids


def _is_guest_derived_local_row(
        conn: sqlite3.Connection, record_type: str, local_id: int,
        guest_conversation_ids: Optional[set[int]] = None,
        _seen: Optional[set[tuple[str, int]]] = None) -> bool:
    """Return whether an allowlisted physical row belongs to guest scope.

    Guest state is deliberately not a wire field.  A child is therefore
    classified through its physical conversation relation before any shadow
    record is created.  Legacy schemas without ``is_guest`` predate guest
    scope and remain compatible.
    """
    local_id = _valid_local_id(local_id)
    if (record_type not in RECORD_TYPES or local_id is None
            or not _has_guest_scope(conn)):
        return False
    identity = (record_type, local_id)
    seen = set() if _seen is None else _seen
    if identity in seen:
        return False
    seen.add(identity)
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        return False
    if guest_conversation_ids is None:
        guest_conversation_ids = _guest_derived_conversation_local_ids(conn)
    if record_type == "conversation":
        return local_id in guest_conversation_ids
    table_columns = _columns(conn, spec.table)
    # Keep the row-local bit as a second fail-closed boundary.  Current ADHD
    # writers copy conversation guest scope onto habit/journal rows, while
    # legacy/imported data may have an incomplete relation graph.
    if "is_guest" in table_columns:
        row = conn.execute(
            "SELECT is_guest FROM {} WHERE {}=?".format(
                spec.table, spec.primary_key),
            (local_id,),
        ).fetchone()
        if row is not None and bool(row[0]):
            return True
    for _, column, target_type in spec.references:
        if column not in table_columns:
            continue
        row = conn.execute(
            "SELECT {column} FROM {table} WHERE {primary}=?".format(
                table=spec.table, column=column,
                primary=spec.primary_key),
            (local_id,),
        ).fetchone()
        if row is None or row[0] is None:
            continue
        reference_id = _valid_local_id(row[0])
        if reference_id is None:
            continue
        if target_type == "conversation":
            if reference_id in guest_conversation_ids:
                return True
            continue
        if target_type in RECORD_TYPES and _is_guest_derived_local_row(
                conn, target_type, reference_id,
                guest_conversation_ids, seen):
            return True
    return False


def _public_ids_for_local_row(
        conn: sqlite3.Connection, record_type: str,
        local_id: int) -> set[str]:
    """Collect existing identities without assigning one to a guest row."""
    result = set()
    shadow = conn.execute(
        "SELECT public_id FROM sync_records "
        "WHERE record_type=? AND local_id=?",
        (record_type, local_id),
    ).fetchone()
    if shadow:
        value = _valid_metadata_public_id(shadow[0])
        if value:
            result.add(value)
    spec = RECORD_TYPES[record_type]
    if (spec.native_public_id and _table_exists(conn, spec.table)
            and "public_id" in _columns(conn, spec.table)):
        native = conn.execute(
            "SELECT public_id FROM {} WHERE {}=?".format(
                spec.table, spec.primary_key),
            (local_id,),
        ).fetchone()
        if native:
            value = _valid_metadata_public_id(native[0])
            if value:
                result.add(value)
    return result


def _required_local_reference_missing(
        conn: sqlite3.Connection, record_type: str,
        local_id: int,
        _seen: Optional[set[tuple[str, int]]] = None) -> bool:
    """Return whether a live row has lost a required local parent.

    Older asynchronous work could finish after its conversation had already
    been removed, leaving a message row whose required ``conv`` parent no
    longer exists. Such an orphan is still local application data, but it
    cannot form a valid logical sync record and must never block unrelated
    records from synchronizing.
    """
    if record_type not in RECORD_TYPES:
        return True
    identity = (record_type, int(local_id))
    seen = set() if _seen is None else _seen
    if identity in seen:
        return True
    seen.add(identity)
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        return False
    columns = _columns(conn, spec.table)
    for _, column, target_type in spec.references:
        if (record_type, column) in _OPTIONAL_REFERENCES:
            continue
        if column not in columns:
            return True
        value = conn.execute(
            "SELECT {column} FROM {table} WHERE {primary}=?".format(
                column=column, table=spec.table,
                primary=spec.primary_key),
            (local_id,),
        ).fetchone()
        if value is None or value[0] is None:
            return True
        reference_id = _valid_local_id(value[0])
        if reference_id is None:
            return True
        target = RECORD_TYPES[target_type]
        if not _table_exists(conn, target.table):
            return True
        target_row = conn.execute(
                    "SELECT 1 FROM {table} WHERE {primary}=?".format(
                        table=target.table, primary=target.primary_key),
                    (reference_id,),
                ).fetchone()
        if target_row is None or _required_local_reference_missing(
                conn, target_type, reference_id, set(seen)):
            return True
        if (_local_row_has_excluded_identity(
                conn, target_type, reference_id)
                or _local_row_has_tombstoned_identity(
                    conn, target_type, reference_id)):
            return True
    return False


def _local_row_has_excluded_identity(
        conn: sqlite3.Connection, record_type: str,
        local_id: int, *, reasons: Optional[set[str]] = None) -> bool:
    identities = _public_ids_for_local_row(
        conn, record_type, local_id)
    if not identities:
        return False
    placeholders = ",".join("?" for _ in identities)
    parameters = [record_type, *sorted(identities)]
    reason_sql = ""
    if reasons:
        valid_reasons = sorted(
            reason for reason in reasons
            if reason in _SYNC_EXCLUSION_REASONS)
        if not valid_reasons:
            return False
        reason_sql = " AND reason IN ({})".format(
            ",".join("?" for _ in valid_reasons))
        parameters.extend(valid_reasons)
    return conn.execute(
        "SELECT 1 FROM sync_excluded_records WHERE record_type=? "
        "AND public_id IN ({}){} LIMIT 1".format(
            placeholders, reason_sql),
        parameters,
    ).fetchone() is not None


def _local_row_has_tombstoned_identity(
        conn: sqlite3.Connection, record_type: str,
        local_id: int) -> bool:
    identities = _public_ids_for_local_row(
        conn, record_type, local_id)
    if not identities:
        return False
    placeholders = ",".join("?" for _ in identities)
    return conn.execute(
        "SELECT 1 FROM sync_records WHERE record_type=? "
        "AND public_id IN ({}) AND deleted_at IS NOT NULL LIMIT 1".format(
            placeholders),
        (record_type, *sorted(identities)),
    ).fetchone() is not None


def _wire_payload_references_guest(
        record_type: str, payload,
        guest_identities: set[tuple[str, str]]) -> bool:
    if record_type not in RECORD_TYPES or not isinstance(payload, dict):
        return False
    for payload_name, _, target_type in RECORD_TYPES[record_type].references:
        reference = payload.get(payload_name)
        if (isinstance(reference, str)
                and (target_type, reference) in guest_identities):
            return True
    return False


def _wire_payload_references_hard_deleted_parent(
        conn: sqlite3.Connection, record_type: str, payload) -> bool:
    """Detect a required parent whose local logical identity is deleted."""
    if record_type not in RECORD_TYPES or not isinstance(payload, dict):
        return False
    for payload_name, column, target_type in RECORD_TYPES[record_type].references:
        if (record_type, column) in _OPTIONAL_REFERENCES:
            continue
        reference = payload.get(payload_name)
        if not isinstance(reference, str):
            continue
        tombstone = conn.execute(
            "SELECT 1 FROM sync_records WHERE record_type=? AND public_id=? "
            "AND deleted_at IS NOT NULL",
            (target_type, reference),
        ).fetchone()
        excluded = conn.execute(
            "SELECT 1 FROM sync_excluded_records WHERE record_type=? "
            "AND public_id=? AND reason IN ('guest_scope','orphan_parent')",
            (target_type, reference),
        ).fetchone()
        if tombstone is not None or excluded is not None:
            return True
    return False


def _decode_stored_record(value) -> Optional[dict]:
    if not isinstance(value, str) or not value:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _exclude_sync_identities(
        conn: sqlite3.Connection,
        identities: set[tuple[str, str]], *, reason: str) -> dict:
    """Persist content-free exclusions and erase every sync audit payload."""
    if reason not in _SYNC_EXCLUSION_REASONS:
        raise SyncError("invalid sync exclusion reason")
    valid = sorted({
        (record_type, public_id)
        for record_type, public_id in identities
        if record_type in RECORD_TYPES
        and _valid_metadata_public_id(public_id) is not None
    })
    result = {
        "identities": len(valid), "records": 0, "changes": 0,
        "seen_versions": 0, "conflicts": 0,
    }
    stamp = _utcnow()
    for record_type, public_id in valid:
        conn.execute(
            "INSERT OR IGNORE INTO sync_excluded_records("
            "record_type,public_id,reason,excluded_at) VALUES(?,?,?,?)",
            (record_type, public_id, reason, stamp),
        )
        result["conflicts"] += max(0, int(conn.execute(
            "DELETE FROM sync_conflicts WHERE record_type=? AND public_id=?",
            (record_type, public_id),
        ).rowcount))
        result["changes"] += max(0, int(conn.execute(
            "DELETE FROM sync_changes WHERE record_type=? AND public_id=?",
            (record_type, public_id),
        ).rowcount))
        result["seen_versions"] += max(0, int(conn.execute(
            "DELETE FROM sync_seen_versions "
            "WHERE record_type=? AND public_id=?",
            (record_type, public_id),
        ).rowcount))
        result["records"] += max(0, int(conn.execute(
            "DELETE FROM sync_records WHERE record_type=? AND public_id=?",
            (record_type, public_id),
        ).rowcount))
        if _table_exists(conn, "sync_identity_aliases"):
            conn.execute(
                "DELETE FROM sync_identity_aliases WHERE record_type=? "
                "AND (alias_public_id=? OR canonical_public_id=?)",
                (record_type, public_id, public_id),
            )
    return result


def _mark_sync_exclusion(
        conn: sqlite3.Connection, record_type: str,
        public_id: str, *, reason: str) -> None:
    if reason not in _SYNC_EXCLUSION_REASONS:
        raise SyncError("invalid sync exclusion reason")
    if (record_type not in RECORD_TYPES
            or _valid_metadata_public_id(public_id) is None):
        return
    conn.execute(
        "INSERT OR IGNORE INTO sync_excluded_records("
        "record_type,public_id,reason,excluded_at) VALUES(?,?,?,?)",
        (record_type, public_id, reason, _utcnow()),
    )


def _exclude_guest_identities(
        conn: sqlite3.Connection,
        identities: set[tuple[str, str]]) -> dict:
    return _exclude_sync_identities(
        conn, identities, reason="guest_scope")


def _exclude_orphan_local_row(
        conn: sqlite3.Connection, record_type: str,
        local_id: int, device_id: str) -> dict:
    raw_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND local_id=? "
        "AND deleted_at IS NULL",
        (record_type, local_id),
    ).fetchone()
    if raw_meta is not None:
        public_id = str(raw_meta["public_id"])
        _record_missing_local_delete(
            conn, _row_dict(raw_meta), device_id, _utcnow())
        _mark_sync_exclusion(
            conn, record_type, public_id, reason="orphan_parent")
        return {"tombstoned": 1, "excluded": 0}
    identities = {
        (record_type, public_id)
        for public_id in _public_ids_for_local_row(
            conn, record_type, local_id)
    }
    public_ids = sorted(public_id for _, public_id in identities)
    if public_ids:
        placeholders = ",".join("?" for _ in public_ids)
        tombstone = conn.execute(
            "SELECT 1 FROM sync_records WHERE record_type=? "
            "AND public_id IN ({}) AND deleted_at IS NOT NULL LIMIT 1".format(
                placeholders),
            (record_type, *public_ids),
        ).fetchone()
        if tombstone is not None:
            return {"tombstoned": 0, "excluded": 0}
    result = _exclude_sync_identities(
        conn, identities, reason="orphan_parent")
    return {"tombstoned": 0, "excluded": result["identities"]}


def _guest_sync_identities(
        conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """Find live and legacy sync identities known to belong to guest scope."""
    identities = {
        (str(row[0]), str(row[1]))
        for row in conn.execute(
            "SELECT record_type,public_id FROM sync_excluded_records "
            "WHERE reason='guest_scope'"
        ).fetchall()
        if row[0] in RECORD_TYPES
        and _valid_metadata_public_id(row[1]) is not None
    }
    if _has_guest_scope(conn):
        guest_conversation_ids = _guest_derived_conversation_local_ids(conn)
        # Discover the whole physical allowlisted graph recursively.  This is
        # intentionally broader than direct conversation children: an ADHD
        # event references a habit, and a journal may reference either one.
        for record_type in sorted(
                RECORD_TYPES, key=lambda value: _DEPENDENCY_ORDER[value]):
            spec = RECORD_TYPES[record_type]
            if not _table_exists(conn, spec.table):
                continue
            for row in conn.execute(
                    "SELECT {0} FROM {1} ORDER BY {0}".format(
                        spec.primary_key, spec.table)).fetchall():
                local_id = _valid_local_id(row[0])
                if local_id is None:
                    continue
                if _is_guest_derived_local_row(
                        conn, record_type, local_id,
                        guest_conversation_ids):
                    identities.update(
                        (record_type, public_id)
                        for public_id in _public_ids_for_local_row(
                            conn, record_type, local_id)
                    )

    if not identities:
        # The common main-profile path avoids scanning the potentially large
        # delivery/conflict history.
        return identities

    # Legacy content can reveal a child relationship after the physical row
    # has disappeared.  Parse both delivery rows and conflict snapshots before
    # deleting anything so all content-bearing copies are removed together.
    # Iterate to a fixed point because change/conflict rows are not guaranteed
    # to be ordered parent-before-child.
    change_rows = conn.execute(
        "SELECT record_type,public_id,payload_json FROM sync_changes"
    ).fetchall()
    conflict_rows = conn.execute(
        "SELECT record_type,public_id,local_json,incoming_json "
        "FROM sync_conflicts"
    ).fetchall()
    progressed = True
    while progressed:
        progressed = False
        for row in change_rows:
            record_type = str(row[0] or "")
            public_id = _valid_metadata_public_id(row[1])
            identity = (record_type, public_id)
            if (not public_id or record_type not in RECORD_TYPES
                    or identity in identities):
                continue
            payload = _decode_stored_record(row[2])
            if _wire_payload_references_guest(
                    record_type, payload, identities):
                identities.add(identity)
                progressed = True

        excluded_public_ids = {value for _, value in identities}
        for row in conflict_rows:
            row_type = str(row[0] or "")
            row_public_id = _valid_metadata_public_id(row[1])
            identity = (row_type, row_public_id)
            if (not row_public_id or row_type not in RECORD_TYPES
                    or identity in identities):
                continue
            guest = False
            for raw in (row[2], row[3]):
                stored = _decode_stored_record(raw)
                if stored:
                    stored_type = str(
                        stored.get("record_type") or row_type)
                    if _wire_payload_references_guest(
                            stored_type, stored.get("payload"), identities):
                        guest = True
                elif isinstance(raw, str) and any(
                        value in raw for value in excluded_public_ids):
                    # Malformed legacy JSON is never exported, but
                    # conservative substring matching keeps possible guest
                    # text out of repair and diagnostic paths as well.
                    guest = True
            if guest:
                identities.add(identity)
                progressed = True
    return identities


def scrub_guest_sync_state(conn: sqlite3.Connection) -> dict:
    """Remove guest-scope shadow state without touching application rows.

    The only retained values are opaque public ids in the exclusion table.
    They prevent a stale peer from reintroducing a record after the local
    guest conversation has already been physically deleted.
    """
    _sync_tables(conn)
    return _exclude_guest_identities(conn, _guest_sync_identities(conn))


def _incoming_is_excluded_guest(
        conn: sqlite3.Connection, incoming: dict) -> bool:
    record_type = incoming["record_type"]
    public_id = incoming["public_id"]
    rows = conn.execute(
        "SELECT record_type,public_id,reason FROM sync_excluded_records"
    ).fetchall()
    excluded_identities = {
        (str(row[0]), str(row[1])) for row in rows
        if row[0] in RECORD_TYPES
        and _valid_metadata_public_id(row[1]) is not None
    }
    if (record_type, public_id) in excluded_identities:
        return True
    # Guest/orphan ancestry is a hard graph boundary.  A policy-withdrawn
    # record, however, may be an optional reference (for example a completed
    # ADHD journal referring to a now device-local event); it must not make an
    # independently consented child disappear.
    for reason in ("guest_scope", "orphan_parent"):
        reason_identities = {
            (str(row[0]), str(row[1])) for row in rows
            if row[2] == reason and row[0] in RECORD_TYPES
            and _valid_metadata_public_id(row[1]) is not None
        }
        if _wire_payload_references_guest(
                record_type, incoming.get("payload"), reason_identities):
            _exclude_sync_identities(
                conn, {(record_type, public_id)}, reason=reason)
            return True
    if _wire_payload_references_hard_deleted_parent(
            conn, record_type, incoming.get("payload")):
        _exclude_sync_identities(
            conn, {(record_type, public_id)}, reason="orphan_parent")
        return True
    return False


def _scrub_hard_deleted_parent_payloads(conn: sqlite3.Connection) -> dict:
    """Redact queued child payloads whose required parent is tombstoned."""
    identities = set()
    for row in conn.execute(
            "SELECT record_type,public_id,payload_json FROM sync_changes "
            "WHERE deleted_at IS NULL AND payload_json IS NOT NULL"):
        record_type = str(row[0])
        payload = _decode_stored_record(row[2])
        if _wire_payload_references_hard_deleted_parent(
                conn, record_type, payload):
            identities.add((record_type, str(row[1])))
    for row in conn.execute(
            "SELECT record_type,public_id,incoming_json FROM sync_conflicts"):
        record_type = str(row[0])
        incoming = _decode_stored_record(row[2])
        payload = incoming.get("payload") if incoming else None
        if _wire_payload_references_hard_deleted_parent(
                conn, record_type, payload):
            identities.add((record_type, str(row[1])))
    if not identities:
        return {
            "identities": 0, "records": 0, "changes": 0,
            "seen_versions": 0, "conflicts": 0,
        }
    return _exclude_sync_identities(
        conn, identities, reason="orphan_parent")


def _projection_payload_allowed(record_type: str, payload) -> bool:
    """Return whether a live policy-bounded payload is eligible for the wire.

    This policy is deliberately duplicated at enrollment, delivery and
    inbound validation boundaries.  A missing/malformed consent flag is a
    denial, never an implicit opt-in.
    """
    if record_type == "adhd_habit_event":
        return (
            isinstance(payload, dict)
            and payload.get("status") in _ADHD_EVENT_SYNC_STATUSES
        )
    if record_type == "adhd_journal":
        return (
            isinstance(payload, dict)
            and type(payload.get("share_with_coach")) is int
            and payload.get("share_with_coach") == 1
            and type(payload.get("sensitive")) is int
            and payload.get("sensitive") == 0
        )
    if record_type == "schema_path":
        return (
            isinstance(payload, dict)
            and payload.get("therapist") == "young"
            and payload.get("flow_version") in (4, 5)
            and type(payload.get("path_sequence")) is int
            and payload.get("path_sequence") > 0
        )
    if record_type in _SCHEMA_CLINICAL_RECORD_TYPES:
        if not isinstance(payload, dict):
            return False
        if record_type == "schema_candidate" and payload.get(
                "status") == "invalidated":
            return False
        if record_type == "schema_step" and payload.get(
                "status") == "invalidated":
            return False
        if record_type == "schema_message_meta" and payload.get(
                "status") != "active":
            return False
    return True


def _schema_path_state_is_valid_for_flow(
        flow_version: object, stage: object, step: object,
        method_node_id: object = "") -> bool:
    """Return whether one shared path head belongs to its exact flow graph."""
    if type(flow_version) is not int:
        return False
    mapping = _SCHEMA_PATH_STEP_STAGE_BY_FLOW.get(flow_version)
    methods = _SCHEMA_PATH_METHODS_BY_FLOW.get(flow_version)
    if mapping is None or methods is None:
        return False
    return (
        isinstance(stage, str)
        and isinstance(step, str)
        and mapping.get(step) == stage
        and isinstance(method_node_id, str)
        and method_node_id in methods
    )


def _schema_step_state_is_valid_for_flow(
        flow_version: object, stage: object, step: object) -> bool:
    if type(flow_version) is not int:
        return False
    mapping = _SCHEMA_PATH_STEP_STAGE_BY_FLOW.get(flow_version)
    return bool(
        mapping is not None
        and isinstance(stage, str)
        and isinstance(step, str)
        and mapping.get(step) == stage
    )


def _schema_source_pair_is_safe(
        conn: sqlite3.Connection, conv_id: int,
        user_id: Optional[int], assistant_id: Optional[int]) -> bool:
    """Validate one authoritative completed pair without reading its text."""
    if user_id is None and assistant_id is None:
        return True
    user_id = _valid_local_id(user_id)
    assistant_id = _valid_local_id(assistant_id)
    if user_id is None or assistant_id is None:
        return False
    # Releasing a hold changes current conversation capability, not the
    # historical safety classification of its source turn.  Keep this exact
    # with server.completed_normal_turn: any retained safety event makes that
    # pair permanently ineligible as clinical derivation.
    messages = conn.execute(
        "SELECT u.id,a.id FROM messages u JOIN messages a ON a.conv=u.conv "
        "WHERE u.conv=? AND u.id=? AND a.id=? AND u.role='user' "
        "AND a.role='assistant' AND u.delivery_status='completed' "
        "AND a.delivery_status='completed' "
        "AND u.turn_pair_public_id=a.turn_pair_public_id "
        "AND length(u.turn_pair_public_id)=32 "
        "AND u.turn_pair_public_id NOT GLOB '*[^0-9a-f]*' "
        "AND NOT EXISTS(SELECT 1 FROM safety_events s WHERE s.conv=u.conv "
        "AND s.source_message=u.id)",
        (conv_id, user_id, assistant_id),
    ).fetchone()
    if messages is None:
        return False
    request = conn.execute(
        "SELECT status,assistant_message FROM chat_requests WHERE conv=? "
        "AND user_message=? ORDER BY created DESC,rowid DESC LIMIT 1",
        (conv_id, user_id),
    ).fetchone()
    if request is not None:
        return (request[0] == "completed"
                and int(request[1] or 0) == assistant_id)
    # chat_requests are delivery/job state and deliberately never sync.  A
    # receiving device can still verify the content-free turn-pair identity
    # and both exact live message shadows.  Local row ids and batch order are
    # not source chronology, so neither adjacency nor numeric order is used.
    synced = conn.execute(
        "SELECT 1 FROM messages u JOIN messages a ON a.conv=u.conv "
        "JOIN sync_records su ON su.record_type='message' "
        "AND su.local_id=u.id AND su.public_id=u.public_id "
        "AND su.deleted_at IS NULL "
        "JOIN sync_records sa ON sa.record_type='message' "
        "AND sa.local_id=a.id AND sa.public_id=a.public_id "
        "AND sa.deleted_at IS NULL "
        "WHERE u.conv=? AND u.id=? AND a.id=? AND u.role='user' "
        "AND a.role='assistant' AND u.delivery_status='completed' "
        "AND a.delivery_status='completed' "
        "AND u.turn_pair_public_id=a.turn_pair_public_id "
        "AND length(u.turn_pair_public_id)=32 "
        "AND u.turn_pair_public_id NOT GLOB '*[^0-9a-f]*' "
        "AND NOT EXISTS(SELECT 1 FROM chat_requests r "
        "WHERE r.conv=u.conv AND r.user_message=u.id) "
        "AND NOT EXISTS(SELECT 1 FROM safety_events s "
        "WHERE s.conv=u.conv AND s.source_message=u.id)",
        (conv_id, user_id, assistant_id),
    ).fetchone()
    return synced is not None


def _schema_message_has_safe_completed_pair(
        conn: sqlite3.Connection, conv_id: int, message_id: object) -> bool:
    message_id = _valid_local_id(message_id)
    if message_id is None:
        return False
    row = conn.execute(
        "SELECT assistant_message FROM chat_requests WHERE conv=? "
        "AND user_message=? AND status='completed'",
        (conv_id, message_id),
    ).fetchone()
    return bool(row and _schema_source_pair_is_safe(
        conn, conv_id, message_id, row[0]))


def _schema_local_projection_allowed(
        conn: sqlite3.Connection, record_type: str, local_id: int) -> bool:
    """Enforce local consent and exact safe lineage for Schema v4/v5 rows."""
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        return False
    row = conn.execute(
        "SELECT * FROM {} WHERE {}=?".format(spec.table, spec.primary_key),
        (local_id,),
    ).fetchone()
    if row is None:
        return False
    values = _row_dict(row)
    conv_id = _valid_local_id(values.get("conv"))
    if conv_id is None:
        return False
    conv = conn.execute(
        "SELECT is_guest FROM conversations WHERE id=?", (conv_id,)
    ).fetchone()
    consent = conn.execute(
        "SELECT schema_clinical_sync_enabled,"
        "schema_clinical_sync_initialized,"
        "schema_clinical_sync_generation FROM session_meta WHERE conv=?",
        (conv_id,),
    ).fetchone()
    if (not conv or int(conv[0] or 0) != 0 or not consent
            or int(consent[0] or 0) != 1 or int(consent[1] or 0) != 1):
        return False
    generation = int(consent[2] or 0)
    if generation < 1:
        return False
    path_flow_version = None
    if record_type in {
            "schema_path", "schema_candidate", "schema_message_meta"}:
        if int(values.get("clinical_generation") or 0) != generation:
            return False
    if record_type == "schema_path":
        path_flow_version = int(values.get("flow_version") or 0)
    else:
        path_id = _valid_local_id(values.get("path"))
        if path_id is None and record_type not in {
                "schema_candidate", "schema_message_meta"}:
            return False
        if path_id is not None:
            path_state = conn.execute(
                "SELECT clinical_generation,flow_version FROM schema_paths "
                "WHERE id=? AND conv=?", (path_id, conv_id),
            ).fetchone()
            if (not path_state
                    or int(path_state[0] or 0) != generation
                    or int(path_state[1] or 0) not in (4, 5)):
                return False
            path_flow_version = int(path_state[1])
    if record_type == "schema_path":
        if (values.get("therapist") != "young"
                or int(values.get("path_sequence") or 0) < 1
                or not _schema_path_state_is_valid_for_flow(
                    path_flow_version, values.get("stage"),
                    values.get("step"),
                    str(values.get("method_node_id") or ""))):
            return False
        user_public = str(values.get("focus_source_user_public_id") or "")
        assistant_public = str(
            values.get("focus_source_assistant_public_id") or "")
        if not user_public and not assistant_public:
            return True
        refs = conn.execute(
            "SELECT u.id,a.id FROM messages u JOIN messages a ON a.conv=u.conv "
            "WHERE u.conv=? AND u.public_id=? AND u.role='user' "
            "AND a.public_id=? AND a.role='assistant'",
            (conv_id, user_public, assistant_public),
        ).fetchone()
        return bool(refs and _schema_source_pair_is_safe(
            conn, conv_id, refs[0], refs[1]))
    if record_type == "schema_candidate" and values.get(
            "status") == "invalidated":
        return False
    # The v5 graph has no burden/focus rating record.  Retain this type only
    # for an existing v4 path; a malformed v5 attachment is fail-closed.
    if record_type == "schema_focus_check" and path_flow_version == 5:
        return False
    if record_type == "schema_step" and values.get(
            "status") == "invalidated":
        return False
    if record_type == "schema_step" and not \
            _schema_step_state_is_valid_for_flow(
                path_flow_version, values.get("stage"), values.get("step")):
        return False
    if record_type == "schema_message_meta" and values.get(
            "status") != "active":
        return False
    if record_type == "schema_healthy_adult":
        return _schema_source_pair_is_safe(
            conn, conv_id, values.get("source_message"),
            values.get("source_assistant_message"))
    if record_type == "schema_growth":
        environment_user = values.get("environment_source_user_message")
        environment_assistant = values.get(
            "environment_source_assistant_message")
        if (environment_user is None) != (environment_assistant is None):
            return False
        if (values.get("environment_status") == "active"
                and environment_user is None):
            return False
        if (environment_user is not None and not _schema_source_pair_is_safe(
                conn, conv_id, environment_user, environment_assistant)):
            return False
    if record_type == "schema_transfer" and not (
            _schema_source_pair_is_safe(
                conn, conv_id, values.get("trigger_source_user_message"),
                values.get("trigger_source_assistant_message"))):
        return False
    user_id = values.get("source_user_message")
    assistant_id = values.get("source_assistant_message")
    if record_type == "schema_step" and user_id is None and assistant_id is None:
        return True
    return _schema_source_pair_is_safe(
        conn, conv_id, user_id, assistant_id)


def _message_is_tus_local_only(
        conn: sqlite3.Connection, local_id: int) -> bool:
    """Keep conversational TUS bubbles and their reply pairs device-local.

    TUS planner state is intentionally absent from ``RECORD_TYPES``.  Its
    deterministic chat bubbles therefore cannot safely cross the wire either:
    doing so would disclose a partial transcript with no durable planner state
    on the peer.  A normal chat reply which explicitly points at such a bubble,
    plus the assistant half of that reply pair, is excluded as well so sync
    never emits an orphan ``reply_to`` dependency.
    """
    if (not _table_exists(conn, "adhd_tus_chat_turns")
            or not _table_exists(conn, "messages")):
        return False
    ledger_columns = _columns(conn, "adhd_tus_chat_turns")
    message_columns = _columns(conn, "messages")
    if not {"prompt_message", "answer_message"}.issubset(ledger_columns):
        # Once the provenance table exists, an unreadable provenance shape is
        # a privacy boundary failure.  Fail closed until schema repair.
        return True
    if not {"id", "reply_to", "turn_pair_public_id"}.issubset(
            message_columns):
        return True
    if conn.execute(
            "SELECT 1 FROM messages WHERE id=?", (local_id,)
    ).fetchone() is None:
        return False
    return conn.execute(
        "WITH RECURSIVE related(id,reply_to,pair_id) AS ("
        "SELECT id,reply_to,COALESCE(turn_pair_public_id,'') FROM messages "
        "WHERE id=? UNION "
        "SELECT m.id,m.reply_to,COALESCE(m.turn_pair_public_id,'') "
        "FROM messages m JOIN related r ON m.id=r.reply_to UNION "
        "SELECT m.id,m.reply_to,COALESCE(m.turn_pair_public_id,'') "
        "FROM messages m JOIN related r ON r.pair_id<>'' "
        "AND m.turn_pair_public_id=r.pair_id) "
        "SELECT 1 FROM related r JOIN adhd_tus_chat_turns t "
        "ON t.prompt_message=r.id OR t.answer_message=r.id LIMIT 1",
        (local_id,),
    ).fetchone() is not None


def _local_projection_allowed(
        conn: sqlite3.Connection, record_type: str, local_id: int) -> bool:
    """Evaluate wire eligibility directly from the authoritative local row."""
    if (record_type == "message"
            and _message_is_tus_local_only(conn, local_id)):
        return False
    if record_type in _SCHEMA_CLINICAL_RECORD_TYPES:
        return _schema_local_projection_allowed(
            conn, record_type, local_id)
    if record_type not in {"adhd_habit_event", "adhd_journal"}:
        return True
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        return False
    columns = _columns(conn, spec.table)
    if record_type == "adhd_habit_event":
        if "status" not in columns:
            return False
        row = conn.execute(
            "SELECT status FROM {} WHERE {}=?".format(
                spec.table, spec.primary_key),
            (local_id,),
        ).fetchone()
        return bool(row and row[0] in _ADHD_EVENT_SYNC_STATUSES)
    required = {"share_with_coach", "sensitive", "is_guest"}
    if not required.issubset(columns):
        return False
    row = conn.execute(
        "SELECT share_with_coach,sensitive,is_guest FROM {} WHERE {}=?".format(
            spec.table, spec.primary_key),
        (local_id,),
    ).fetchone()
    return bool(
        row
        and type(row[0]) is int and int(row[0]) == 1
        and type(row[1]) is int and int(row[1]) == 0
        and type(row[2]) is int and int(row[2]) == 0
    )


def _record_projection_withdrawal(
        conn: sqlite3.Connection, meta: dict, device_id: str,
        stamp: Optional[str] = None) -> Optional[dict]:
    """Publish a payload-free tombstone while retaining the private row.

    The shadow is detached from ``local_id``.  If the user explicitly makes
    the row eligible again later, it can be enrolled under a fresh identity;
    the old identity remains a scrubbed tombstone and cannot revive text on a
    stale peer.
    """
    if meta.get("deleted_at") is not None or meta.get("local_id") is None:
        return None
    deleted_at = str(stamp or _utcnow())
    revision = int(meta["revision"]) + 1
    record = {
        "record_type": meta["record_type"],
        "public_id": meta["public_id"],
        "revision": revision,
        "origin_device_id": device_id,
        "parent_origin_device_id": meta["origin_device_id"],
        "parent_revision": meta["revision"],
        "updated_at": deleted_at,
        "deleted_at": deleted_at,
        "payload": None,
    }
    cursor = conn.execute(
        "UPDATE sync_records SET local_id=NULL,revision=?,"
        "origin_device_id=?,parent_origin_device_id=?,parent_revision=?,"
        "updated_at=?,deleted_at=?,payload_hash=? "
        "WHERE record_type=? AND public_id=? AND local_id IS NOT NULL "
        "AND deleted_at IS NULL",
        (
            revision, device_id, meta["origin_device_id"], meta["revision"],
            deleted_at, deleted_at, _payload_hash(None, deleted_at),
            meta["record_type"], meta["public_id"],
        ),
    )
    if cursor.rowcount != 1:
        return None
    _mark_seen(conn, record)
    _append_change(conn, record)
    _scrub_deleted_record_history(
        conn, record["record_type"], record["public_id"])
    _mark_sync_exclusion(
        conn, record["record_type"], record["public_id"],
        reason="policy_withdrawn")
    return record


def _redact_ineligible_module_records(
        conn: sqlite3.Connection, device_id: str) -> dict:
    """Withdraw shared module rows whose explicit eligibility was revoked."""
    device_id = _validate_device_id(device_id)
    _sync_tables(conn)
    result = {"redacted": 0, "missing": 0}
    stamp = _utcnow()
    for record_type in (
            "message", "adhd_habit_event", "adhd_journal",
            *_SCHEMA_CLINICAL_RECORD_TYPES):
        spec = RECORD_TYPES[record_type]
        if not _table_exists(conn, spec.table):
            continue
        rows = conn.execute(
            "SELECT * FROM sync_records WHERE record_type=? "
            "AND local_id IS NOT NULL AND deleted_at IS NULL "
            "ORDER BY local_id",
            (record_type,),
        ).fetchall()
        for raw_meta in rows:
            meta = _row_dict(raw_meta)
            exists = conn.execute(
                "SELECT 1 FROM {} WHERE {}=?".format(
                    spec.table, spec.primary_key),
                (meta["local_id"],),
            ).fetchone()
            if exists is None:
                _record_missing_local_delete(
                    conn, meta, device_id, stamp)
                result["missing"] += 1
                continue
            if _local_projection_allowed(
                    conn, record_type, int(meta["local_id"])):
                continue
            if _record_projection_withdrawal(
                    conn, meta, device_id, stamp) is not None:
                result["redacted"] += 1
    return result


def initialize_sync(
        conn: sqlite3.Connection,
        device_id: str,
        *,
        bootstrap: bool = True,
) -> dict:
    """Create additive shadow tables and optionally publish legacy rows."""
    device_id = _validate_device_id(device_id)
    _sync_tables(conn)
    privacy = scrub_all_deleted_history(conn)
    hard_parent = _scrub_hard_deleted_parent_payloads(conn)
    projection = _redact_ineligible_module_records(conn, device_id)
    counts = {
        "bootstrapped": 0,
        "identity_migrated": 0,
        "tables_missing": [],
        "scrubbed": privacy["records"],
        "guest_excluded": privacy["guest_identities"],
        "orphan_excluded": 0,
        "policy_excluded": 0,
        "policy_redacted": projection["redacted"],
        "hard_parent_excluded": hard_parent["identities"],
        "auto_merged": 0,
        "deferred_applied": 0,
    }
    if not bootstrap:
        return counts
    guest_conversation_ids = _guest_derived_conversation_local_ids(conn)
    for record_type in sorted(
            RECORD_TYPES, key=lambda value: _DEPENDENCY_ORDER[value]):
        spec = RECORD_TYPES[record_type]
        if not _table_exists(conn, spec.table):
            counts["tables_missing"].append(spec.table)
            continue
        for row in conn.execute(
            "SELECT {0} FROM {1} ORDER BY {0}".format(
                spec.primary_key, spec.table)
        ).fetchall():
            local_id = row[0]
            if _is_guest_derived_local_row(
                    conn, record_type, int(local_id),
                    guest_conversation_ids):
                counts["guest_excluded"] += 1
                continue
            if _local_row_has_excluded_identity(
                    conn, record_type, int(local_id),
                    reasons={"guest_scope", "orphan_parent"}):
                counts["orphan_excluded"] += 1
                continue
            if _required_local_reference_missing(
                    conn, record_type, int(local_id)):
                _exclude_orphan_local_row(
                    conn, record_type, int(local_id), device_id)
                counts["orphan_excluded"] += 1
                continue
            if not _local_projection_allowed(
                    conn, record_type, int(local_id)):
                counts["policy_excluded"] += 1
                continue
            if _migrate_conversation_singleton_identity(
                    conn, record_type, int(local_id), device_id):
                counts["identity_migrated"] += 1
                if conn.execute(
                        "SELECT 1 FROM {} WHERE {}=?".format(
                            spec.table, spec.primary_key),
                        (local_id,),
                ).fetchone() is None:
                    continue
            exists = conn.execute(
                "SELECT 1 FROM sync_records "
                "WHERE record_type=? AND local_id=?",
                (record_type, local_id),
            ).fetchone()
            if not exists:
                record_local_change(
                    conn, record_type, local_id, device_id,
                    updated_at=_row_timestamp(
                        conn, record_type, local_id) or _utcnow(),
                    _guest_checked=True,
                )
                counts["bootstrapped"] += 1
    _scrub_ineligible_stored_clinical_conflicts(conn)
    counts["auto_merged"] = _auto_merge_legacy_conflicts(conn)
    counts["deferred_applied"] = _retry_deferred_conflicts(conn)
    return counts


def _row_timestamp(
        conn: sqlite3.Connection, record_type: str, local_id: int
) -> Optional[str]:
    spec = RECORD_TYPES[record_type]
    cols = _columns(conn, spec.table)
    candidates = [
        value for value in (spec.timestamp_field, "updated", "created")
        if value and value in cols
    ]
    if not candidates:
        return None
    select = ",".join(candidates)
    row = conn.execute(
        "SELECT {} FROM {} WHERE {}=?".format(
            select, spec.table, spec.primary_key),
        (local_id,),
    ).fetchone()
    if not row:
        return None
    for value in row:
        if value:
            return str(value)
    return None


def _public_id_for_local(
        conn: sqlite3.Connection,
        record_type: str,
        local_id: Optional[int],
) -> Optional[str]:
    if local_id is None:
        return None
    row = conn.execute(
        "SELECT public_id FROM sync_records "
        "WHERE record_type=? AND local_id=?",
        (record_type, local_id),
    ).fetchone()
    if row:
        return row[0]
    spec = RECORD_TYPES[record_type]
    if spec.native_public_id and _table_exists(conn, spec.table):
        native = conn.execute(
            "SELECT public_id FROM {} WHERE {}=?".format(
                spec.table, spec.primary_key),
            (local_id,),
        ).fetchone()
        if native and native[0]:
            return str(native[0])
    return None


def _canonical_adhd_days(value) -> str:
    if not isinstance(value, str):
        raise SyncError("preferred ADHD days must be JSON text")
    # Older ADHD drafts could persist an empty text value, while the public
    # server representation has always treated that value as no preferred
    # days.  Preserve the physical row and normalize only its wire projection.
    value = value.strip()
    try:
        decoded = [] if not value else json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise SyncError("invalid preferred ADHD days") from None
    if not isinstance(decoded, list):
        raise SyncError("invalid preferred ADHD days")
    days = []
    for item in decoded:
        if type(item) is not int or not 0 <= item <= 6 or item in days:
            raise SyncError("invalid preferred ADHD days")
        days.append(item)
    return _canonical_json(sorted(days))


def _conversation_singleton_public_id(
        record_type: str, conversation_public_id: str) -> str:
    """Return the stable wire identity for a one-row-per-session record."""
    if record_type not in _CONVERSATION_SINGLETON_TYPES:
        raise SyncError("record is not a conversation singleton")
    conversation_public_id = _validate_public_id(conversation_public_id)
    seed = "divan-conversation-singleton-v1\n{}\n{}".format(
        record_type, conversation_public_id)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return "singleton-{}:{}".format(record_type, digest)


def _stable_conversation_singleton_public_id(
        conn: sqlite3.Connection, record_type: str, values: dict) -> str:
    conversation_id = _valid_local_id(values.get("conv"))
    if conversation_id is None:
        raise SyncError("singleton conversation is missing")
    conversation_public_id = _public_id_for_local(
        conn, "conversation", conversation_id)
    if conversation_public_id is None:
        raise SyncError("referenced conversation row has no sync identity")
    return _conversation_singleton_public_id(
        record_type, conversation_public_id)


def _remember_singleton_alias(
        conn: sqlite3.Connection, record_type: str,
        alias_public_id: str, canonical_public_id: str) -> None:
    if record_type not in _CONVERSATION_SINGLETON_TYPES:
        raise SyncError("invalid singleton alias type")
    alias_public_id = _validate_public_id(alias_public_id)
    canonical_public_id = _validate_public_id(canonical_public_id)
    if alias_public_id == canonical_public_id:
        return
    canonical_pattern = r"singleton-{}:[0-9a-f]{{64}}".format(
        re.escape(record_type))
    if not re.fullmatch(canonical_pattern, canonical_public_id):
        raise SyncError("invalid singleton canonical identity")
    # A deterministic id is never a legacy alias.  Rejecting a mismatched
    # canonical-looking source prevents a stale or hostile peer from using a
    # tombstone belonging to one conversation to delete another singleton.
    if alias_public_id.startswith("singleton-"):
        raise SyncError("singleton canonical identity cannot be re-aliased")
    alias_head = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    ).fetchone()
    if alias_head is not None:
        alias_meta = _row_dict(alias_head)
        if (alias_meta.get("deleted_at") is None
                and alias_meta.get("local_id") is not None):
            spec = RECORD_TYPES[record_type]
            physical = conn.execute(
                "SELECT 1 FROM {} WHERE {}=?".format(
                    spec.table, spec.primary_key),
                (int(alias_meta["local_id"]),),
            ).fetchone()
            if physical is not None:
                _, alias_payload = _serialize_row(
                    conn, record_type, int(alias_meta["local_id"]))
                alias_expected = _conversation_singleton_public_id(
                    record_type, alias_payload["conversation_public_id"])
                if alias_expected != canonical_public_id:
                    raise SyncError(
                        "singleton alias belongs to another record")
    existing = conn.execute(
        "SELECT canonical_public_id FROM sync_identity_aliases "
        "WHERE record_type=? AND alias_public_id=?",
        (record_type, alias_public_id),
    ).fetchone()
    if existing is not None and str(existing[0]) != canonical_public_id:
        raise SyncError("singleton alias has a conflicting natural key")
    conn.execute(
        "INSERT OR IGNORE INTO sync_identity_aliases("
        "record_type,alias_public_id,canonical_public_id,created_at) "
        "VALUES(?,?,?,?)",
        (
            record_type, alias_public_id, canonical_public_id, _utcnow(),
        ),
    )


def _singleton_alias_target(
        conn: sqlite3.Connection, record_type: str,
        public_id: str) -> Optional[str]:
    if record_type not in _CONVERSATION_SINGLETON_TYPES:
        return None
    row = conn.execute(
        "SELECT canonical_public_id FROM sync_identity_aliases "
        "WHERE record_type=? AND alias_public_id=?",
        (record_type, public_id),
    ).fetchone()
    return str(row[0]) if row else None


def _stable_adhd_event_public_id(
        conn: sqlite3.Connection, values: dict) -> str:
    habit_id = values.get("habit")
    scheduled_for = values.get("scheduled_for")
    if type(habit_id) is not int or habit_id < 1:
        raise SyncError("ADHD event habit is missing")
    habit_public_id = _public_id_for_local(
        conn, "adhd_habit", habit_id)
    if habit_public_id is None:
        raise SyncError("referenced adhd_habit row has no sync identity")
    if (isinstance(scheduled_for, bool)
            or type(scheduled_for) not in (int, float)
            or not math.isfinite(float(scheduled_for))):
        raise SyncError("invalid ADHD event time")
    seed = "{}\n{}".format(
        habit_public_id, format(float(scheduled_for), ".17g"))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return "adhd-event:{}".format(digest)


def _serialize_row(
        conn: sqlite3.Connection, record_type: str, local_id: int
) -> tuple[str, dict]:
    if record_type not in RECORD_TYPES:
        raise SyncError("record type is not syncable")
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        raise SyncError("record table does not exist")
    row = conn.execute(
        "SELECT * FROM {} WHERE {}=?".format(
            spec.table, spec.primary_key), (local_id,)
    ).fetchone()
    if not row:
        raise SyncError("record does not exist")
    values = _row_dict(row)

    meta = conn.execute(
        "SELECT public_id FROM sync_records "
        "WHERE record_type=? AND local_id=?",
        (record_type, local_id),
    ).fetchone()
    public_id = str(meta[0]) if meta else ""
    if spec.native_public_id and not public_id:
        native = str(values.get("public_id") or "")
        if native:
            public_id = native
    collision = None
    if public_id:
        collision = conn.execute(
            "SELECT local_id FROM sync_records "
            "WHERE record_type=? AND public_id=?",
            (record_type, public_id),
        ).fetchone()
    if (
        not public_id
        or not _PUBLIC_ID_RE.fullmatch(public_id)
        or (collision and collision[0] != local_id)
    ):
        public_id = ""
    if not public_id:
        if record_type == "adhd_habit_event":
            public_id = _stable_adhd_event_public_id(conn, values)
            # A payload-free tombstone is final for its wire identity.  If a
            # previously withdrawn event becomes eligible again (or the user
            # deliberately recreates one at the same scheduled time), enroll
            # it under a fresh identity instead of reviving an identity which
            # may represent a physical deletion on another device.
            if conn.execute(
                    "SELECT 1 FROM sync_records WHERE record_type=? "
                    "AND public_id=?",
                    (record_type, public_id),
            ).fetchone() is not None:
                public_id = _new_public_id()
        elif record_type in _CONVERSATION_SINGLETON_TYPES:
            public_id = _stable_conversation_singleton_public_id(
                conn, record_type, values)
        else:
            public_id = _new_public_id()
        if spec.native_public_id and "public_id" in values:
            conn.execute(
                "UPDATE {} SET public_id=? WHERE {}=?".format(
                    spec.table, spec.primary_key),
                (public_id, local_id),
            )

    payload = {
        field: values[field]
        for field in spec.fields if field in values
    }
    if (record_type == "adhd_habit"
            and "preferred_days_json" in payload):
        payload["preferred_days_json"] = _canonical_adhd_days(
            payload["preferred_days_json"])
    for payload_name, column, target_type in spec.references:
        if column not in values:
            continue
        raw_reference_id = values[column]
        if raw_reference_id is None:
            payload[payload_name] = None
            continue
        reference_id = _valid_local_id(raw_reference_id)
        optional = (record_type, column) in _OPTIONAL_REFERENCES
        if reference_id is None:
            if optional:
                payload[payload_name] = None
                continue
            raise SyncError(
                "referenced {} row has no sync identity".format(
                    target_type))
        if optional and (
                _required_local_reference_missing(
                    conn, target_type, reference_id)
                or _local_row_has_excluded_identity(
                    conn, target_type, reference_id)
                or _local_row_has_tombstoned_identity(
                    conn, target_type, reference_id)):
            payload[payload_name] = None
            continue
        reference_public_id = _public_id_for_local(
            conn, target_type, reference_id)
        if reference_public_id is None:
            if optional:
                payload[payload_name] = None
                continue
            raise SyncError(
                "referenced {} row has no sync identity".format(target_type))
        payload[payload_name] = reference_public_id
    return public_id, payload


def _event_id(record: dict) -> str:
    return "{}:{}:{}:{}".format(
        record["origin_device_id"], record["record_type"],
        record["public_id"], record["revision"],
    )


def _append_change(conn: sqlite3.Connection, record: dict) -> None:
    if (record.get("deleted_at") is None
            and not _projection_payload_allowed(
                record.get("record_type"), record.get("payload"))):
        raise SyncError("record is excluded by local sync policy")
    conn.execute(
        "INSERT OR IGNORE INTO sync_changes("
        "event_id,record_type,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            _event_id(record), record["record_type"], record["public_id"],
            record["revision"], record["origin_device_id"],
            record.get("parent_origin_device_id"),
            record.get("parent_revision"), record["updated_at"],
            record.get("deleted_at"),
            None if record.get("payload") is None
            else _canonical_json(record["payload"]),
        ),
    )


def _mark_seen(conn: sqlite3.Connection, record: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sync_seen_versions("
        "record_type,public_id,origin_device_id,revision,seen_at)"
        " VALUES(?,?,?,?,?)",
        (
            record["record_type"], record["public_id"],
            record["origin_device_id"], record["revision"], _utcnow(),
        ),
    )


def _rewrite_singleton_conflicts(
        conn: sqlite3.Connection, record_type: str,
        alias_public_id: str, canonical_public_id: str) -> None:
    """Move an unresolved legacy singleton conflict without losing text."""
    rows = conn.execute(
        "SELECT * FROM sync_conflicts WHERE record_type=? AND public_id=? "
        "ORDER BY id",
        (record_type, alias_public_id),
    ).fetchall()
    for raw in rows:
        row = _row_dict(raw)
        try:
            local = json.loads(row["local_json"])
            incoming = json.loads(row["incoming_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            # A malformed legacy conflict cannot be made actionable.  Do not
            # copy its possibly sensitive raw JSON into another audit row.
            continue
        for record in (local, incoming):
            if isinstance(record, dict):
                record["public_id"] = canonical_public_id
                if record is incoming:
                    record["parent_origin_device_id"] = None
                    record["parent_revision"] = None
        if not isinstance(incoming, dict) or not {
                "origin_device_id", "revision"}.issubset(incoming):
            continue
        incoming_event_id = _event_id(incoming)
        conn.execute(
            "INSERT OR IGNORE INTO sync_conflicts("
            "record_type,public_id,reason,local_json,incoming_json,"
            "incoming_event_id,created_at,status,resolved_at,resolution) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                record_type, canonical_public_id, row["reason"],
                _canonical_json(local), _canonical_json(incoming),
                incoming_event_id, row["created_at"], row["status"],
                row["resolved_at"], row["resolution"],
            ),
        )
    conn.execute(
        "DELETE FROM sync_conflicts WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    )


def _migrate_conversation_singleton_identity(
        conn: sqlite3.Connection, record_type: str,
        local_id: int, device_id: str) -> bool:
    """Replace a random legacy shadow id with its deterministic natural id."""
    if record_type not in _CONVERSATION_SINGLETON_TYPES:
        return False
    spec = RECORD_TYPES[record_type]
    physical = conn.execute(
        "SELECT * FROM {} WHERE {}=?".format(
            spec.table, spec.primary_key),
        (local_id,),
    ).fetchone()
    if physical is None:
        return False
    canonical_public_id = _stable_conversation_singleton_public_id(
        conn, record_type, _row_dict(physical))
    raw_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND local_id=?",
        (record_type, local_id),
    ).fetchone()
    if raw_meta is None:
        canonical_raw = conn.execute(
            "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
            (record_type, canonical_public_id),
        ).fetchone()
        if canonical_raw is not None:
            canonical = _row_dict(canonical_raw)
            if canonical["deleted_at"] is not None:
                conn.execute(
                    "DELETE FROM {} WHERE {}=?".format(
                        spec.table, spec.primary_key),
                    (local_id,),
                )
                return True
            raise SyncError("singleton natural identity is already in use")
        return False
    meta = _row_dict(raw_meta)
    alias_public_id = str(meta["public_id"])
    _, payload = _serialize_row(conn, record_type, local_id)
    expected_public_id = _conversation_singleton_public_id(
        record_type, payload["conversation_public_id"])
    if expected_public_id != canonical_public_id:
        raise SyncError("singleton natural identity changed unexpectedly")
    if alias_public_id == canonical_public_id:
        return False
    _remember_singleton_alias(
        conn, record_type, alias_public_id, canonical_public_id)

    canonical_raw = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, canonical_public_id),
    ).fetchone()
    if canonical_raw is not None:
        canonical = _row_dict(canonical_raw)
        if canonical["deleted_at"] is not None:
            # The logical singleton was deleted on a peer.  Deletion is a
            # privacy boundary, so a legacy alias cannot revive it.
            conn.execute(
                "DELETE FROM {} WHERE {}=?".format(
                    RECORD_TYPES[record_type].table,
                    RECORD_TYPES[record_type].primary_key),
                (local_id,),
            )
            conn.execute(
                "DELETE FROM sync_changes WHERE record_type=? "
                "AND public_id=?",
                (record_type, alias_public_id),
            )
            conn.execute(
                "DELETE FROM sync_conflicts WHERE record_type=? "
                "AND public_id=?",
                (record_type, alias_public_id),
            )
            conn.execute(
                "DELETE FROM sync_seen_versions WHERE record_type=? "
                "AND public_id=?",
                (record_type, alias_public_id),
            )
            conn.execute(
                "DELETE FROM sync_records WHERE record_type=? "
                "AND public_id=?",
                (record_type, alias_public_id),
            )
            _mark_sync_exclusion(
                conn, record_type, alias_public_id,
                reason="identity_migrated")
            return True
        if canonical.get("local_id") == local_id:
            # Repair an interrupted older migration without changing content.
            conn.execute(
                "DELETE FROM sync_records WHERE record_type=? "
                "AND public_id=?",
                (record_type, alias_public_id),
            )
            _mark_sync_exclusion(
                conn, record_type, alias_public_id,
                reason="identity_migrated")
            return True
        raise SyncError("singleton natural identity is already in use")

    _validate_payload(record_type, payload)
    stamp = str(
        _row_timestamp(conn, record_type, local_id)
        or meta.get("updated_at") or _utcnow())
    canonical = {
        "record_type": record_type,
        "public_id": canonical_public_id,
        "revision": 1,
        "origin_device_id": device_id,
        "parent_origin_device_id": None,
        "parent_revision": None,
        "updated_at": stamp,
        "deleted_at": None,
        "payload": payload,
    }

    # Remove content-bearing delivery history for the retired alias.  Its
    # canonical live snapshot is appended first-class below; the content-free
    # alias table is sufficient to map a later legacy deletion.
    _rewrite_singleton_conflicts(
        conn, record_type, alias_public_id, canonical_public_id)
    conn.execute(
        "DELETE FROM sync_changes WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    )
    conn.execute(
        "DELETE FROM sync_seen_versions WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    )
    conn.execute(
        "DELETE FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    )
    conn.execute(
        "INSERT INTO sync_records("
        "record_type,local_id,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            record_type, local_id, canonical_public_id, 1, device_id,
            None, None, stamp, None, _payload_hash(payload),
        ),
    )
    _mark_seen(conn, canonical)
    _append_change(conn, canonical)
    _mark_sync_exclusion(
        conn, record_type, alias_public_id, reason="identity_migrated")
    return True


def _canonicalize_missing_singleton_delete(
        conn: sqlite3.Connection, meta: dict,
        device_id: str, deleted_at: str) -> Optional[dict]:
    """Promote an unhooked legacy singleton deletion to its natural id."""
    record_type = str(meta.get("record_type") or "")
    alias_public_id = str(meta.get("public_id") or "")
    if (record_type not in _CONVERSATION_SINGLETON_TYPES
            or meta.get("deleted_at") is not None):
        return None
    payload_row = conn.execute(
        "SELECT payload_json FROM sync_changes WHERE record_type=? "
        "AND public_id=? AND deleted_at IS NULL AND payload_json IS NOT NULL "
        "ORDER BY cursor DESC LIMIT 1",
        (record_type, alias_public_id),
    ).fetchone()
    payload = _decode_stored_record(payload_row[0]) if payload_row else None
    if not payload or not isinstance(
            payload.get("conversation_public_id"), str):
        return None
    try:
        canonical_public_id = _conversation_singleton_public_id(
            record_type, payload["conversation_public_id"])
    except SyncError:
        return None
    if canonical_public_id == alias_public_id:
        return None
    _remember_singleton_alias(
        conn, record_type, alias_public_id, canonical_public_id)
    canonical_raw = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, canonical_public_id),
    ).fetchone()
    canonical_meta = _row_dict(canonical_raw) if canonical_raw else None
    if canonical_meta and canonical_meta["deleted_at"] is not None:
        record = _record_from_meta(conn, canonical_meta)
    else:
        revision = int(canonical_meta["revision"]) + 1 if canonical_meta else 1
        record = {
            "record_type": record_type,
            "public_id": canonical_public_id,
            "revision": revision,
            "origin_device_id": device_id,
            "parent_origin_device_id": (
                canonical_meta["origin_device_id"] if canonical_meta else None),
            "parent_revision": (
                canonical_meta["revision"] if canonical_meta else None),
            "updated_at": deleted_at,
            "deleted_at": deleted_at,
            "payload": None,
        }
        conn.execute(
            "INSERT INTO sync_records("
            "record_type,local_id,public_id,revision,origin_device_id,"
            "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
            "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(record_type,public_id) DO UPDATE SET "
            "local_id=NULL,revision=excluded.revision,"
            "origin_device_id=excluded.origin_device_id,"
            "parent_origin_device_id=excluded.parent_origin_device_id,"
            "parent_revision=excluded.parent_revision,"
            "updated_at=excluded.updated_at,deleted_at=excluded.deleted_at,"
            "payload_hash=excluded.payload_hash",
            (
                record_type, None, canonical_public_id, revision, device_id,
                record["parent_origin_device_id"],
                record["parent_revision"], deleted_at, deleted_at,
                _payload_hash(None, deleted_at),
            ),
        )
        _mark_seen(conn, record)
        _append_change(conn, record)
        _scrub_deleted_record_history(
            conn, record_type, canonical_public_id)

    # The canonical tombstone is now the sole delivery history.  Retain only
    # the opaque alias mapping/exclusion for a stale legacy replay.
    conn.execute(
        "DELETE FROM sync_changes WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    )
    conn.execute(
        "DELETE FROM sync_conflicts WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    )
    conn.execute(
        "DELETE FROM sync_seen_versions WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    )
    conn.execute(
        "DELETE FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, alias_public_id),
    )
    _mark_sync_exclusion(
        conn, record_type, alias_public_id, reason="identity_migrated")
    return record


def _ensure_incoming_singleton_local_head(
        conn: sqlite3.Connection, incoming: dict, device_id: str) -> None:
    """Enroll/migrate a physical singleton before applying a peer snapshot."""
    if (incoming["record_type"] not in _CONVERSATION_SINGLETON_TYPES
            or incoming["deleted_at"] is not None
            or not isinstance(incoming.get("payload"), dict)):
        return
    conversation_public_id = incoming["payload"].get(
        "conversation_public_id")
    conversation_id = _find_local_id(
        conn, "conversation", conversation_public_id)
    if conversation_id is None:
        return
    spec = RECORD_TYPES[incoming["record_type"]]
    row = conn.execute(
        "SELECT {} FROM {} WHERE conv=?".format(
            spec.primary_key, spec.table),
        (conversation_id,),
    ).fetchone()
    if row is None:
        return
    local_id = int(row[0])
    _migrate_conversation_singleton_identity(
        conn, incoming["record_type"], local_id, device_id)
    if conn.execute(
            "SELECT 1 FROM {} WHERE {}=?".format(
                spec.table, spec.primary_key),
            (local_id,),
    ).fetchone() is None:
        return
    raw_meta = conn.execute(
        "SELECT 1 FROM sync_records WHERE record_type=? AND local_id=?",
        (incoming["record_type"], local_id),
    ).fetchone()
    if raw_meta is None:
        record_local_change(
            conn, incoming["record_type"], local_id, device_id,
            updated_at=_row_timestamp(
                conn, incoming["record_type"], local_id) or _utcnow(),
            _guest_checked=True,
        )
        return


def _ensure_singleton_tombstone_local_head(
        conn: sqlite3.Connection, incoming: dict, device_id: str) -> None:
    """Find a legacy physical singleton for a payload-free canonical delete."""
    record_type = incoming["record_type"]
    if (record_type not in _CONVERSATION_SINGLETON_TYPES
            or incoming["deleted_at"] is None):
        return
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        return
    for row in conn.execute(
            "SELECT {} FROM {} ORDER BY {}".format(
                spec.primary_key, spec.table, spec.primary_key)):
        local_id = int(row[0])
        try:
            physical = conn.execute(
                "SELECT * FROM {} WHERE {}=?".format(
                    spec.table, spec.primary_key),
                (local_id,),
            ).fetchone()
            if physical is None:
                continue
            desired = _stable_conversation_singleton_public_id(
                conn, record_type, _row_dict(physical))
        except SyncError:
            continue
        if desired != incoming["public_id"]:
            continue
        _migrate_conversation_singleton_identity(
            conn, record_type, local_id, device_id)
        if conn.execute(
                "SELECT 1 FROM {} WHERE {}=?".format(
                    spec.table, spec.primary_key),
                (local_id,),
        ).fetchone() is None:
            return
        raw_meta = conn.execute(
            "SELECT 1 FROM sync_records WHERE record_type=? AND local_id=?",
            (record_type, local_id),
        ).fetchone()
        if raw_meta is None:
            record_local_change(
                conn, record_type, local_id, device_id,
                updated_at=_row_timestamp(
                    conn, record_type, local_id) or _utcnow(),
                _guest_checked=True,
            )
        return


def _canonicalize_singleton_incoming(
        conn: sqlite3.Connection, incoming: dict,
        device_id: str) -> tuple[dict, Optional[dict]]:
    """Normalize a legacy singleton id before identity lookup or conflicts."""
    record_type = incoming["record_type"]
    if record_type not in _CONVERSATION_SINGLETON_TYPES:
        return incoming, None
    original_public_id = incoming["public_id"]
    canonical_public_id = None
    if incoming["deleted_at"] is None:
        payload = incoming.get("payload")
        if not isinstance(payload, dict):
            return incoming, None
        canonical_public_id = _conversation_singleton_public_id(
            record_type, payload["conversation_public_id"])
        if original_public_id != canonical_public_id:
            _remember_singleton_alias(
                conn, record_type, original_public_id,
                canonical_public_id)
        _ensure_incoming_singleton_local_head(conn, incoming, device_id)
    else:
        canonical_public_id = _singleton_alias_target(
            conn, record_type, original_public_id)
        _ensure_singleton_tombstone_local_head(
            conn, incoming, device_id)
    if not canonical_public_id or original_public_id == canonical_public_id:
        return incoming, None

    normalized = dict(incoming)
    normalized["public_id"] = canonical_public_id
    normalized["parent_origin_device_id"] = None
    normalized["parent_revision"] = None

    # If a payload-free deletion of the old id arrived first, learning the
    # natural key later must promote that deletion rather than revive text.
    alias_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=? "
        "AND deleted_at IS NOT NULL",
        (record_type, original_public_id),
    ).fetchone()
    if alias_meta is not None and incoming["deleted_at"] is None:
        alias = _row_dict(alias_meta)
        normalized.update({
            "revision": int(alias["revision"]),
            "origin_device_id": alias["origin_device_id"],
            "updated_at": alias["updated_at"],
            "deleted_at": alias["deleted_at"],
            "payload": None,
        })
    return normalized, incoming


def _scrub_deleted_record_history(
        conn: sqlite3.Connection, record_type: str, public_id: str) -> dict:
    """Keep one payload-free tombstone and erase content-bearing sync audit.

    ``sync_changes`` is a delivery queue, not an immutable clinical audit log.
    Once the current head is a deletion, retaining prior payload snapshots or
    conflict JSON would defeat the user's deletion request.  Seen-version rows
    are intentionally retained: they contain no user text and stop a stale
    peer from replaying a previously observed live version.
    """
    raw_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).fetchone()
    if raw_meta is None:
        raise SyncError("sync record not found")
    meta = _row_dict(raw_meta)
    if meta["deleted_at"] is None:
        raise SyncError("live sync history cannot be scrubbed")
    tombstone = {
        "record_type": record_type,
        "public_id": public_id,
        "revision": int(meta["revision"]),
        "origin_device_id": meta["origin_device_id"],
        "parent_origin_device_id": meta["parent_origin_device_id"],
        "parent_revision": meta["parent_revision"],
        "updated_at": meta["updated_at"],
        "deleted_at": meta["deleted_at"],
        "payload": None,
    }
    _append_change(conn, tombstone)
    keep_event_id = _event_id(tombstone)
    # Repair old databases defensively in case the retained event was created
    # by a pre-redaction build with an unexpected payload.
    conn.execute(
        "UPDATE sync_changes SET record_type=?,public_id=?,revision=?,"
        "origin_device_id=?,parent_origin_device_id=?,parent_revision=?,"
        "updated_at=?,deleted_at=?,payload_json=NULL WHERE event_id=?",
        (
            record_type, public_id, tombstone["revision"],
            tombstone["origin_device_id"],
            tombstone["parent_origin_device_id"],
            tombstone["parent_revision"], tombstone["updated_at"],
            tombstone["deleted_at"], keep_event_id,
        ),
    )
    removed_changes = conn.execute(
        "DELETE FROM sync_changes WHERE record_type=? AND public_id=? "
        "AND event_id<>?",
        (record_type, public_id, keep_event_id),
    ).rowcount
    removed_conflicts = conn.execute(
        "DELETE FROM sync_conflicts WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).rowcount
    return {
        "record_type": record_type,
        "public_id": public_id,
        "removed_changes": max(0, int(removed_changes)),
        "removed_conflicts": max(0, int(removed_conflicts)),
        "tombstone_event_id": keep_event_id,
    }


def scrub_deleted_record_history(
        conn: sqlite3.Connection, record_type: str, public_id: str) -> dict:
    """Public privacy API for one record whose current head is a deletion."""
    if record_type not in RECORD_TYPES:
        raise SyncError("record type is not syncable")
    public_id = _validate_public_id(public_id)
    _sync_tables(conn)
    return _scrub_deleted_record_history(conn, record_type, public_id)


def scrub_all_deleted_history(conn: sqlite3.Connection) -> dict:
    """Upgrade old databases by redacting every already-deleted record."""
    _sync_tables(conn)
    guest = scrub_guest_sync_state(conn)
    rows = conn.execute(
        "SELECT record_type,public_id FROM sync_records "
        "WHERE deleted_at IS NOT NULL ORDER BY record_type,public_id"
    ).fetchall()
    result = {
        "records": 0, "removed_changes": 0, "removed_conflicts": 0,
        "guest_identities": guest["identities"],
        "guest_records": guest["records"],
        "guest_changes": guest["changes"],
        "guest_seen_versions": guest["seen_versions"],
        "guest_conflicts": guest["conflicts"],
    }
    for row in rows:
        if row[0] not in RECORD_TYPES:
            continue
        cleaned = _scrub_deleted_record_history(conn, row[0], row[1])
        result["records"] += 1
        result["removed_changes"] += cleaned["removed_changes"]
        result["removed_conflicts"] += cleaned["removed_conflicts"]
    return result


def reset_sync_state(conn: sqlite3.Connection) -> dict:
    """Erase all merge/delivery state after an application-wide deletion.

    SQLite's AUTOINCREMENT high-water value is deliberately not reset.  New
    events therefore remain above cursors acknowledged by a previously paired
    device when the installation identity itself is retained.
    """
    _sync_tables(conn)
    result = {}
    for table in (
            "sync_conflicts", "sync_changes", "sync_seen_versions",
            "sync_records", "sync_peer_cursors",
            "sync_excluded_records", "sync_identity_aliases"):
        result[table] = max(0, int(conn.execute(
            "DELETE FROM {}".format(table)).rowcount))
    if _table_exists(conn, "sync_local_status"):
        conn.execute(
            "UPDATE sync_local_status SET last_sync_at=NULL,"
            "last_peer_device_id=NULL,last_peer_name=NULL,"
            "last_summary_json='{}' WHERE singleton=1")
        result["sync_local_status"] = 1
    return result


def record_local_change(
        conn: sqlite3.Connection,
        record_type: str,
        local_id: int,
        device_id: str,
        *,
        updated_at: Optional[str] = None,
        _guest_checked: bool = False,
) -> dict:
    """Snapshot one allowed local row and append a causal change event."""
    device_id = _validate_device_id(device_id)
    if type(local_id) is not int or local_id < 1:
        raise SyncError("invalid local id")
    if record_type not in RECORD_TYPES:
        raise SyncError("record type is not syncable")
    _sync_tables(conn)
    if not _guest_checked:
        scrub_guest_sync_state(conn)
        if _is_guest_derived_local_row(
                conn, record_type, local_id):
            # Never assign a new sync identity to guest-only content. Existing
            # native/shadow identities were quarantined by the scrub above.
            raise SyncError("guest records are not syncable")
    if not _local_projection_allowed(conn, record_type, local_id):
        raw_meta = conn.execute(
            "SELECT * FROM sync_records WHERE record_type=? "
            "AND local_id=? AND deleted_at IS NULL",
            (record_type, local_id),
        ).fetchone()
        if raw_meta is not None:
            withdrawn = _record_projection_withdrawal(
                conn, _row_dict(raw_meta), device_id,
                str(updated_at or _utcnow()))
            if withdrawn is not None:
                return withdrawn
        # Private/default journals and delivery-device event state never gain
        # a public identity merely because an unguarded mutation hook fired.
        raise SyncError("record is excluded by local sync policy")
    if record_type in _CONVERSATION_SINGLETON_TYPES:
        _migrate_conversation_singleton_identity(
            conn, record_type, local_id, device_id)
        if conn.execute(
                "SELECT 1 FROM {} WHERE {}=?".format(
                    RECORD_TYPES[record_type].table,
                    RECORD_TYPES[record_type].primary_key),
                (local_id,),
        ).fetchone() is None:
            raise SyncError("deleted singleton cannot be changed")
    public_id, payload = _serialize_row(conn, record_type, local_id)
    _validate_payload(record_type, payload)
    _validate_schema_public_identity(record_type, public_id, payload)
    local_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND local_id=? "
        "AND deleted_at IS NULL",
        (record_type, local_id),
    ).fetchone()
    if local_meta is not None and local_meta["public_id"] != public_id:
        if record_type not in _SCHEMA_CLINICAL_RECORD_TYPES:
            raise SyncError("native public identity changed unexpectedly")
        # Explicit clinical re-enable rotates the generation-derived physical
        # ids.  Withdraw every old identity first, then enroll the same local
        # row under the fresh namespace; the UNIQUE local-id shadow invariant
        # therefore remains intact and no payload can revive an old tombstone.
        _record_projection_withdrawal(
            conn, _row_dict(local_meta), device_id,
            str(updated_at or _utcnow()))
    previous = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).fetchone()
    previous = _row_dict(previous) if previous else None
    if previous and previous["deleted_at"] is not None:
        # Re-enabling a projection is an explicit local action.  Release only
        # its policy-withdrawal marker; guest/orphan quarantines remain hard
        # privacy boundaries.  The new revision is a direct child of the
        # payload-free tombstone and peers can therefore distinguish it from
        # an unrelated stale live replay.
        conn.execute(
            "DELETE FROM sync_excluded_records WHERE record_type=? "
            "AND public_id=? AND reason='policy_withdrawn'",
            (record_type, public_id),
        )
    revision = int(previous["revision"]) + 1 if previous else 1
    stamp = str(updated_at or _utcnow())
    record = {
        "record_type": record_type,
        "public_id": public_id,
        "revision": revision,
        "origin_device_id": device_id,
        "parent_origin_device_id": (
            previous["origin_device_id"] if previous else None),
        "parent_revision": previous["revision"] if previous else None,
        "updated_at": stamp,
        "deleted_at": None,
        "payload": payload,
    }
    conn.execute(
        "INSERT INTO sync_records("
        "record_type,local_id,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(record_type,public_id) DO UPDATE SET "
        "local_id=excluded.local_id,revision=excluded.revision,"
        "origin_device_id=excluded.origin_device_id,"
        "parent_origin_device_id=excluded.parent_origin_device_id,"
        "parent_revision=excluded.parent_revision,"
        "updated_at=excluded.updated_at,deleted_at=NULL,"
        "payload_hash=excluded.payload_hash",
        (
            record_type, local_id, public_id, revision, device_id,
            record["parent_origin_device_id"], record["parent_revision"],
            stamp, None, _payload_hash(payload),
        ),
    )
    _mark_seen(conn, record)
    _append_change(conn, record)
    return record


def _record_missing_local_delete(
        conn: sqlite3.Connection,
        meta: dict,
        device_id: str,
        deleted_at: str,
) -> dict:
    """Turn a live shadow row whose physical row vanished into a tombstone."""
    revision = int(meta["revision"]) + 1
    record = {
        "record_type": meta["record_type"],
        "public_id": meta["public_id"],
        "revision": revision,
        "origin_device_id": device_id,
        "parent_origin_device_id": meta["origin_device_id"],
        "parent_revision": meta["revision"],
        "updated_at": deleted_at,
        "deleted_at": deleted_at,
        "payload": None,
    }
    conn.execute(
        "UPDATE sync_records SET local_id=NULL,revision=?,"
        "origin_device_id=?,parent_origin_device_id=?,parent_revision=?,"
        "updated_at=?,deleted_at=?,payload_hash=? "
        "WHERE record_type=? AND public_id=? AND local_id IS NOT NULL "
        "AND deleted_at IS NULL",
        (
            revision, device_id, meta["origin_device_id"], meta["revision"],
            deleted_at, deleted_at, _payload_hash(None, deleted_at),
            meta["record_type"], meta["public_id"],
        ),
    )
    _mark_seen(conn, record)
    _append_change(conn, record)
    _scrub_deleted_record_history(
        conn, record["record_type"], record["public_id"])
    return record


def refresh_local_changes(
        conn: sqlite3.Connection,
        device_id: str,
) -> dict:
    """Discover unhooked local writes and physical deletes by full scan.

    This is the safety net for legacy server mutation paths which do not yet
    call ``record_local_change``/``record_local_delete`` in their transaction.
    The scan compares canonical logical payload hashes, never raw SQLite
    pages.  Calling it repeatedly without an intervening physical mutation
    appends no new changes.
    """
    device_id = _validate_device_id(device_id)
    _sync_tables(conn)
    guest_privacy = scrub_guest_sync_state(conn)
    hard_parent = _scrub_hard_deleted_parent_payloads(conn)
    projection = _redact_ineligible_module_records(conn, device_id)
    counts = {
        "added": 0,
        "updated": 0,
        "deleted": projection["missing"],
        "unchanged": 0,
        "identity_migrated": 0,
        "guest_excluded": guest_privacy["identities"],
        "orphan_excluded": 0,
        "policy_excluded": 0,
        "policy_redacted": projection["redacted"],
        "hard_parent_excluded": hard_parent["identities"],
        "tables_missing": [],
        "auto_merged": 0,
        "deferred_applied": 0,
    }
    ordered_types = sorted(
        RECORD_TYPES, key=lambda value: _DEPENDENCY_ORDER[value])
    guest_conversation_ids = _guest_derived_conversation_local_ids(conn)

    # Parents are visited first so newly discovered child rows can encode
    # their references with the parent's stable public identity.
    for record_type in ordered_types:
        spec = RECORD_TYPES[record_type]
        if not _table_exists(conn, spec.table):
            counts["tables_missing"].append(spec.table)
            continue
        rows = conn.execute(
            "SELECT {0} FROM {1} ORDER BY {0}".format(
                spec.primary_key, spec.table)
        ).fetchall()
        for row in rows:
            local_id = int(row[0])
            if _is_guest_derived_local_row(
                    conn, record_type, local_id,
                    guest_conversation_ids):
                counts["guest_excluded"] += 1
                continue
            if _local_row_has_excluded_identity(
                    conn, record_type, local_id,
                    reasons={"guest_scope", "orphan_parent"}):
                counts["orphan_excluded"] += 1
                continue
            if _required_local_reference_missing(
                    conn, record_type, local_id):
                orphan = _exclude_orphan_local_row(
                    conn, record_type, local_id, device_id)
                counts["deleted"] += orphan["tombstoned"]
                counts["orphan_excluded"] += 1
                continue
            if not _local_projection_allowed(
                    conn, record_type, local_id):
                counts["policy_excluded"] += 1
                continue
            if _migrate_conversation_singleton_identity(
                    conn, record_type, local_id, device_id):
                counts["identity_migrated"] += 1
                if conn.execute(
                        "SELECT 1 FROM {} WHERE {}=?".format(
                            spec.table, spec.primary_key),
                        (local_id,),
                ).fetchone() is None:
                    counts["deleted"] += 1
                    continue
            raw_meta = conn.execute(
                "SELECT * FROM sync_records "
                "WHERE record_type=? AND local_id=?",
                (record_type, local_id),
            ).fetchone()
            if raw_meta is None:
                record_local_change(
                    conn, record_type, local_id, device_id,
                    _guest_checked=True)
                counts["added"] += 1
                continue
            meta = _row_dict(raw_meta)
            serialized_public_id, payload = _serialize_row(
                conn, record_type, local_id)
            _validate_payload(record_type, payload)
            _validate_schema_public_identity(
                record_type, serialized_public_id, payload)
            if meta["public_id"] != serialized_public_id:
                if record_type not in _SCHEMA_CLINICAL_RECORD_TYPES:
                    raise SyncError("native public identity changed unexpectedly")
                record_local_change(
                    conn, record_type, local_id, device_id,
                    _guest_checked=True)
                counts["updated"] += 1
                counts["policy_redacted"] += 1
                continue
            if (
                meta["deleted_at"] is None
                and meta["payload_hash"] == _payload_hash(payload)
            ):
                counts["unchanged"] += 1
                continue
            record_local_change(
                conn, record_type, local_id, device_id,
                _guest_checked=True)
            counts["updated"] += 1

    # A physical delete has no row left for record_local_delete to serialize.
    # Scan only live shadows, and clear local_id as part of the tombstone so a
    # second refresh cannot emit the same deletion again.
    stamp = _utcnow()
    for record_type in ordered_types:
        spec = RECORD_TYPES[record_type]
        if not _table_exists(conn, spec.table):
            continue
        live_meta = conn.execute(
            "SELECT * FROM sync_records WHERE record_type=? "
            "AND local_id IS NOT NULL AND deleted_at IS NULL "
            "ORDER BY local_id",
            (record_type,),
        ).fetchall()
        for raw_meta in live_meta:
            meta = _row_dict(raw_meta)
            exists = conn.execute(
                "SELECT 1 FROM {} WHERE {}=?".format(
                    spec.table, spec.primary_key),
                (meta["local_id"],),
            ).fetchone()
            if exists is not None:
                continue
            if _canonicalize_missing_singleton_delete(
                    conn, meta, device_id, stamp) is not None:
                counts["deleted"] += 1
                counts["identity_migrated"] += 1
                continue
            _record_missing_local_delete(
                conn, meta, device_id, stamp)
            counts["deleted"] += 1
    # A final privacy pass makes the method fail closed if future enrollment
    # code accidentally creates guest shadow state in this same transaction.
    repaired = scrub_guest_sync_state(conn)
    counts["guest_excluded"] = max(
        counts["guest_excluded"], repaired["identities"])
    _scrub_ineligible_stored_clinical_conflicts(conn)
    counts["auto_merged"] = _auto_merge_legacy_conflicts(conn)
    counts["deferred_applied"] = _retry_deferred_conflicts(conn)
    return counts


def _dependent_local_ids(
        conn: sqlite3.Connection, conversation_id: int
) -> list[tuple[str, int]]:
    """Return the full syncable descendant graph, deepest rows first."""
    discovered = {("conversation", int(conversation_id))}
    frontier = [("conversation", int(conversation_id))]
    while frontier:
        target_type, target_id = frontier.pop(0)
        for record_type, spec in RECORD_TYPES.items():
            # A source/supervision link does not make another conversation an
            # owned child of the deleted source session.
            if record_type == "conversation" or not _table_exists(
                    conn, spec.table):
                continue
            columns = _columns(conn, spec.table)
            for _, column, reference_type in spec.references:
                if reference_type != target_type or column not in columns:
                    continue
                for row in conn.execute(
                        "SELECT {0} FROM {1} WHERE {2}=? ORDER BY {0}".format(
                            spec.primary_key, spec.table, column),
                        (target_id,),
                ).fetchall():
                    identity = (record_type, int(row[0]))
                    if identity in discovered:
                        continue
                    discovered.add(identity)
                    frontier.append(identity)
    discovered.discard(("conversation", int(conversation_id)))
    return sorted(
        discovered,
        key=lambda value: (
            -_DEPENDENCY_ORDER[value[0]], value[0], value[1]),
    )


def record_local_delete(
        conn: sqlite3.Connection,
        record_type: str,
        local_id: int,
        device_id: str,
        *,
        deleted_at: Optional[str] = None,
        cascade: bool = True,
        physical: bool = False,
) -> list[dict]:
    """Create durable tombstones before the application's physical delete."""
    device_id = _validate_device_id(device_id)
    if record_type not in RECORD_TYPES:
        raise SyncError("record type is not syncable")
    _sync_tables(conn)
    is_guest = _is_guest_derived_local_row(
        conn, record_type, local_id)
    scrub_guest_sync_state(conn)
    stamp = str(deleted_at or _utcnow())
    records = []
    if record_type == "conversation" and cascade:
        for child_type, child_id in _dependent_local_ids(conn, local_id):
            records.extend(record_local_delete(
                conn, child_type, child_id, device_id,
                deleted_at=stamp, cascade=False, physical=physical,
            ))

    if is_guest:
        # Guest rows are application-local and need no peer tombstone. Their
        # opaque native/shadow ids remain quarantined so stale peers cannot
        # reintroduce them later.
        if physical:
            conn.execute(
                "DELETE FROM {} WHERE {}=?".format(
                    RECORD_TYPES[record_type].table,
                    RECORD_TYPES[record_type].primary_key),
                (local_id,),
            )
        return records

    if record_type in _CONVERSATION_SINGLETON_TYPES:
        _migrate_conversation_singleton_identity(
            conn, record_type, local_id, device_id)
        exists = conn.execute(
            "SELECT 1 FROM {} WHERE {}=?".format(
                RECORD_TYPES[record_type].table,
                RECORD_TYPES[record_type].primary_key),
            (local_id,),
        ).fetchone()
        if exists is None:
            return records

    if not _local_projection_allowed(conn, record_type, local_id):
        raw_meta = conn.execute(
            "SELECT * FROM sync_records WHERE record_type=? "
            "AND local_id=? AND deleted_at IS NULL",
            (record_type, local_id),
        ).fetchone()
        if raw_meta is not None:
            withdrawn = _record_projection_withdrawal(
                conn, _row_dict(raw_meta), device_id, stamp)
            if withdrawn is not None:
                records.append(withdrawn)
        if physical:
            conn.execute(
                "DELETE FROM {} WHERE {}=?".format(
                    RECORD_TYPES[record_type].table,
                    RECORD_TYPES[record_type].primary_key),
                (local_id,),
            )
        return records

    public_id, _ = _serialize_row(conn, record_type, local_id)
    previous_row = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).fetchone()
    previous = _row_dict(previous_row) if previous_row else None
    revision = int(previous["revision"]) + 1 if previous else 1
    record = {
        "record_type": record_type,
        "public_id": public_id,
        "revision": revision,
        "origin_device_id": device_id,
        "parent_origin_device_id": (
            previous["origin_device_id"] if previous else None),
        "parent_revision": previous["revision"] if previous else None,
        "updated_at": stamp,
        "deleted_at": stamp,
        "payload": None,
    }
    conn.execute(
        "INSERT INTO sync_records("
        "record_type,local_id,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(record_type,public_id) DO UPDATE SET "
        "local_id=NULL,revision=excluded.revision,"
        "origin_device_id=excluded.origin_device_id,"
        "parent_origin_device_id=excluded.parent_origin_device_id,"
        "parent_revision=excluded.parent_revision,"
        "updated_at=excluded.updated_at,deleted_at=excluded.deleted_at,"
        "payload_hash=excluded.payload_hash",
        (
            record_type, None, public_id, revision, device_id,
            record["parent_origin_device_id"], record["parent_revision"],
            stamp, stamp, _payload_hash(None, stamp),
        ),
    )
    _mark_seen(conn, record)
    _append_change(conn, record)
    _scrub_deleted_record_history(conn, record_type, public_id)
    if physical:
        conn.execute(
            "DELETE FROM {} WHERE {}=?".format(
                RECORD_TYPES[record_type].table,
                RECORD_TYPES[record_type].primary_key),
            (local_id,),
        )
    records.append(record)
    return records


def export_change_batch(
        conn: sqlite3.Connection,
        device_id: str,
        *,
        after_cursor: int = 0,
        ack_cursor: int = 0,
        limit: int = DEFAULT_BATCH_LIMIT,
) -> dict:
    """Return a bounded, secret-free logical change batch."""
    device_id = _validate_device_id(device_id)
    if type(after_cursor) is not int or after_cursor < 0:
        raise SyncError("invalid cursor")
    if type(ack_cursor) is not int or ack_cursor < 0:
        raise SyncError("invalid acknowledgement cursor")
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH_LIMIT:
        raise SyncError("invalid batch limit")
    _sync_tables(conn)
    scrub_guest_sync_state(conn)
    _scrub_hard_deleted_parent_payloads(conn)
    _redact_ineligible_module_records(conn, device_id)
    rows = conn.execute(
        "SELECT c.* FROM sync_changes c WHERE c.cursor>? "
        "AND (c.deleted_at IS NOT NULL OR NOT EXISTS("
        "SELECT 1 FROM sync_excluded_records e "
        "WHERE e.record_type=c.record_type AND e.public_id=c.public_id)) "
        "ORDER BY c.cursor LIMIT ?",
        (after_cursor, limit),
    ).fetchall()
    records = []
    cursor = after_cursor
    live_clinical_batch = None
    for raw in rows:
        row = _row_dict(raw)
        is_live_clinical = (
            row["record_type"] in _SCHEMA_CLINICAL_RECORD_TYPES
            and row["deleted_at"] is None)
        if records and is_live_clinical != live_clinical_batch:
            # A receiving installation must be able to apply the content-free
            # session-meta preference first, show its local confirmation UI,
            # and retry without ever retaining clinical payloads.  Therefore
            # a batch never mixes live Schema content with ordinary records.
            break
        if live_clinical_batch is None:
            live_clinical_batch = is_live_clinical
        cursor = int(row["cursor"])
        record = {
            "record_type": row["record_type"],
            "public_id": row["public_id"],
            "revision": row["revision"],
            "origin_device_id": row["origin_device_id"],
            "parent_origin_device_id": row["parent_origin_device_id"],
            "parent_revision": row["parent_revision"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
            "payload": (
                None if row["payload_json"] is None
                else json.loads(row["payload_json"])),
        }
        if record["record_type"] not in RECORD_TYPES:
            raise SyncError("unsafe record found in change log")
        if record["deleted_at"] is None:
            if not _projection_payload_allowed(
                    record["record_type"], record["payload"]):
                raise SyncError(
                    "policy-excluded record found in change log")
            _validate_payload(record["record_type"], record["payload"])
            _validate_schema_public_identity(
                record["record_type"], record["public_id"],
                record["payload"])
            if record["record_type"] in _SCHEMA_CLINICAL_RECORD_TYPES:
                try:
                    _validate_incoming_schema_flow_contract(
                        conn, record, {})
                except _MissingDependency:
                    raise SyncError(
                        "clinical sync path flow is unavailable") from None
                conv_public_id = record["payload"].get(
                    "conversation_public_id")
                conv_id = _find_local_id(
                    conn, "conversation", conv_public_id)
                held = (conn.execute(
                    "SELECT safety_hold FROM conversations WHERE id=?",
                    (conv_id,)).fetchone() if conv_id is not None else None)
                if held is None:
                    raise SyncError(
                        "clinical sync conversation is unavailable")
                if int(held[0] or 0) == 1:
                    # Keep the cursor before this record.  A clean service
                    # pause closes the QR without acknowledging it, so the
                    # same payload is replayable after the safety hold ends.
                    raise ClinicalSyncSafetyPause(
                        "clinical sync is paused by a conversation safety hold")
        records.append(record)
    remaining = conn.execute(
        "SELECT 1 FROM sync_changes c WHERE c.cursor>? "
        "AND (c.deleted_at IS NOT NULL OR NOT EXISTS("
        "SELECT 1 FROM sync_excluded_records e "
        "WHERE e.record_type=c.record_type AND e.public_id=c.public_id)) "
        "LIMIT 1", (cursor,)
    ).fetchone() is not None
    return {
        "kind": BATCH_KIND,
        "version": BATCH_VERSION,
        "sender_device_id": device_id,
        "after_cursor": after_cursor,
        "cursor": cursor,
        "ack_cursor": ack_cursor,
        "has_more": remaining,
        "records": records,
    }


def _text_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _validate_text_field(record_type: str, key: str, value: str) -> None:
    if "\x00" in value:
        raise SyncError("payload text contains a null byte")
    if key in _TIMESTAMP_FIELDS:
        if not value or _text_size(value) > 64:
            raise SyncError("invalid payload timestamp")
        return
    if key in _LONG_TEXT_FIELDS:
        limit = MAX_TEXT_FIELD_BYTES
    elif key == "title":
        limit = MAX_SHORT_TEXT_BYTES
    elif key in {
            "mode", "submode", "therapist", "status", "scope", "kind",
            "preferred_pace", "case_id", "role"}:
        limit = MAX_IDENTIFIER_BYTES
    else:
        limit = MAX_SHORT_TEXT_BYTES
    if _text_size(value) > limit:
        raise SyncError("payload text field is too large")
    allowed = _ENUM_FIELDS.get((record_type, key))
    if allowed is not None and value not in allowed:
        raise SyncError("invalid enumerated payload field")
    if key == "preferred_days_json":
        if value != _canonical_adhd_days(value):
            raise SyncError("preferred ADHD days are not canonical")
    if key == "reminder_local_time" and value and not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise SyncError("invalid ADHD reminder time")
    if key == "timezone" and value and not re.fullmatch(
            r"[A-Za-z0-9_+\-/]{1,64}", value):
        raise SyncError("invalid ADHD timezone")
    if (record_type == "message" and key == "turn_pair_public_id"
            and value and not _TURN_PAIR_PUBLIC_ID_RE.fullmatch(value)):
        raise SyncError("invalid completed-turn pair identity")


def _validate_payload(record_type: str, payload) -> None:
    if not isinstance(payload, dict):
        raise SyncError("live record payload must be an object")
    spec = RECORD_TYPES[record_type]
    allowed = set(spec.fields)
    allowed.update(item[0] for item in spec.references)
    unknown = set(payload) - allowed
    forbidden = set(payload) & _FORBIDDEN_KEYS
    if forbidden:
        raise SyncError("secret fields are forbidden")
    if unknown:
        raise SyncError("unknown logical record fields")
    required = _REQUIRED_PAYLOAD_FIELDS[record_type]
    if any(key not in payload or payload[key] is None for key in required):
        raise SyncError("required logical record field is missing")
    if not _projection_payload_allowed(record_type, payload):
        raise SyncError("record is excluded by sync policy")
    reference_fields = {item[0] for item in spec.references}
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            raise SyncError("nested logical record fields are forbidden")
        if key in reference_fields:
            if value is not None:
                _validate_public_id(value)
            continue
        if value is None:
            continue
        if isinstance(value, bool):
            raise SyncError("boolean payload fields are forbidden")
        if key in _REAL_FIELDS:
            if type(value) not in (int, float) or not math.isfinite(
                    float(value)) or not 0 < float(value) <= 253402300799:
                raise SyncError("invalid real-number payload field")
            continue
        if isinstance(value, str):
            if key.endswith("_public_id") and value:
                _validate_public_id(value)
            if key in _INTEGER_FIELDS or key in _REAL_FIELDS:
                raise SyncError("numeric payload field must be an integer")
            _validate_text_field(record_type, key, value)
            continue
        if type(value) is not int:
            raise SyncError("unsupported logical record field type")
        if key not in _INTEGER_FIELDS:
            raise SyncError("text payload field must be a string")
        if key in _BOOLEAN_INTEGER_FIELDS and value not in (0, 1):
            raise SyncError("invalid boolean integer payload field")
        if key in _RATING_FIELDS and not 0 <= value <= 10:
            raise SyncError("invalid rating payload field")
        if key == "available_minutes" and not 1 <= value <= 1440:
            raise SyncError("invalid available minutes payload field")
        if key == "target_per_week" and not 1 <= value <= 7:
            raise SyncError("invalid weekly ADHD target")
        if key == "effort_minutes" and not 0 <= value <= 1440:
            raise SyncError("invalid ADHD effort minutes")
    if (record_type == "adhd_habit"
            and not str(payload.get("title") or "").strip()):
        raise SyncError("ADHD habit title is required")
    if (record_type == "adhd_journal"
            and not str(payload.get("content") or "").strip()):
        raise SyncError("ADHD journal content is required")
    if (record_type == "message" and payload.get("turn_pair_public_id")
            and payload.get("role") not in {"user", "assistant"}):
        raise SyncError("completed-turn identity requires a dialogue role")
    if record_type == "schema_path":
        if payload.get("therapist") != "young":
            raise SyncError("Schema Path therapist is invalid")
        flow_version = payload.get("flow_version")
        if type(flow_version) is not int or flow_version not in (4, 5):
            raise SyncError("Schema Path flow version is invalid")
        if not _schema_path_state_is_valid_for_flow(
                flow_version, payload.get("stage"), payload.get("step"),
                str(payload.get("method_node_id") or "")):
            raise SyncError("Schema Path stage, step or method is invalid")
        if (type(payload.get("clinical_generation")) is not int
                or payload["clinical_generation"] < 1):
            raise SyncError("invalid Schema clinical generation")
        if (type(payload.get("path_sequence")) is not int
                or payload["path_sequence"] < 1):
            raise SyncError("invalid Schema Path sequence")
        if type(payload.get("revision")) is not int or payload["revision"] < 0:
            raise SyncError("invalid Schema Path revision")
    if record_type in {
            "schema_candidate", "schema_focus_check", "schema_step"}:
        if type(payload.get("revision")) is not int or payload["revision"] < 0:
            raise SyncError("invalid Schema projection revision")
    if record_type == "schema_step" and not any(
            _schema_step_state_is_valid_for_flow(
                flow_version, payload.get("stage"), payload.get("step"))
            for flow_version in _SCHEMA_PATH_STEP_STAGE_BY_FLOW):
        raise SyncError("Schema step stage is invalid")
    if record_type == "schema_candidate" and (
            type(payload.get("clinical_generation")) is not int
            or payload["clinical_generation"] < 1):
        raise SyncError("invalid Schema candidate generation")
    if (record_type == "session_meta"
            and "schema_clinical_sync_generation" in payload
            and (type(payload["schema_clinical_sync_generation"]) is not int
                 or payload["schema_clinical_sync_generation"] < 0)):
        raise SyncError("invalid Schema consent generation")
    if record_type == "session_meta" and (
            ("schema_clinical_sync_enabled" in payload)
            != ("schema_clinical_sync_generation" in payload)):
        raise SyncError("incomplete Schema consent preference")
    if record_type == "schema_growth":
        if type(payload.get("seq")) is not int or not 1 <= payload["seq"] <= 6:
            raise SyncError("invalid Schema growth sequence")
        age = payload.get("stage_age")
        if age is not None and (
                type(age) is not int or not 0 <= age <= 120):
            raise SyncError("invalid Schema growth age")
        environment_user = payload.get(
            "environment_source_user_message_public_id")
        environment_assistant = payload.get(
            "environment_source_assistant_message_public_id")
        if (environment_user in (None, "")) != (
                environment_assistant in (None, "")):
            raise SyncError("Schema environment source pair is incomplete")
        if (payload.get("environment_status") == "active"
                and environment_user in (None, "")):
            raise SyncError("active Schema environment requires a source pair")
    if record_type == "schema_origin":
        age = payload.get("age_reported")
        if age is not None and (
                type(age) is not int or not 0 <= age <= 120):
            raise SyncError("invalid Schema origin age")


def _schema_natural_public_id(kind: str, *parts) -> str:
    """Mirror the server's content-free Schema v4 natural identity."""
    normalized = [str(kind)] + [
        "" if part is None else str(part) for part in parts]
    if any(not value for value in normalized):
        return ""
    encoded = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(
        b"divan-schema-v4\0" + encoded).hexdigest()[:32]


def _expected_schema_public_id(record_type: str, payload: dict) -> str:
    """Derive one approved clinical projection's canonical public id."""
    if record_type == "schema_path":
        return _schema_natural_public_id(
            "path", payload.get("conversation_public_id"),
            payload.get("clinical_generation"),
            payload.get("path_sequence"))
    if record_type == "schema_candidate":
        return _schema_natural_public_id(
            "candidate", payload.get("conversation_public_id"),
            payload.get("clinical_generation"),
            payload.get("source_user_message_public_id"),
            payload.get("source_assistant_message_public_id"),
            payload.get("schema_key") or "-",
            payload.get("mode_key") or "-")
    if record_type == "schema_focus_check":
        return _schema_natural_public_id(
            "focus", payload.get("path_public_id"),
            payload.get("candidate_public_id"))
    if record_type == "schema_step":
        return _schema_natural_public_id(
            "step", payload.get("path_public_id"), payload.get("step"))
    if record_type == "schema_origin":
        return _schema_natural_public_id(
            "origin", payload.get("path_public_id"))
    if record_type == "schema_growth":
        return _schema_natural_public_id(
            "growth", payload.get("path_public_id"), payload.get("seq"))
    if record_type == "schema_healthy_adult":
        return _schema_natural_public_id(
            "healthy", payload.get("path_public_id"),
            payload.get("source_message_public_id"),
            payload.get("source_assistant_message_public_id"),
            payload.get("source"))
    if record_type == "schema_transfer":
        return _schema_natural_public_id(
            "transfer", payload.get("path_public_id"))
    if record_type == "schema_message_meta":
        path_public_id = payload.get("path_public_id")
        if path_public_id:
            return _schema_natural_public_id(
                "meta", path_public_id, payload.get("event_key"))
        return _schema_natural_public_id(
            "meta-local", payload.get("conversation_public_id"),
            payload.get("clinical_generation"), payload.get("event_key"))
    return ""


def _validate_schema_public_identity(
        record_type: str, public_id: str, payload: dict) -> None:
    """Reject live Schema aliases before content reaches sync state."""
    if record_type not in _SCHEMA_CLINICAL_RECORD_TYPES:
        return
    expected = _expected_schema_public_id(record_type, payload)
    if not expected or public_id != expected:
        raise SyncError("Schema projection public identity is not canonical")


def validate_change_batch(batch: dict) -> dict:
    if not isinstance(batch, dict) or set(batch) != {
        "kind", "version", "sender_device_id", "after_cursor", "cursor",
        "ack_cursor", "has_more", "records",
    }:
        raise SyncError("invalid sync batch shape")
    if batch["kind"] != BATCH_KIND:
        raise SyncError("unsupported sync batch kind")
    if batch["version"] != BATCH_VERSION:
        raise SyncError(
            "unsupported sync batch version; protocol v{} required".format(
                BATCH_VERSION))
    _validate_device_id(batch["sender_device_id"])
    if type(batch["after_cursor"]) is not int or batch["after_cursor"] < 0:
        raise SyncError("invalid batch cursor")
    if type(batch["cursor"]) is not int or (
            batch["cursor"] < batch["after_cursor"]):
        raise SyncError("invalid batch cursor")
    if type(batch["ack_cursor"]) is not int or batch["ack_cursor"] < 0:
        raise SyncError("invalid acknowledgement cursor")
    if type(batch["has_more"]) is not bool:
        raise SyncError("invalid continuation flag")
    if not isinstance(batch["records"], list) or (
            len(batch["records"]) > MAX_BATCH_LIMIT):
        raise SyncError("invalid record list")
    try:
        encoded_batch = _canonical_json(batch).encode("utf-8")
    except (TypeError, ValueError):
        raise SyncError("sync batch is not canonical JSON") from None
    if len(encoded_batch) > MAX_PAYLOAD_BYTES:
        raise SyncError("sync batch is too large")
    message_pair_roles = {}
    for record in batch["records"]:
        if not isinstance(record, dict) or set(record) != {
            "record_type", "public_id", "revision", "origin_device_id",
            "parent_origin_device_id", "parent_revision", "updated_at",
            "deleted_at", "payload",
        }:
            raise SyncError("invalid sync record shape")
        record_type = record["record_type"]
        if record_type not in RECORD_TYPES:
            raise SyncError("record type is not syncable")
        _validate_public_id(record["public_id"])
        _validate_device_id(record["origin_device_id"])
        parent_origin = record["parent_origin_device_id"]
        parent_revision = record["parent_revision"]
        if (parent_origin is None) != (parent_revision is None):
            raise SyncError("incomplete parent version")
        if parent_origin is not None:
            _validate_device_id(parent_origin)
        if type(record["revision"]) is not int or record["revision"] < 1:
            raise SyncError("invalid revision")
        if parent_revision is not None and (
                type(parent_revision) is not int or parent_revision < 1):
            raise SyncError("invalid parent revision")
        if (parent_revision is not None
                and record["revision"] <= parent_revision):
            raise SyncError("child revision must advance its parent")
        if (not isinstance(record["updated_at"], str)
                or not record["updated_at"]
                or "\x00" in record["updated_at"]
                or _text_size(record["updated_at"]) > 64):
            raise SyncError("invalid update time")
        if record["deleted_at"] is not None and (
                not isinstance(record["deleted_at"], str)
                or not record["deleted_at"]
                or "\x00" in record["deleted_at"]
                or _text_size(record["deleted_at"]) > 64):
            raise SyncError("invalid deletion time")
        if record["deleted_at"] is not None:
            if record["payload"] is not None:
                raise SyncError("tombstone payload must be null")
        else:
            _validate_payload(record_type, record["payload"])
            _validate_schema_public_identity(
                record_type, record["public_id"], record["payload"])
            if record_type == "message":
                pair_public_id = record["payload"]["turn_pair_public_id"]
                if pair_public_id:
                    pair_role = (
                        pair_public_id, record["payload"].get("role"))
                    previous_public_id = message_pair_roles.get(pair_role)
                    if (previous_public_id is not None
                            and previous_public_id != record["public_id"]):
                        raise SyncError(
                            "completed-turn pair role is duplicated")
                    message_pair_roles[pair_role] = record["public_id"]
    # Validate every child whose parent path is carried in this batch before
    # apply_change_batch initializes or scrubs any local sync state.  Children
    # arriving in a later batch are checked against the installed parent by
    # _require_incoming_schema_clinical_consent below.
    incoming_path_flows = {
        record["public_id"]: record["payload"]["flow_version"]
        for record in batch["records"]
        if record["record_type"] == "schema_path"
        and record["deleted_at"] is None
    }
    for record in batch["records"]:
        if (record["record_type"] not in _SCHEMA_CLINICAL_RECORD_TYPES
                or record["deleted_at"] is not None
                or record["record_type"] == "schema_path"):
            continue
        payload = record["payload"]
        flow_version = incoming_path_flows.get(
            payload.get("path_public_id"))
        if flow_version is None:
            continue
        if (record["record_type"] == "schema_step"
                and not _schema_step_state_is_valid_for_flow(
                    flow_version, payload.get("stage"),
                    payload.get("step"))):
            raise SyncError("Schema step does not belong to its path flow")
        if (record["record_type"] == "schema_focus_check"
                and flow_version == 5):
            raise SyncError("Schema v5 does not accept focus rating records")
    live_clinical = [
        record for record in batch["records"]
        if record["record_type"] in _SCHEMA_CLINICAL_RECORD_TYPES
        and record["deleted_at"] is None]
    if live_clinical and len(live_clinical) != len(batch["records"]):
        raise SyncError(
            "live Schema projections require a dedicated clinical batch")
    return batch


def _find_local_id(
        conn: sqlite3.Connection, record_type: str, public_id: str
) -> Optional[int]:
    row = conn.execute(
        "SELECT local_id FROM sync_records "
        "WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).fetchone()
    if row and row[0] is not None:
        return int(row[0])
    spec = RECORD_TYPES[record_type]
    if spec.native_public_id and _table_exists(conn, spec.table):
        native = conn.execute(
            "SELECT {} FROM {} WHERE public_id=?".format(
                spec.primary_key, spec.table),
            (public_id,),
        ).fetchone()
        return int(native[0]) if native else None
    return None


def _payload_to_columns(
        conn: sqlite3.Connection, record_type: str, payload: dict
) -> dict:
    spec = RECORD_TYPES[record_type]
    table_columns = _columns(conn, spec.table)
    values = {
        key: value for key, value in payload.items()
        if key in spec.fields and key in table_columns
    }
    for payload_name, column, target_type in spec.references:
        if column not in table_columns or payload_name not in payload:
            continue
        reference = payload[payload_name]
        if reference is None:
            values[column] = None
            continue
        reference_id = _find_local_id(conn, target_type, reference)
        if reference_id is None:
            if (record_type, column) in _OPTIONAL_REFERENCES:
                values[column] = None
                continue
            raise _MissingDependency(
                "{} {}".format(target_type, reference))
        values[column] = reference_id
    if (record_type == "message" and values.get("reply_to") is not None
            and values.get("conv") is not None):
        parent = conn.execute(
            "SELECT conv FROM messages WHERE id=?",
            (values["reply_to"],),
        ).fetchone()
        if parent is None or int(parent[0]) != int(values["conv"]):
            raise SyncError("message reply target is outside its conversation")
    return values


def _write_payload(
        conn: sqlite3.Connection,
        record_type: str,
        public_id: str,
        payload: dict,
        local_id: Optional[int],
) -> int:
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        raise SyncError("target database lacks a required record table")
    values = _payload_to_columns(conn, record_type, payload)
    columns = _columns(conn, spec.table)
    # The mode preference may cross devices, but a numeric message watermark
    # may not: SQLite message ids are installation-local. When an incoming
    # merge turns Schema Therapy mode on, make the receiving installation
    # establish its own disclosure baseline before any background analyzer is
    # allowed to inspect text. A same-state session-meta update must not reset
    # a live cursor.
    if (record_type == "session_meta" and local_id is not None
            and values.get("schema_mode_enabled") == 1
            and "schema_mode_enabled" in columns):
        previous_mode = conn.execute(
            "SELECT schema_mode_enabled FROM session_meta WHERE conv=?",
            (local_id,),
        ).fetchone()
        if not previous_mode or int(previous_mode[0] or 0) != 1:
            if "schema_mode_initialized" in columns:
                values["schema_mode_initialized"] = 0
            if "schema_mode_enrolled_after_message_id" in columns:
                values["schema_mode_enrolled_after_message_id"] = 0
            if "schema_mode_provider" in columns:
                values["schema_mode_provider"] = ""
            if "schema_mode_model" in columns:
                values["schema_mode_model"] = ""
    # The clinical-sync preference may travel, but consent to disclose or
    # apply deep work is installation-local.  Any remote preference transition
    # therefore returns this device to a pending-confirmation state.
    if (record_type == "session_meta" and local_id is not None
            and "schema_clinical_sync_enabled" in values
            and "schema_clinical_sync_enabled" in columns):
        select_fields = ["schema_clinical_sync_enabled"]
        if "schema_clinical_sync_generation" in columns:
            select_fields.append("schema_clinical_sync_generation")
        previous_sync = conn.execute(
            "SELECT {} FROM session_meta WHERE conv=?".format(
                ",".join(select_fields)), (local_id,),
        ).fetchone()
        incoming_sync = int(values["schema_clinical_sync_enabled"] or 0)
        previous_enabled = int(previous_sync[0] or 0) \
            if previous_sync else 0
        previous_generation = int(previous_sync[1] or 0) \
            if previous_sync and len(select_fields) > 1 else 0
        incoming_generation = int(values.get(
            "schema_clinical_sync_generation", previous_generation) or 0)
        if incoming_generation < previous_generation:
            # A delayed preference head from an older sharing generation must
            # never reopen or withdraw the current generation.  Other benign
            # session framing fields in the same record may still merge.
            values["schema_clinical_sync_enabled"] = previous_enabled
            if "schema_clinical_sync_generation" in columns:
                values["schema_clinical_sync_generation"] = \
                    previous_generation
        elif (not previous_sync or incoming_generation > previous_generation
                or previous_enabled != incoming_sync):
            if "schema_clinical_sync_initialized" in columns:
                values["schema_clinical_sync_initialized"] = 0
    if spec.native_public_id and "public_id" in columns:
        values["public_id"] = public_id
    if local_id is None:
        if not values:
            raise SyncError("record has no fields supported by target schema")
        names = list(values)
        cursor = conn.execute(
            "INSERT INTO {}({}) VALUES({})".format(
                spec.table, ",".join(names),
                ",".join("?" for _ in names)),
            [values[name] for name in names],
        )
        return int(cursor.lastrowid)
    if values:
        names = list(values)
        conn.execute(
            "UPDATE {} SET {} WHERE {}=?".format(
                spec.table,
                ",".join("{}=?".format(name) for name in names),
                spec.primary_key),
            [values[name] for name in names] + [local_id],
        )
    return local_id


def _record_from_meta(
        conn: sqlite3.Connection, meta: dict
) -> dict:
    payload = None
    if meta["deleted_at"] is None and meta["local_id"] is not None:
        _, payload = _serialize_row(
            conn, meta["record_type"], int(meta["local_id"]))
    return {
        "record_type": meta["record_type"],
        "public_id": meta["public_id"],
        "revision": meta["revision"],
        "origin_device_id": meta["origin_device_id"],
        "parent_origin_device_id": meta["parent_origin_device_id"],
        "parent_revision": meta["parent_revision"],
        "updated_at": meta["updated_at"],
        "deleted_at": meta["deleted_at"],
        "payload": payload,
    }


def _is_direct_child(incoming: dict, local: dict) -> bool:
    return (
        incoming["parent_origin_device_id"] == local["origin_device_id"]
        and incoming["parent_revision"] == local["revision"]
    )


def _is_known_ancestor(incoming: dict, local: dict) -> bool:
    return (
        local["parent_origin_device_id"] == incoming["origin_device_id"]
        and local["parent_revision"] == incoming["revision"]
    ) or (
        local["origin_device_id"] == incoming["origin_device_id"]
        and int(local["revision"]) >= int(incoming["revision"])
    )


def _incoming_wins(local: dict, incoming: dict) -> bool:
    """Choose one head without consulting device-local arrival order.

    Privacy tombstones dominate live content without exception.  Re-enabled
    projections receive a fresh public identity, so a payload-free deletion
    can never be confused with a reversible policy withdrawal.  For live/live
    or tombstone/tombstone versions, causal ancestry dominates wall time; only
    concurrent branches use the deterministic total order.
    """
    direct = _is_direct_child(incoming, local)
    if local["deleted_at"] is not None and incoming["deleted_at"] is None:
        return False
    if incoming["deleted_at"] is not None and local["deleted_at"] is None:
        return True
    if _is_known_ancestor(incoming, local):
        return False
    if direct or (
            incoming["origin_device_id"] == local["origin_device_id"]
            and int(incoming["revision"]) > int(local["revision"])):
        return True
    return _record_order_key(incoming) > _record_order_key(local)


def _queue_conflict(
        conn: sqlite3.Connection,
        local: dict,
        incoming: dict,
        reason: str,
) -> bool:
    cursor = conn.execute(
        "INSERT OR IGNORE INTO sync_conflicts("
        "record_type,public_id,reason,local_json,incoming_json,"
        "incoming_event_id,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            incoming["record_type"], incoming["public_id"], reason,
            _canonical_json(local), _canonical_json(incoming),
            _event_id(incoming), _utcnow(),
        ),
    )
    return cursor.rowcount > 0


def _schema_path_public_id_from_record(record: dict) -> Optional[str]:
    if record.get("record_type") == "schema_path":
        return _valid_metadata_public_id(record.get("public_id"))
    payload = record.get("payload")
    if isinstance(payload, dict):
        return _valid_metadata_public_id(payload.get("path_public_id"))
    return None


def _mark_schema_projection_conflict(
        conn: sqlite3.Connection, local: dict, incoming: dict,
        reason: str) -> None:
    """Expose a content-free read-only marker to the Schema Path UI."""
    if not _table_exists(conn, "schema_path_sync_conflicts"):
        return
    path_public_id = (
        _schema_path_public_id_from_record(incoming)
        or _schema_path_public_id_from_record(local))
    if path_public_id is None:
        return
    payload = incoming.get("payload")
    conversation_public_id = (
        payload.get("conversation_public_id")
        if isinstance(payload, dict) else None)
    conv_id = (_find_local_id(conn, "conversation", conversation_public_id)
               if isinstance(conversation_public_id, str) else None)
    if conv_id is None:
        path_id = _find_local_id(conn, "schema_path", path_public_id)
        if path_id is not None:
            row = conn.execute(
                "SELECT conv FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            conv_id = _valid_local_id(row[0]) if row else None
    if conv_id is None:
        return
    stamp = _utcnow()
    public_id = hashlib.sha256(
        ("schema-sync-conflict\0" + path_public_id).encode("utf-8")
    ).hexdigest()[:32]
    conn.execute(
        "INSERT INTO schema_path_sync_conflicts("
        "public_id,conv,path_public_id,status,reason,created,updated) "
        "VALUES(?,?,?,'open',?,?,?) ON CONFLICT(path_public_id,status) "
        "DO UPDATE SET reason=excluded.reason,updated=excluded.updated",
        (public_id, conv_id, path_public_id, reason[:120], stamp, stamp),
    )


def _clinical_versions_are_concurrent(local: dict, incoming: dict) -> bool:
    if incoming.get("record_type") not in _SCHEMA_CLINICAL_RECORD_TYPES:
        return False
    if local.get("deleted_at") is not None or incoming.get(
            "deleted_at") is not None:
        return False
    if _payload_hash(local.get("payload")) == _payload_hash(
            incoming.get("payload")):
        return False
    if _is_direct_child(incoming, local) or _is_known_ancestor(
            incoming, local):
        return False
    if (incoming.get("origin_device_id") == local.get("origin_device_id")
            and int(incoming.get("revision") or 0)
            != int(local.get("revision") or 0)):
        return False
    return True


def _schema_active_path_collision(
        conn: sqlite3.Connection, incoming: dict) -> Optional[dict]:
    """Return a different local active path that would violate UNIQUE."""
    if (incoming.get("record_type") != "schema_path"
            or incoming.get("deleted_at") is not None):
        return None
    payload = incoming.get("payload")
    if (not isinstance(payload, dict)
            or payload.get("status") not in ("active", "paused")):
        # Completed/stopped paths preserve history but do not participate in
        # the one-active-path invariant and must be installable while another
        # path is active.
        return None
    conv_public_id = (payload.get("conversation_public_id")
                      if isinstance(payload, dict) else None)
    conv_id = (_find_local_id(conn, "conversation", conv_public_id)
               if isinstance(conv_public_id, str) else None)
    if conv_id is None:
        return None
    row = conn.execute(
        "SELECT id FROM schema_paths WHERE conv=? "
        "AND status IN ('active','paused') AND public_id<>? "
        "ORDER BY id LIMIT 1", (conv_id, incoming["public_id"]),
    ).fetchone()
    if row is None:
        return None
    meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type='schema_path' "
        "AND local_id=? AND deleted_at IS NULL", (row[0],),
    ).fetchone()
    if meta is None:
        raise SyncError("local Schema path lacks a sync identity")
    return _record_from_meta(conn, _row_dict(meta))


def _install_incoming(
        conn: sqlite3.Connection,
        incoming: dict,
        local_meta: Optional[dict],
) -> None:
    record_type = incoming["record_type"]
    public_id = incoming["public_id"]
    local_id = int(local_meta["local_id"]) if (
        local_meta and local_meta["local_id"] is not None) else None
    if incoming["deleted_at"] is not None:
        if (local_id is None
                and record_type in _CONVERSATION_SINGLETON_TYPES):
            alias_rows = conn.execute(
                "SELECT r.local_id,a.alias_public_id FROM "
                "sync_identity_aliases a JOIN sync_records r "
                "ON r.record_type=a.record_type "
                "AND r.public_id=a.alias_public_id "
                "WHERE a.record_type=? AND a.canonical_public_id=? "
                "AND r.local_id IS NOT NULL",
                (record_type, public_id),
            ).fetchall()
            for alias_row in alias_rows:
                alias_local_id = int(alias_row[0])
                conn.execute(
                    "DELETE FROM {} WHERE {}=?".format(
                        RECORD_TYPES[record_type].table,
                        RECORD_TYPES[record_type].primary_key),
                    (alias_local_id,),
                )
                alias_public_id = str(alias_row[1])
                conn.execute(
                    "DELETE FROM sync_changes WHERE record_type=? "
                    "AND public_id=?",
                    (record_type, alias_public_id),
                )
                conn.execute(
                    "DELETE FROM sync_conflicts WHERE record_type=? "
                    "AND public_id=?",
                    (record_type, alias_public_id),
                )
                conn.execute(
                    "DELETE FROM sync_records WHERE record_type=? "
                    "AND public_id=?",
                    (record_type, alias_public_id),
                )
                _mark_sync_exclusion(
                    conn, record_type, alias_public_id,
                    reason="identity_migrated")
        if local_id is not None:
            conn.execute(
                "DELETE FROM {} WHERE {}=?".format(
                    RECORD_TYPES[record_type].table,
                    RECORD_TYPES[record_type].primary_key),
                (local_id,),
            )
        local_id = None
    else:
        local_id = _write_payload(
            conn, record_type, public_id, incoming["payload"], local_id)
    conn.execute(
        "INSERT INTO sync_records("
        "record_type,local_id,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(record_type,public_id) DO UPDATE SET "
        "local_id=excluded.local_id,revision=excluded.revision,"
        "origin_device_id=excluded.origin_device_id,"
        "parent_origin_device_id=excluded.parent_origin_device_id,"
        "parent_revision=excluded.parent_revision,"
        "updated_at=excluded.updated_at,deleted_at=excluded.deleted_at,"
        "payload_hash=excluded.payload_hash",
        (
            record_type, local_id, public_id, incoming["revision"],
            incoming["origin_device_id"],
            incoming["parent_origin_device_id"],
            incoming["parent_revision"], incoming["updated_at"],
            incoming["deleted_at"],
            _payload_hash(incoming["payload"], incoming["deleted_at"]),
        ),
    )
    _mark_seen(conn, incoming)
    _append_change(conn, incoming)
    if incoming["deleted_at"] is not None:
        _scrub_deleted_record_history(conn, record_type, public_id)
    else:
        _drop_conflicts_superseded_by(conn, incoming)


def _require_incoming_message_pair_identity(
        conn: sqlite3.Connection, incoming: dict) -> None:
    """Keep one immutable message and pair-role bound to one wire identity."""
    if (incoming.get("record_type") != "message"
            or incoming.get("deleted_at") is not None):
        return
    payload = incoming.get("payload")
    if not isinstance(payload, dict):
        raise SyncError("message sync payload is invalid")
    pair_public_id = payload.get("turn_pair_public_id")
    role = payload.get("role")
    existing = conn.execute(
        "SELECT m.turn_pair_public_id,r.revision,r.origin_device_id "
        "FROM messages m LEFT JOIN sync_records r "
        "ON r.record_type='message' AND r.local_id=m.id "
        "AND r.public_id=m.public_id WHERE m.public_id=?",
        (incoming.get("public_id"),),
    ).fetchone()
    if existing is not None:
        current_pair = str(existing[0] or "")
        if current_pair != pair_public_id:
            causal_pair_backfill = (
                current_pair == ""
                and bool(pair_public_id)
                and existing[1] is not None
                and incoming.get("parent_origin_device_id") == existing[2]
                and incoming.get("parent_revision") == int(existing[1])
                and int(incoming.get("revision") or 0) > int(existing[1])
            )
            if not causal_pair_backfill:
                raise SyncError(
                    "immutable message turn-pair identity changed")
    if pair_public_id:
        collision = conn.execute(
            "SELECT public_id FROM messages WHERE turn_pair_public_id=? "
            "AND role=? AND public_id<>? LIMIT 1",
            (pair_public_id, role, incoming.get("public_id")),
        ).fetchone()
        if collision is not None:
            raise SyncError("completed-turn pair role is already bound")


def _apply_one_canonical(
        conn: sqlite3.Connection, incoming: dict, *,
        replay_deferred: bool = False) -> str:
    if _incoming_is_excluded_guest(conn, incoming):
        # Do not retain the payload in seen/change/conflict tables. The peer
        # cursor is still acknowledged by apply_change_batch, making retries
        # idempotent without preserving guest content.
        return "ignored"
    seen = conn.execute(
        "SELECT 1 FROM sync_seen_versions WHERE record_type=? "
        "AND public_id=? AND origin_device_id=? AND revision=?",
        (
            incoming["record_type"], incoming["public_id"],
            incoming["origin_device_id"], incoming["revision"],
        ),
    ).fetchone()
    if seen and not replay_deferred:
        return "ignored"
    _require_incoming_message_pair_identity(conn, incoming)
    raw_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (incoming["record_type"], incoming["public_id"]),
    ).fetchone()
    if raw_meta is None:
        collision = _schema_active_path_collision(conn, incoming)
        if collision is not None:
            created = _queue_conflict(
                conn, collision, incoming, "concurrent_schema_path")
            _mark_schema_projection_conflict(
                conn, collision, incoming, "concurrent_schema_path")
            _mark_seen(conn, incoming)
            _append_change(conn, incoming)
            return "conflict" if created else "ignored"
        _install_incoming(conn, incoming, None)
        return "applied"
    meta = _row_dict(raw_meta)
    local = _record_from_meta(conn, meta)
    if _clinical_versions_are_concurrent(local, incoming):
        created = _queue_conflict(
            conn, local, incoming, "concurrent_schema_edit")
        _mark_schema_projection_conflict(
            conn, local, incoming, "concurrent_schema_edit")
        _mark_seen(conn, incoming)
        _append_change(conn, incoming)
        return "conflict" if created else "ignored"
    if _incoming_wins(local, incoming):
        _install_incoming(conn, incoming, meta)
        return "applied"
    if local["deleted_at"] is not None:
        # Never retain a stale live payload after this installation has
        # crossed the privacy deletion boundary.  Concurrent tombstones are
        # semantically identical too, so keep only the deterministic head.
        _mark_seen(conn, incoming)
        _scrub_deleted_record_history(
            conn, incoming["record_type"], incoming["public_id"])
        return "ignored"
    _mark_seen(conn, incoming)
    _append_change(conn, incoming)
    return "ignored"


def _apply_one(
        conn: sqlite3.Connection, incoming: dict, device_id: str) -> str:
    _incoming_schema_lineage_is_safe(conn, incoming)
    normalized, original = _canonicalize_singleton_incoming(
        conn, incoming, device_id)
    result = _apply_one_canonical(conn, normalized)
    if original is not None:
        # Keep only the content-free delivery marker for the legacy id.  The
        # normalized record/conflict is stored exclusively under the stable
        # singleton identity.
        _mark_seen(conn, original)
        _mark_sync_exclusion(
            conn, original["record_type"], original["public_id"],
            reason="identity_migrated")
    return result


def _stored_conflict_record(raw: object) -> Optional[dict]:
    incoming = _decode_stored_record(raw)
    if not incoming:
        return None
    try:
        validate_change_batch({
            "kind": BATCH_KIND,
            "version": BATCH_VERSION,
            "sender_device_id": incoming.get("origin_device_id"),
            "after_cursor": 0,
            "cursor": 0,
            "ack_cursor": 0,
            "has_more": False,
            "records": [incoming],
        })
    except SyncError:
        return None
    return incoming


def _clinical_replay_is_currently_safe(
        conn: sqlite3.Connection, incoming: dict) -> bool:
    """Recheck every local privacy gate before replaying stored content.

    Conflict/deferred JSON can outlive the consent and safety state under
    which it was first received.  A replay must therefore be held to the
    same generation, device-confirmation and exact-source rules as a fresh
    clinical batch.  Tombstones remain admissible because they contain no
    payload and may only remove an old projection.
    """
    if (incoming.get("record_type") not in _SCHEMA_CLINICAL_RECORD_TYPES
            or incoming.get("deleted_at") is not None):
        return True
    payload = incoming.get("payload")
    if not isinstance(payload, dict):
        return False
    conversation_public_id = payload.get("conversation_public_id")
    if not isinstance(conversation_public_id, str):
        return False
    conv_id = _find_local_id(
        conn, "conversation", conversation_public_id)
    if conv_id is None:
        return False
    conv = conn.execute(
        "SELECT is_guest,safety_hold FROM conversations WHERE id=?",
        (conv_id,),
    ).fetchone()
    consent = conn.execute(
        "SELECT schema_clinical_sync_enabled,"
        "schema_clinical_sync_initialized,"
        "schema_clinical_sync_generation FROM session_meta WHERE conv=?",
        (conv_id,),
    ).fetchone()
    if (not conv or int(conv[0] or 0) != 0 or int(conv[1] or 0) != 0
            or not consent or int(consent[0] or 0) != 1
            or int(consent[1] or 0) != 1):
        return False
    try:
        _validate_incoming_schema_flow_contract(conn, incoming, {})
        generation = _incoming_schema_generation(conn, incoming, {})
    except (SyncError, _MissingDependency):
        return False
    if generation != int(consent[2] or 0):
        return False
    try:
        _incoming_schema_lineage_is_safe(conn, incoming)
    except (SyncError, _MissingDependency):
        return False
    return True


def _close_schema_projection_conflict_marker(
        conn: sqlite3.Connection, path_public_id: Optional[str]) -> None:
    """Resolve the content-free UI marker once no payload conflict remains."""
    if (not path_public_id or not _table_exists(
            conn, "schema_path_sync_conflicts")):
        return
    for row in conn.execute(
            "SELECT record_type,local_json,incoming_json "
            "FROM sync_conflicts WHERE status='open'").fetchall():
        if str(row[0] or "") not in _SCHEMA_CLINICAL_RECORD_TYPES:
            continue
        for raw in (row[1], row[2]):
            record = _decode_stored_record(raw)
            if (_schema_path_public_id_from_record(record or {})
                    == path_public_id):
                return
    stamp = _utcnow()
    conn.execute(
        "DELETE FROM schema_path_sync_conflicts WHERE "
        "path_public_id=? AND status='resolved'", (path_public_id,))
    conn.execute(
        "UPDATE schema_path_sync_conflicts SET status='resolved',"
        "resolved_at=?,updated=? WHERE path_public_id=? "
        "AND status='open'", (stamp, stamp, path_public_id))


def _discard_stored_conflict(
        conn: sqlite3.Connection, conflict_id: int,
        incoming: dict) -> None:
    """Erase a no-longer-admissible stored branch and its delivery copy."""
    event_id = _event_id(incoming)
    path_public_id = _schema_path_public_id_from_record(incoming)
    conn.execute("DELETE FROM sync_changes WHERE event_id=?", (event_id,))
    conn.execute(
        "DELETE FROM sync_seen_versions WHERE record_type=? AND public_id=? "
        "AND origin_device_id=? AND revision=?",
        (
            incoming["record_type"], incoming["public_id"],
            incoming["origin_device_id"], incoming["revision"],
        ),
    )
    conn.execute("DELETE FROM sync_conflicts WHERE id=?", (conflict_id,))
    _close_schema_projection_conflict_marker(conn, path_public_id)


def _drop_conflicts_superseded_by(
        conn: sqlite3.Connection, installed: dict) -> None:
    """Remove conflict UI payloads made obsolete by a causal descendant.

    Keep delivery/seen rows: unlike a privacy discard, an explicitly stopped
    branch remains valid history and its seen marker prevents a stale peer
    from presenting the old active version again.
    """
    rows = conn.execute(
        "SELECT id,incoming_json FROM sync_conflicts WHERE status='open' "
        "AND record_type=? AND public_id=?",
        (installed["record_type"], installed["public_id"]),
    ).fetchall()
    removed = False
    path_public_id = _schema_path_public_id_from_record(installed)
    for row in rows:
        previous = _stored_conflict_record(row[1])
        if previous is None:
            conn.execute("DELETE FROM sync_conflicts WHERE id=?", (row[0],))
            removed = True
            continue
        if (_event_id(previous) != _event_id(installed) and (
                _is_direct_child(installed, previous)
                or _is_known_ancestor(previous, installed))):
            conn.execute("DELETE FROM sync_conflicts WHERE id=?", (row[0],))
            removed = True
    if removed:
        _close_schema_projection_conflict_marker(conn, path_public_id)


def _scrub_ineligible_stored_clinical_conflicts(
        conn: sqlite3.Connection) -> int:
    """Erase queued clinical branches after consent/safety scope changes."""
    placeholders = ",".join(
        "?" for _ in sorted(_SCHEMA_CLINICAL_RECORD_TYPES))
    rows = conn.execute(
        "SELECT id,incoming_json FROM sync_conflicts WHERE status='open' "
        "AND record_type IN ({})".format(placeholders),
        tuple(sorted(_SCHEMA_CLINICAL_RECORD_TYPES)),
    ).fetchall()
    removed = 0
    for row in rows:
        incoming = _stored_conflict_record(row[1])
        if incoming is None:
            conn.execute("DELETE FROM sync_conflicts WHERE id=?", (row[0],))
            removed += 1
            continue
        if not _clinical_replay_is_currently_safe(conn, incoming):
            _discard_stored_conflict(conn, int(row[0]), incoming)
            removed += 1
    return removed


def _record_rejected_incoming_schema_path(
        conn: sqlite3.Connection, incoming: dict,
        device_id: str) -> dict:
    """Install an explicitly rejected active path as a stopped child.

    A different-public-id active-path collision cannot be resolved by merely
    closing its conflict row: the remote peer would keep its own path active
    and conflict again.  Keeping the losing path as stopped preserves its
    already-consented history while freeing the one-active-path invariant on
    both peers before the chosen path is replayed.
    """
    _validate_device_id(device_id)
    if (incoming.get("record_type") != "schema_path"
            or incoming.get("deleted_at") is not None
            or not isinstance(incoming.get("payload"), dict)):
        raise SyncError("active Schema path branch is invalid")
    raw_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (incoming["record_type"], incoming["public_id"]),
    ).fetchone()
    meta = _row_dict(raw_meta) if raw_meta else None
    parent_origin = (
        meta["origin_device_id"] if meta
        else incoming["origin_device_id"])
    parent_revision = int(
        meta["revision"] if meta else incoming["revision"])
    stamp = _utcnow()
    payload = dict(incoming["payload"])
    payload["status"] = "stopped"
    payload["closed_at"] = stamp
    payload["updated"] = stamp
    payload["pause_reason"] = "sync_conflict_rejected"
    payload["resume_required"] = 0
    if type(payload.get("revision")) is int:
        payload["revision"] = int(payload["revision"]) + 1
    stopped = {
        "record_type": incoming["record_type"],
        "public_id": incoming["public_id"],
        "revision": parent_revision + 1,
        "origin_device_id": device_id,
        "parent_origin_device_id": parent_origin,
        "parent_revision": parent_revision,
        "updated_at": stamp,
        "deleted_at": None,
        "payload": payload,
    }
    _validate_payload("schema_path", payload)
    _validate_schema_public_identity(
        "schema_path", stopped["public_id"], payload)
    _install_incoming(conn, stopped, meta)
    return stopped


def _auto_merge_legacy_conflicts(conn: sqlite3.Connection) -> int:
    """Consume manual v3 race rows under the deterministic v4 policy.

    The incoming branch was marked seen when v3 queued the row, so the replay
    deliberately bypasses only that delivery check.  Current physical/shadow
    state is still compared with the stored branch, and deletion/exclusion
    rules remain authoritative.  Consumed rows are removed so losing clinical
    text is not retained merely as obsolete merge UI state.
    """
    rows = conn.execute(
        "SELECT id,incoming_json FROM sync_conflicts WHERE status='open' "
        "AND reason IN ('concurrent_clinical_edit',"
        "'immutable_record_mismatch') ORDER BY id"
    ).fetchall()
    merged = 0
    for row in rows:
        incoming = _stored_conflict_record(row[1])
        if incoming is None:
            conn.execute("DELETE FROM sync_conflicts WHERE id=?", (row[0],))
            continue
        if not _clinical_replay_is_currently_safe(conn, incoming):
            _discard_stored_conflict(conn, int(row[0]), incoming)
            continue
        try:
            _apply_one_canonical(
                conn, incoming, replay_deferred=True)
        except _MissingDependency:
            # Preserve a valid record until its parent can be installed.
            continue
        conn.execute("DELETE FROM sync_conflicts WHERE id=?", (row[0],))
        merged += 1
    return merged


def _retry_deferred_conflicts(conn: sqlite3.Connection) -> int:
    """Install cross-batch children after their required parent arrives."""
    rows = conn.execute(
        "SELECT id,incoming_json FROM sync_conflicts WHERE status='open' "
        "AND reason='missing_dependency' ORDER BY id"
    ).fetchall()
    completed = 0
    progressed = True
    while rows and progressed:
        progressed = False
        remaining = []
        for row in rows:
            incoming = _stored_conflict_record(row[1])
            if incoming is None:
                conn.execute(
                    "DELETE FROM sync_conflicts WHERE id=?", (row[0],))
                progressed = True
                continue
            if not _clinical_replay_is_currently_safe(conn, incoming):
                _discard_stored_conflict(conn, int(row[0]), incoming)
                progressed = True
                continue
            try:
                _apply_one_canonical(
                    conn, incoming, replay_deferred=True)
            except _MissingDependency:
                remaining.append(row)
                continue
            conn.execute("DELETE FROM sync_conflicts WHERE id=?", (row[0],))
            completed += 1
            progressed = True
        rows = remaining
    return completed


def _incoming_schema_generation(
        conn: sqlite3.Connection, record: dict,
        incoming_paths: dict[str, tuple[str, int, int]]) -> int:
    """Resolve one live approved record to its privacy generation."""
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise SyncError("clinical sync payload is invalid")
    record_type = record.get("record_type")
    direct = payload.get("clinical_generation")
    if record_type in {
            "schema_path", "schema_candidate", "schema_message_meta"}:
        if type(direct) is not int or direct < 1:
            raise SyncError("clinical sync generation is missing")
        path_public_id = payload.get("path_public_id")
        if record_type != "schema_path" and path_public_id not in (None, ""):
            incoming = incoming_paths.get(path_public_id)
            if incoming is not None:
                if (incoming[0] != payload.get("conversation_public_id")
                        or incoming[1] != direct):
                    raise SyncError("clinical sync path generation is invalid")
            else:
                path_id = _find_local_id(
                    conn, "schema_path", path_public_id)
                row = (conn.execute(
                    "SELECT p.clinical_generation,v.public_id "
                    "FROM schema_paths p JOIN conversations v ON v.id=p.conv "
                    "WHERE p.id=?", (path_id,),
                ).fetchone() if path_id is not None else None)
                if (not row or row[1] != payload.get(
                        "conversation_public_id") or int(row[0] or 0) != direct):
                    raise SyncError("clinical sync path generation is invalid")
        return direct
    path_public_id = payload.get("path_public_id")
    if not isinstance(path_public_id, str):
        raise SyncError("clinical sync path generation is missing")
    incoming = incoming_paths.get(path_public_id)
    if incoming is not None:
        if incoming[0] != payload.get("conversation_public_id"):
            raise SyncError("clinical sync path scope is invalid")
        return incoming[1]
    path_id = _find_local_id(conn, "schema_path", path_public_id)
    if path_id is None:
        raise _MissingDependency("schema_path")
    row = conn.execute(
        "SELECT p.clinical_generation,v.public_id FROM schema_paths p "
        "JOIN conversations v ON v.id=p.conv WHERE p.id=?", (path_id,)
    ).fetchone()
    if (not row or row[1] != payload.get("conversation_public_id")
            or type(row[0]) is not int or int(row[0]) < 1):
        raise SyncError("clinical sync path generation is invalid")
    return int(row[0])


def _incoming_schema_flow_version(
        conn: sqlite3.Connection, record: dict,
        incoming_paths: dict[str, tuple[str, int, int]]) -> Optional[int]:
    """Resolve an attached clinical projection to its exact flow version."""
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise SyncError("clinical sync payload is invalid")
    if record.get("record_type") == "schema_path":
        flow_version = payload.get("flow_version")
        if type(flow_version) is not int or flow_version not in (4, 5):
            raise SyncError("clinical sync path flow is invalid")
        return flow_version
    path_public_id = payload.get("path_public_id")
    if path_public_id in (None, ""):
        if record.get("record_type") in {
                "schema_candidate", "schema_message_meta"}:
            return None
        raise SyncError("clinical sync path flow is unavailable")
    incoming = incoming_paths.get(path_public_id)
    if incoming is not None:
        return incoming[2]
    path_id = _find_local_id(conn, "schema_path", path_public_id)
    if path_id is None:
        raise _MissingDependency("schema_path")
    row = conn.execute(
        "SELECT flow_version FROM schema_paths WHERE id=?", (path_id,)
    ).fetchone()
    if not row or type(row[0]) is not int or int(row[0]) not in (4, 5):
        raise SyncError("clinical sync path flow is invalid")
    return int(row[0])


def _validate_incoming_schema_flow_contract(
        conn: sqlite3.Connection, record: dict,
        incoming_paths: dict[str, tuple[str, int, int]]) -> None:
    """Reject cross-flow artifacts before any clinical content is retained."""
    if (record.get("record_type") not in _SCHEMA_CLINICAL_RECORD_TYPES
            or record.get("deleted_at") is not None):
        return
    flow_version = _incoming_schema_flow_version(
        conn, record, incoming_paths)
    if flow_version is None:
        return
    payload = record["payload"]
    record_type = record["record_type"]
    if record_type == "schema_step" and not \
            _schema_step_state_is_valid_for_flow(
                flow_version, payload.get("stage"), payload.get("step")):
        raise SyncError("Schema step does not belong to its path flow")
    if record_type == "schema_focus_check" and flow_version == 5:
        raise SyncError("Schema v5 does not accept focus rating records")


def _require_incoming_schema_clinical_consent(
        conn: sqlite3.Connection, records: list[dict]) -> set[tuple]:
    """Reject live clinical payloads before retaining any of their content.

    The preference bit may be synchronized, but receiving approved deep work
    is a separate local disclosure choice.  Tombstones remain admissible so a
    withdrawn/deleted record can erase an old local projection even after the
    user has turned sharing off.
    """
    incoming_paths = {}
    for record in records:
        if (record.get("record_type") != "schema_path"
                or record.get("deleted_at") is not None):
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise SyncError("clinical sync payload is invalid")
        generation = payload.get("clinical_generation")
        if type(generation) is not int or generation < 1:
            raise SyncError("clinical sync generation is missing")
        flow_version = payload.get("flow_version")
        if type(flow_version) is not int or flow_version not in (4, 5):
            raise SyncError("clinical sync path flow is invalid")
        incoming_paths[record["public_id"]] = (
            payload.get("conversation_public_id"), generation,
            flow_version)

    stale = set()
    for record in records:
        if (record.get("record_type") not in _SCHEMA_CLINICAL_RECORD_TYPES
                or record.get("deleted_at") is not None):
            continue
        payload = record.get("payload")
        public_id = (payload.get("conversation_public_id")
                     if isinstance(payload, dict) else None)
        if not isinstance(public_id, str):
            raise SyncError("clinical sync conversation is missing")
        local_id = _find_local_id(conn, "conversation", public_id)
        if local_id is None:
            raise ClinicalSyncConfirmationRequired(
                "clinical sync requires local conversation confirmation")
        try:
            _validate_incoming_schema_flow_contract(
                conn, record, incoming_paths)
            generation = _incoming_schema_generation(
                conn, record, incoming_paths)
        except _MissingDependency:
            # A properly ordered v8 stream either carries the path earlier in
            # this batch or has already installed it.  Never retain an
            # unscoped clinical child as a generic deferred conflict.
            raise SyncError("clinical sync path generation is unavailable") \
                from None
        conv = conn.execute(
            "SELECT is_guest,safety_hold FROM conversations WHERE id=?",
            (local_id,)
        ).fetchone()
        consent = conn.execute(
            "SELECT schema_clinical_sync_enabled,"
            "schema_clinical_sync_initialized,"
            "schema_clinical_sync_generation FROM session_meta WHERE conv=?",
            (local_id,),
        ).fetchone()
        local_generation = int(consent[2] or 0) if consent else 0
        identity = (
            record["record_type"], record["public_id"],
            record["origin_device_id"], record["revision"])
        if generation < local_generation or (
                consent and int(consent[0] or 0) == 0
                and generation <= local_generation):
            stale.add(identity)
            continue
        if conv and int(conv[1] or 0) == 1:
            # Do not acknowledge this batch.  Once the local safety hold is
            # cleared a fresh QR can replay the exact same clinical records;
            # no payload, conflict row or cursor is retained meanwhile.
            raise ClinicalSyncSafetyPause(
                "clinical sync is paused by a conversation safety hold")
        if (not conv or int(conv[0] or 0) != 0 or not consent
                or generation != local_generation
                or int(consent[0] or 0) != 1
                or int(consent[1] or 0) != 1):
            raise ClinicalSyncConfirmationRequired(
                "clinical sync requires explicit confirmation on this device")
    return stale


def _incoming_schema_lineage_is_safe(
        conn: sqlite3.Connection, incoming: dict) -> None:
    """Validate exact message lineage after parent messages are installed."""
    record_type = incoming.get("record_type")
    if (record_type not in _SCHEMA_CLINICAL_RECORD_TYPES
            or incoming.get("deleted_at") is not None):
        return
    payload = incoming.get("payload")
    if not isinstance(payload, dict):
        raise SyncError("clinical sync payload is invalid")
    conv_id = _find_local_id(
        conn, "conversation", payload.get("conversation_public_id"))
    if conv_id is None:
        raise _MissingDependency("conversation")

    def message_id(field: str) -> Optional[int]:
        public_id = payload.get(field)
        if public_id in (None, ""):
            return None
        local_id = _find_local_id(conn, "message", public_id)
        if local_id is None:
            raise _MissingDependency("message")
        return local_id

    if record_type == "schema_path":
        user_id = message_id("focus_source_user_public_id")
        assistant_id = message_id("focus_source_assistant_public_id")
    elif record_type == "schema_healthy_adult":
        if not _schema_source_pair_is_safe(
                conn, conv_id, message_id("source_message_public_id"),
                message_id("source_assistant_message_public_id")):
            raise SyncError("clinical sync source message is not safe")
        existing = conn.execute(
            "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
            (record_type, incoming.get("public_id")),
        ).fetchone()
        if existing is not None and existing["deleted_at"] is None:
            local_payload = _record_from_meta(
                conn, _row_dict(existing)).get("payload") or {}
            immutable_fields = {
                "conversation_public_id", "path_public_id",
                "source_message_public_id",
                "source_assistant_message_public_id", "source",
                "evidence", "created",
            }
            if any(payload.get(key) != local_payload.get(key)
                   for key in immutable_fields):
                raise SyncError(
                    "Healthy Adult evidence fields are immutable")
        return
    else:
        user_id = message_id("source_user_message_public_id")
        assistant_id = message_id("source_assistant_message_public_id")
    if (user_id is None) != (assistant_id is None):
        raise SyncError("clinical sync source pair is incomplete")
    if user_id is not None and not _schema_source_pair_is_safe(
            conn, conv_id, user_id, assistant_id):
        raise SyncError("clinical sync source pair is not safe")
    if record_type == "schema_growth":
        environment_user = message_id(
            "environment_source_user_message_public_id")
        environment_assistant = message_id(
            "environment_source_assistant_message_public_id")
        if (environment_user is None) != (environment_assistant is None):
            raise SyncError(
                "clinical sync environment source pair is incomplete")
        if (payload.get("environment_status") == "active"
                and environment_user is None):
            raise SyncError(
                "active clinical environment requires a source pair")
        if (environment_user is not None
                and not _schema_source_pair_is_safe(
                    conn, conv_id, environment_user,
                    environment_assistant)):
            raise SyncError(
                "clinical sync environment source message is not safe")
    if record_type == "schema_transfer" and not _schema_source_pair_is_safe(
            conn, conv_id,
            message_id("trigger_source_user_message_public_id"),
            message_id("trigger_source_assistant_message_public_id")):
        raise SyncError("clinical sync trigger source is not safe")
    if record_type == "schema_message_meta":
        message = message_id("message_public_id")
        if assistant_id is None or message != assistant_id:
            raise SyncError("clinical sync meta anchor is invalid")


def _incoming_message_dependency_depths(records: list[dict]) -> dict[str, int]:
    """Order in-batch reply parents first without trusting sender list order."""
    live = {
        record["public_id"]: record
        for record in records
        if record.get("record_type") == "message"
        and record.get("deleted_at") is None
        and isinstance(record.get("payload"), dict)
    }
    depths = {}
    visiting = set()

    def depth(public_id: str) -> int:
        if public_id in depths:
            return depths[public_id]
        if public_id in visiting:
            raise SyncError("message reply graph is cyclic")
        visiting.add(public_id)
        parent = live[public_id]["payload"].get("reply_to_public_id")
        value = 1 + depth(parent) if parent in live else 0
        visiting.remove(public_id)
        depths[public_id] = value
        return value

    for public_id in live:
        depth(public_id)
    return depths


def apply_change_batch(
        conn: sqlite3.Connection,
        batch: dict,
        device_id: str,
) -> dict:
    """Merge a validated batch to one deterministic, privacy-safe state."""
    _validate_device_id(device_id)
    validate_change_batch(batch)
    message_depths = _incoming_message_dependency_depths(batch["records"])
    _sync_tables(conn)
    stale_clinical = _require_incoming_schema_clinical_consent(
        conn, batch["records"])
    scrub_guest_sync_state(conn)
    _scrub_hard_deleted_parent_payloads(conn)
    _redact_ineligible_module_records(conn, device_id)
    _scrub_ineligible_stored_clinical_conflicts(conn)
    legacy_merged = _auto_merge_legacy_conflicts(conn)
    deferred_applied = _retry_deferred_conflicts(conn)
    if batch["ack_cursor"] > local_cursor_high_water(conn):
        raise SyncError("peer acknowledged an unknown local cursor")
    summary = {
        "applied": 0,
        "ignored": 0,
        "conflicts": 0,
        "deferred": 0,
        "auto_merged": legacy_merged,
        "deferred_applied": deferred_applied,
        "cursor": batch["cursor"],
        "ack_cursor": batch["ack_cursor"],
    }
    records = sorted(
        batch["records"],
        key=lambda item: (
            1 if item["deleted_at"] is not None else 0,
            (
                -_DEPENDENCY_ORDER[item["record_type"]]
                if item["deleted_at"] is not None
                else _DEPENDENCY_ORDER[item["record_type"]]
            ),
            (
                message_depths.get(item["public_id"], 0)
                if item["deleted_at"] is None else 0
            ),
            (
                int(item["revision"])
                if item["record_type"] == "message" else 0
            ),
        ),
    )
    pending = list(records)
    while pending:
        next_pending = []
        progressed = False
        for record in pending:
            identity = (
                record["record_type"], record["public_id"],
                record["origin_device_id"], record["revision"])
            if identity in stale_clinical:
                # A withdrawn generation never revives.  Acknowledge its
                # metadata without retaining payload, conflict text or a
                # physical row, so a stale third peer cannot retry forever.
                _mark_seen(conn, record)
                summary["ignored"] += 1
                progressed = True
                continue
            try:
                result = _apply_one(conn, record, device_id)
            except _MissingDependency:
                if (record["record_type"] in _SCHEMA_CLINICAL_RECORD_TYPES
                        and record["deleted_at"] is None):
                    # Clinical source lineage is not a best-effort graph
                    # dependency.  Retaining the payload for a later retry
                    # would bypass the exact completed-message safety gate
                    # and leak it into conflict/change history.  Reject the
                    # transaction so a fresh, correctly ordered QR batch can
                    # replay without advancing the peer cursor.
                    raise SyncError(
                        "clinical sync source dependency is unavailable") \
                        from None
                next_pending.append(record)
                continue
            progressed = True
            if result == "applied":
                summary["applied"] += 1
            elif result == "conflict":
                summary["conflicts"] += 1
            else:
                summary["ignored"] += 1
        if not next_pending or not progressed:
            pending = next_pending
            break
        pending = next_pending
    for record in pending:
        local = {
            "record_type": record["record_type"],
            "public_id": record["public_id"],
            "missing_dependency": True,
        }
        if not _queue_conflict(
                conn, local, record, "missing_dependency"):
            summary["ignored"] += 1
        _mark_seen(conn, record)
        _append_change(conn, record)
        summary["deferred"] += 1
    summary["deferred_applied"] += _retry_deferred_conflicts(conn)
    summary["auto_merged"] += _auto_merge_legacy_conflicts(conn)
    _scrub_hard_deleted_parent_payloads(conn)
    # Ordinary records in this very batch may have just enabled a safety
    # hold or withdrawn the clinical-sharing preference.  Re-run the stored
    # branch scrub after those mutations and before committing the peer
    # cursor; no waiting conflict payload may survive that boundary.
    _scrub_ineligible_stored_clinical_conflicts(conn)
    conn.execute(
        "INSERT INTO sync_peer_cursors("
        "peer_device_id,remote_cursor,acknowledged_local_cursor,updated_at) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(peer_device_id) DO UPDATE SET "
        "remote_cursor=MAX(remote_cursor,excluded.remote_cursor),"
        "acknowledged_local_cursor=MAX("
        "acknowledged_local_cursor,excluded.acknowledged_local_cursor),"
        "updated_at=excluded.updated_at",
        (
            batch["sender_device_id"], batch["cursor"],
            batch["ack_cursor"], _utcnow(),
        ),
    )
    scrub_guest_sync_state(conn)
    return summary


def local_cursor_high_water(conn: sqlite3.Connection) -> int:
    """Return the greatest cursor ever allocated by this change log."""
    _sync_tables(conn)
    current = conn.execute(
        "SELECT COALESCE(MAX(cursor),0) FROM sync_changes").fetchone()[0]
    allocated = 0
    if _table_exists(conn, "sqlite_sequence"):
        row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='sync_changes'"
        ).fetchone()
        allocated = int(row[0]) if row else 0
    return max(int(current or 0), allocated)


def projection_summary(conn: sqlite3.Connection) -> dict:
    """Return a content-free proof of the current live shared projection.

    This is intentionally not a database checksum.  Delivery jobs, secrets,
    device settings, private ADHD notes and historical tombstone bookkeeping
    are local by design.  Two peers are user-visibly equal when every live,
    allowlisted logical head (including its causal metadata and payload hash)
    matches and neither side has an unresolved dependency/conflict.
    """
    _sync_tables(conn)
    rows = conn.execute(
        "SELECT r.record_type,r.public_id,r.revision,r.origin_device_id,"
        "r.parent_origin_device_id,r.parent_revision,r.updated_at,"
        "r.payload_hash FROM sync_records r "
        "WHERE r.deleted_at IS NULL AND r.local_id IS NOT NULL "
        "AND NOT EXISTS(SELECT 1 FROM sync_excluded_records e "
        "WHERE e.record_type=r.record_type AND e.public_id=r.public_id) "
        "ORDER BY r.record_type,r.public_id"
    ).fetchall()
    heads = []
    type_counts = {}
    for row in rows:
        record_type = str(row[0])
        if record_type not in RECORD_TYPES:
            # Unknown historical shadow state is not part of this protocol's
            # allowlisted user projection.
            continue
        head = [
            record_type, str(row[1]), int(row[2]), str(row[3]),
            None if row[4] is None else str(row[4]),
            None if row[5] is None else int(row[5]),
            str(row[6]), str(row[7]),
        ]
        heads.append(head)
        type_counts[record_type] = type_counts.get(record_type, 0) + 1
    pending = int(conn.execute(
        "SELECT COUNT(*) FROM sync_conflicts WHERE status='open'"
    ).fetchone()[0])
    proof = {
        "projection_version": PROJECTION_VERSION,
        "protocol_version": BATCH_VERSION,
        "heads": heads,
    }
    return {
        "projection_version": PROJECTION_VERSION,
        "protocol_version": BATCH_VERSION,
        "digest": hashlib.sha256(
            _canonical_json(proof).encode("utf-8")).hexdigest(),
        "live_count": len(heads),
        "type_counts": {
            key: type_counts[key] for key in sorted(type_counts)
        },
        "pending": pending,
    }


def peer_cursor(conn: sqlite3.Connection, peer_device_id: str) -> int:
    """Return the highest accepted cursor advertised by one peer."""
    _validate_device_id(peer_device_id)
    _sync_tables(conn)
    row = conn.execute(
        "SELECT remote_cursor FROM sync_peer_cursors WHERE peer_device_id=?",
        (peer_device_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def peer_ack_cursor(conn: sqlite3.Connection, peer_device_id: str) -> int:
    """Return the local cursor which this peer explicitly acknowledged."""
    _validate_device_id(peer_device_id)
    _sync_tables(conn)
    row = conn.execute(
        "SELECT acknowledged_local_cursor FROM sync_peer_cursors "
        "WHERE peer_device_id=?",
        (peer_device_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def peer_offered_cursor(conn: sqlite3.Connection, peer_device_id: str) -> int:
    """Return the greatest local cursor actually offered to this peer."""
    _validate_device_id(peer_device_id)
    _sync_tables(conn)
    row = conn.execute(
        "SELECT offered_local_cursor FROM sync_peer_cursors "
        "WHERE peer_device_id=?",
        (peer_device_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def record_peer_offer(
        conn: sqlite3.Connection, peer_device_id: str, cursor: int) -> int:
    """Persist a monotonic upper bound for resumable acknowledgements."""
    _validate_device_id(peer_device_id)
    if type(cursor) is not int or cursor < 0:
        raise SyncError("invalid offered cursor")
    _sync_tables(conn)
    if cursor > local_cursor_high_water(conn):
        raise SyncError("cannot offer an unknown local cursor")
    conn.execute(
        "INSERT INTO sync_peer_cursors("
        "peer_device_id,remote_cursor,acknowledged_local_cursor,"
        "offered_local_cursor,updated_at) VALUES(?,0,0,?,?) "
        "ON CONFLICT(peer_device_id) DO UPDATE SET "
        "offered_local_cursor=MAX("
        "offered_local_cursor,excluded.offered_local_cursor),"
        "updated_at=excluded.updated_at",
        (peer_device_id, cursor, _utcnow()),
    )
    return peer_offered_cursor(conn, peer_device_id)


def list_conflicts(
        conn: sqlite3.Connection, *, status: str = "open"
) -> list[dict]:
    if status not in ("open", "resolved"):
        raise SyncError("invalid conflict status")
    _sync_tables(conn)
    scrub_guest_sync_state(conn)
    _scrub_hard_deleted_parent_payloads(conn)
    _scrub_ineligible_stored_clinical_conflicts(conn)
    return [
        _row_dict(row) for row in conn.execute(
            "SELECT * FROM sync_conflicts WHERE status=? ORDER BY id",
            (status,),
        ).fetchall()
    ]


def resolve_conflict(
        conn: sqlite3.Connection,
        conflict_id: int,
        resolution: str,
) -> None:
    """Close a conflict after the application performs explicit UI review.

    ``resolution`` is audit text (for example ``keep_local`` or
    ``manual_merge``).  If the user chooses incoming/merged content, the
    application should write that content to the real row first and call
    ``record_local_change``; this produces a new causal version instead of
    silently replacing the clinical record here.
    """
    if type(conflict_id) is not int or conflict_id < 1:
        raise SyncError("invalid conflict id")
    if not isinstance(resolution, str) or not resolution.strip():
        raise SyncError("resolution is required")
    _sync_tables(conn)
    scrub_guest_sync_state(conn)
    conflict = conn.execute(
        "SELECT * FROM sync_conflicts WHERE id=? AND status='open'",
        (conflict_id,),
    ).fetchone()
    if conflict is None:
        raise SyncError("open conflict not found")
    path_public_id = None
    if str(conflict["record_type"] or "") in _SCHEMA_CLINICAL_RECORD_TYPES:
        for raw in (conflict["incoming_json"], conflict["local_json"]):
            record = _decode_stored_record(raw)
            if record:
                path_public_id = _schema_path_public_id_from_record(record)
                if path_public_id:
                    break
    cursor = conn.execute(
        "UPDATE sync_conflicts SET status='resolved',resolved_at=?,"
        "resolution=? WHERE id=? AND status='open'",
        (_utcnow(), resolution.strip()[:120], conflict_id),
    )
    if cursor.rowcount != 1:
        raise SyncError("open conflict not found")
    if path_public_id and _table_exists(
            conn, "schema_path_sync_conflicts"):
        still_open = False
        for row in conn.execute(
                "SELECT record_type,local_json,incoming_json "
                "FROM sync_conflicts WHERE status='open'").fetchall():
            if str(row[0] or "") not in _SCHEMA_CLINICAL_RECORD_TYPES:
                continue
            for raw in (row[1], row[2]):
                record = _decode_stored_record(raw)
                if (_schema_path_public_id_from_record(record or {})
                        == path_public_id):
                    still_open = True
                    break
            if still_open:
                break
        if not still_open:
            stamp = _utcnow()
            conn.execute(
                "DELETE FROM schema_path_sync_conflicts WHERE "
                "path_public_id=? AND status='resolved'", (path_public_id,))
            conn.execute(
                "UPDATE schema_path_sync_conflicts SET status='resolved',"
                "resolved_at=?,updated=? WHERE path_public_id=? "
                "AND status='open'", (stamp, stamp, path_public_id))


__all__ = [
    "BATCH_KIND", "BATCH_VERSION", "PROJECTION_VERSION",
    "RECORD_TYPES", "SyncError", "ClinicalSyncConfirmationRequired",
    "ClinicalSyncSafetyPause",
    "initialize_sync", "refresh_local_changes",
    "record_local_change", "record_local_delete",
    "scrub_guest_sync_state",
    "scrub_deleted_record_history", "scrub_all_deleted_history",
    "reset_sync_state",
    "export_change_batch", "validate_change_batch", "apply_change_batch",
    "local_cursor_high_water", "projection_summary",
    "peer_cursor", "peer_ack_cursor", "peer_offered_cursor",
    "record_peer_offer",
    "list_conflicts", "resolve_conflict",
]
