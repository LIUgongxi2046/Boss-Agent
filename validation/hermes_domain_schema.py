FIELDS = {
    "boss.meeting.confirm": {"meeting_id", "meeting_version", "draft_version", "review_sha256"},
    "boss.meeting.cancel": {"meeting_id", "expected_version", "reason"},
    "boss.meeting.held": {"meeting_id", "expected_version", "reason"},
    "boss.minutes.confirm": {"meeting_id", "expected_version", "source_id", "source_version"},
    "boss.minutes.assignment.create": {"meeting_id", "minute_version", "entry_id", "purpose", "coordinator_id", "due_at", "timezone", "evidence_requirements"},
    "boss.assignment.create": {"purpose", "coordinator_id", "due_at", "timezone", "evidence_requirements", "related_meeting_id", "related_event_ids", "source_refs", "content_version"},
}

MEETING_DRAFT_FIELDS = {"meeting_id", "meeting_version", "expected_version", "purpose", "starts_at", "ends_at", "timezone", "preparation_due_at", "participant_ids", "source_refs"}
MEETING_DRAFT_PROPERTIES = {
    "meeting_id": {"type": "string", "minLength": 1},
    "meeting_version": {"type": "string", "pattern": "^(0|[1-9][0-9]{0,8})$"},
    "expected_version": {"type": "string", "pattern": "^(0|[1-9][0-9]{0,8})$"},
    "purpose": {"type": "string", "minLength": 1, "maxLength": 1200},
    "starts_at": {"type": "string", "minLength": 1, "maxLength": 100},
    "ends_at": {"type": "string", "minLength": 1, "maxLength": 100},
    "timezone": {"type": "string", "minLength": 1, "maxLength": 80},
    "preparation_due_at": {"type": ["string", "null"], "maxLength": 100},
    "participant_ids": {"type": "array", "minItems": 1, "maxItems": 32, "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
    "source_refs": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "object", "additionalProperties": False, "required": ["source_id", "version"], "properties": {"source_id": {"type": "string", "minLength": 1}, "version": {"type": "string", "pattern": "^(0|[1-9][0-9]{0,8})$"}}}},
}
MEETING_DRAFT_SCHEMA = {"type": "object", "additionalProperties": False, "required": sorted(MEETING_DRAFT_FIELDS), "properties": MEETING_DRAFT_PROPERTIES}

MINUTES_DRAFT_FIELDS = {"meeting_id", "meeting_version", "source_id", "source_version", "expected_version", "entries"}
MINUTES_DRAFT_SCHEMA = {"type": "object", "additionalProperties": False, "required": sorted(MINUTES_DRAFT_FIELDS), "properties": {
    "meeting_id": {"type": "string", "minLength": 1},
    "meeting_version": {"type": "string", "pattern": "^(0|[1-9][0-9]{0,8})$"},
    "source_id": {"type": "string", "minLength": 1},
    "source_version": {"type": "string", "pattern": "^(0|[1-9][0-9]{0,8})$"},
    "expected_version": {"type": "string", "pattern": "^(0|[1-9][0-9]{0,8})$"},
    "entries": {"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "object", "additionalProperties": False, "required": ["kind", "text", "source_anchor"], "properties": {
        "kind": {"enum": ["OPINION", "SUGGESTION", "DECISION", "ASSIGNMENT_DRAFT"]},
        "text": {"type": "string", "minLength": 1, "maxLength": 1400},
        "source_anchor": {"type": "string", "minLength": 1, "maxLength": 200},
    }}},
}}

RUNTIME_BRIEF_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["source_ids", "request_key", "format_name", "expected_goal_revision", "meeting_id", "meeting_version", "sections"],
    "properties": {
        "source_ids": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True, "items": {"type": "string", "minLength": 1, "maxLength": 100}},
        "request_key": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "\\S"},
        "format_name": {"enum": ["MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"]},
        "expected_goal_revision": {"type": "integer", "minimum": 1},
        "meeting_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "meeting_version": {"type": "string", "minLength": 1, "maxLength": 128},
        "previous_artifact_id": {"type": "string", "format": "uuid"},
        "expected_version": {"type": "integer", "minimum": 1},
        "sections": {"type": "array", "minItems": 1, "maxItems": 200, "items": {"type": "object", "additionalProperties": False,
            "required": ["kind", "text", "source_ids"], "properties": {
                "kind": {"enum": ["AGENDA", "FACT", "COMMITMENT", "CONSENSUS", "CONFLICT", "DECISION", "MISSING"]},
                "text": {"type": "string", "minLength": 1, "maxLength": 12000, "pattern": "\\S"},
                "source_ids": {"type": "array", "uniqueItems": True, "maxItems": 100, "items": {"type": "string", "minLength": 1, "maxLength": 100}}}}}},
    "dependentRequired": {"previous_artifact_id": ["expected_version"], "expected_version": ["previous_artifact_id"]}}
