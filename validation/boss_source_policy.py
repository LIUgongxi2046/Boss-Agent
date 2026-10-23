from datetime import date, datetime, time

from business import require

SOURCE_STATES = {
    "RECEIVED", "VALID", "INCOMPLETE", "CONFLICTED",
    "SUPERSEDED", "WITHDRAWN", "EXPIRED",
}


def _instant(value, reference):
    require(isinstance(value, str), "来源有效时间格式无效")
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.min, tzinfo=reference.tzinfo)
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, "来源有效时间必须包含时区")
    return result


def source_validity(document, business_at):
    reference = datetime.fromisoformat(business_at)
    require(reference.tzinfo is not None, "业务时间必须包含时区")
    state = document.get("validity_state", "VALID")
    require(isinstance(state, str) and state in SOURCE_STATES, "来源有效状态无效")
    if document.get("withdrawn") is True or state == "WITHDRAWN":
        return "WITHDRAWN"
    start_value = document.get("valid_from")
    if start_value is None:
        start_value = document.get("published_at")
    if start_value is None:
        return "INCOMPLETE"
    start = _instant(start_value, reference)
    end = _instant(document["valid_until"], reference) if document.get("valid_until") is not None else None
    require(start is None or end is None or start < end, "来源有效时间范围无效")
    if end is not None and reference >= end:
        return "EXPIRED"
    if start is not None and reference < start:
        return "RECEIVED"
    return state
