"""Existing keyword interpretation as a replaceable, network-free adapter."""

import json
import re

from newsroom_agent.conditions import FIELD_OPTIONS, route_question


class MockQuestionPlanner:
    def interpret(self, question: str) -> str:
        source = route_question(question)
        values: dict[str, str | None] = {
            "entity": None, "metric": None, "period": None, "comparison": None,
        }
        filters: dict[str, str | None] = {}
        uncertain_fields = []
        for field, choices in FIELD_OPTIONS.get(source, {}).items():
            matches = []
            remaining = question
            # Match nested names once but retain separately mentioned alternatives.
            for choice in sorted(choices, key=len, reverse=True):
                if choice in remaining:
                    matches.append(choice)
                    remaining = remaining.replace(choice, " ")
            value = matches[0] if len(matches) == 1 else None
            if len(matches) > 1:
                uncertain_fields.append(field)
            if field in {"filters.frequency", "filters.report_type"}:
                # Annual is the existing workshop default, not a model inference.
                value = None if any(w in question for w in ("분기", "월간", "월별")) else "연간"
            if field.startswith("filters."):
                filters[field.removeprefix("filters.")] = value
            else:
                values[field] = value

        periods = re.findall(r"(?<!\d)(\d{4})\s*년?\s*(?:-|~|–|부터)\s*(\d{4})(?!\d)", question)
        values["period"] = "-".join(periods[0]) if len(periods) == 1 else None
        if len(periods) > 1:
            uncertain_fields.append("period")
        return json.dumps({
            "selected_source": source, **values, "filters": filters,
            "uncertain_fields": uncertain_fields,
        }, ensure_ascii=False)
