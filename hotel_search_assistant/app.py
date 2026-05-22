from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import date, datetime
from json import JSONDecodeError
from typing import Any

from .config import DEFAULT_CONFIG_PATH, load_config
from .llm import LLMClient, LLMError


EXIT_COMMANDS = {"exit", "quit", "q"}
SHOW_FILTER_COMMANDS = {"filter", "filters", "show filter", "show filters"}
REQUIRED_FIELDS = ("destination", "check_in_date", "check_out_date", "guests")
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
MONTH_NUMBERS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
FILTER_EVIDENCE_KEYWORDS = {
    "air_conditioning": ("air conditioning", "a/c", " ac ", "aircon", "conditioner"),
    "heating": ("heating", "heated room", "warm room"),
    "private_bathroom": ("private bathroom", "own bathroom", "ensuite", "en-suite"),
    "soundproof_room": ("soundproof", "quiet room", "quiet hotel"),
    "yoga_area": ("yoga", "space to stretch", "stretch"),
    "library": ("library", "reading room"),
    "bedside_reading_lights": ("reading light", "reading lights", "bedside light", "bedside lights"),
    "boutique_hotel": ("boutique",),
    "coworking_lounge": ("coworking", "co-working", "coworking-style lounge", "co-working-style lounge"),
    "english_speaking_staff": ("english",),
    "dutch_speaking_staff": ("dutch",),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Console hotel search assistant")
    parser.add_argument(
        "-c",
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to JSON config file",
    )
    parser.add_argument(
        "-q",
        "--query",
        help="Run one request and exit",
    )
    parser.add_argument(
        "--force-json",
        action="store_true",
        help="Force JSON Schema output. Use when the request has destination, dates and guests.",
    )
    return parser.parse_args()


def run() -> int:
    args = parse_args()
    config = load_config(args.config)
    client = LLMClient(config)
    conversation_history: list[dict[str, str]] = []

    if args.query:
        return handle_request(
            client,
            args.query,
            previous_state=None,
            conversation_history=conversation_history,
            force_json=args.force_json,
        )[1]

    print("Hotel Search Assistant")
    print("Type your hotel request. Commands: filter, filters, show filter, show filters, exit, quit, q")
    print("Wait for the You > prompt, then type the request in this app window.")
    print(f"Provider: {config.provider}; model: {config.model}")

    previous_state: dict[str, Any] | None = None
    while True:
        try:
            user_message = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print_final_filter(previous_state)
            return 0

        if not user_message:
            continue
        normalized_message = user_message.lower()
        if normalized_message in SHOW_FILTER_COMMANDS:
            print_final_filter(previous_state)
            continue
        if normalized_message in EXIT_COMMANDS:
            print_final_filter(previous_state)
            return 0

        parsed, exit_code = handle_request(
            client,
            user_message,
            previous_state=previous_state,
            conversation_history=conversation_history,
            force_json=args.force_json,
        )
        if parsed is not None:
            previous_state = parsed
        if exit_code != 0:
            continue


def handle_request(
    client: LLMClient,
    user_message: str,
    *,
    previous_state: dict[str, Any] | None,
    conversation_history: list[dict[str, str]],
    force_json: bool,
) -> tuple[dict[str, Any] | None, int]:
    prompt = build_user_prompt(user_message, previous_state, conversation_history)

    try:
        reply = client.complete(prompt, force_json=force_json)
    except LLMError as error:
        assistant_reply = format_llm_error(error)
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", assistant_reply)
        print_assistant_response(assistant_reply)
        return None, 1

    parsed = extract_json_object(reply)
    if parsed is None:
        evidence_text = build_evidence_text(conversation_history, user_message)
        if should_ask_conflict(conversation_history):
            conflict_question = detect_conflict_question(previous_state or {"filters": {}}, evidence_text)
            if conflict_question is not None:
                remember_message(conversation_history, "user", user_message)
                remember_message(conversation_history, "assistant", conflict_question)
                print_assistant_response(conflict_question)
                return previous_state, 0

        updated_state = apply_short_guest_reply_to_previous_state(
            previous_state,
            user_message,
            conversation_history,
        )
        if updated_state is None:
            updated_state = apply_explicit_updates_to_previous_state(
                previous_state,
                user_message,
                conversation_history,
            )
        if updated_state is not None:
            evidence_text = build_evidence_text(conversation_history, user_message)
            date_validation_error = validate_stay_dates(updated_state)
            clarifying_question = build_missing_required_question(updated_state, evidence_text)
            if date_validation_error is not None:
                remember_message(conversation_history, "user", user_message)
                remember_message(conversation_history, "assistant", date_validation_error)
                print_assistant_response(date_validation_error)
                return None, 0
            if clarifying_question is not None:
                remember_message(conversation_history, "user", user_message)
                remember_message(conversation_history, "assistant", clarifying_question)
                print_assistant_response(clarifying_question)
                return updated_state, 0

            assistant_reply = json.dumps(updated_state, indent=2, ensure_ascii=False)
            remember_message(conversation_history, "user", user_message)
            remember_message(conversation_history, "assistant", assistant_reply)
            print_assistant_response(assistant_reply)
            return updated_state, 0

        assistant_reply = reply.strip()
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", assistant_reply)
        print_assistant_response(assistant_reply)
        return None, 0

    evidence_text = build_evidence_text(conversation_history, user_message)
    sanitized = sanitize_filter_payload(parsed, client.config.json_schema, previous_state, evidence_text)
    apply_explicit_filter_rules(sanitized, evidence_text)
    apply_explicit_change_rules(sanitized, user_message.lower())
    apply_explicit_date_rules(sanitized, evidence_text)
    clear_guessed_dates(sanitized, evidence_text)
    apply_explicit_guest_rule(sanitized, evidence_text, user_message, conversation_history, previous_state)
    if should_ask_conflict(conversation_history):
        conflict_question = detect_conflict_question(sanitized, evidence_text)
        if conflict_question is not None:
            remember_message(conversation_history, "user", user_message)
            remember_message(conversation_history, "assistant", conflict_question)
            print_assistant_response(conflict_question)
            return sanitized, 0

    date_validation_error = validate_stay_dates(sanitized)
    if date_validation_error is not None:
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", date_validation_error)
        print_assistant_response(date_validation_error)
        return None, 0

    clarifying_question = build_missing_required_question(sanitized, evidence_text)
    if clarifying_question is not None:
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", clarifying_question)
        print_assistant_response(clarifying_question)
        return sanitized, 0

    assistant_reply = json.dumps(sanitized, indent=2, ensure_ascii=False)
    remember_message(conversation_history, "user", user_message)
    remember_message(conversation_history, "assistant", assistant_reply)
    print_assistant_response(assistant_reply)
    return sanitized, 0


def build_user_prompt(
    user_message: str,
    previous_state: dict[str, Any] | None,
    conversation_history: list[dict[str, str]],
) -> str:
    sections = [
        "Use the full conversation context below, including all earlier user messages and assistant replies.",
        "Do not ask again for destination, dates, guests, or filter preferences if they were already provided earlier.",
        "If the current user message is a short confirmation like 'yes', apply it to the previous assistant question and the original hotel request.",
        "Never default guests to 2. If guests are not explicitly provided in the conversation, set guests to null or ask how many guests will stay.",
        "If there are contradictory requests, ask about that conflict before asking for missing guests.",
        "When returning JSON, return only a strict JSON object. Do not include intro text, Markdown fences, comments, or explanations.",
        "Inside filters, include only keys from the configured schema. Do not invent aliases like soundproofing ratings.",
        "Do not infer filters from vague preferences. For example, cozy does not imply heating, and hotel room does not imply private_bathroom.",
        "Do not include false filters unless the user explicitly removes or rejects a filter from previous state.",
    ]

    if conversation_history:
        sections.append("Conversation so far:")
        sections.append(format_conversation_history(conversation_history))

    if previous_state is not None:
        previous = json.dumps(previous_state, ensure_ascii=False)
        sections.extend(
            [
                "Previous extracted hotel search state:",
                previous,
                "Apply the current user request to that state when it asks to add, remove, or change filters.",
            ]
        )

    sections.extend(["Current user request:", user_message])
    return "\n\n".join(sections)


def remember_message(conversation_history: list[dict[str, str]], role: str, content: str) -> None:
    conversation_history.append({"role": role, "content": content})


def format_conversation_history(conversation_history: list[dict[str, str]]) -> str:
    return "\n".join(
        f"{message['role'].title()}: {message['content']}" for message in conversation_history
    )


def print_final_filter(previous_state: dict[str, Any] | None) -> None:
    if previous_state is None:
        print_assistant_response("No complete hotel search filter has been formed yet.")
        return

    print_assistant_response(
        "Final hotel search filter payload:\n"
        f"{json.dumps(previous_state, indent=2, ensure_ascii=False)}"
    )


def print_assistant_response(text: str) -> None:
    print(f"\nAssistant:\n{text}")


def sanitize_filter_payload(
    payload: dict[str, Any],
    json_schema: dict[str, Any],
    previous_state: dict[str, Any] | None,
    evidence_text: str,
) -> dict[str, Any]:
    filter_schema = json_schema["properties"]["filters"]["properties"]
    allowed_filters = set(filter_schema)
    previous_filters = previous_state.get("filters", {}) if previous_state else {}

    sanitized: dict[str, Any] = {
        "destination": value_or_previous(payload, previous_state, "destination"),
        "check_in_date": value_or_previous(payload, previous_state, "check_in_date"),
        "check_out_date": value_or_previous(payload, previous_state, "check_out_date"),
        "guests": value_or_previous(payload, previous_state, "guests"),
        "filters": {},
    }

    filters = payload.get("filters")
    if not isinstance(filters, dict):
        return sanitized

    for key, value in filters.items():
        if key not in allowed_filters:
            continue
        if value is False and previous_state is None:
            continue
        if value is False and key not in previous_filters:
            continue
        if value is True and not has_filter_evidence(key, evidence_text):
            continue
        sanitized["filters"][key] = value

    return sanitized


def value_or_previous(
    payload: dict[str, Any],
    previous_state: dict[str, Any] | None,
    key: str,
) -> Any:
    value = payload.get(key)
    if value is not None:
        return value
    if previous_state is None:
        return None
    return previous_state.get(key)


def build_evidence_text(conversation_history: list[dict[str, str]], user_message: str) -> str:
    parts = [message["content"] for message in conversation_history if message["role"] == "user"]
    parts.append(user_message)
    return "\n".join(parts).lower()


def has_filter_evidence(filter_name: str, evidence_text: str) -> bool:
    keywords = FILTER_EVIDENCE_KEYWORDS.get(filter_name)
    if keywords is None:
        return True
    return any(keyword in evidence_text for keyword in keywords)


def apply_explicit_filter_rules(payload: dict[str, Any], evidence_text: str) -> None:
    filters = payload.setdefault("filters", {})

    if re.search(r"\bwi[-\s]?fi\b|\bwifi\b|wireless internet", evidence_text):
        filters["wi_fi"] = True

    if "rain shower" in evidence_text:
        filters["bathroom_rain_shower"] = True

    if re.search(r"\breal double bed\b|\bking bed\b|\bqueen bed\b", evidence_text):
        filters["real_double_bed_not_twins"] = True
        filters["king_queen_bed_150cm_plus"] = True

    if re.search(r"\bnot\s+(two\s+)?(twins|twin beds|single beds)\b", evidence_text):
        filters["real_double_bed_not_twins"] = True
        filters["double_bed_131_150cm"] = False

    if re.search(r"\bsoundproof(?:ed|ing)?\b|\bquiet room\b|\bquiet hotel\b", evidence_text):
        filters["soundproof_room"] = True

    if re.search(r"\byoga\b|\bspace to stretch\b|\bstretch\b", evidence_text):
        filters["yoga_area"] = True

    if re.search(r"\breading room\b|\blibrary\b", evidence_text):
        filters["library"] = True

    if re.search(r"\breading lights?\b|\bbedside lights?\b", evidence_text):
        filters["bedside_reading_lights"] = True

    room_size = extract_room_size_min(evidence_text)
    if room_size is not None:
        filters["room_size_sqm_min"] = room_size
        if room_size >= 30:
            filters["room_size_30sqm_plus"] = True

    if "boutique" in evidence_text:
        filters["boutique_hotel"] = True

    if re.search(r"\bco[-\s]?working[-\s]?(style\s+)?lounge\b|\bcoworking\b", evidence_text):
        filters["coworking_lounge"] = True

    if re.search(r"\benglish\b", evidence_text):
        filters["english_speaking_staff"] = True

    if re.search(r"\bdutch\b", evidence_text):
        filters["dutch_speaking_staff"] = True

    if re.search(r"\brooftop pool\b", evidence_text):
        filters["rooftop_pool"] = True
        filters["any_pool"] = True

    if re.search(r"\bheated pool\b", evidence_text):
        filters["heated_pool"] = True
        filters["any_pool"] = True

    if re.search(r"\boutdoor pool\b", evidence_text):
        filters["outdoor_pool"] = True
        filters["any_pool"] = True

    if re.search(r"\bindoor pool\b", evidence_text):
        filters["indoor_pool"] = True
        filters["any_pool"] = True

    if re.search(r"\b(children'?s|kids?) pool\b", evidence_text):
        filters["childrens_pool"] = True
        filters["any_pool"] = True

    if re.search(r"\b(swimming pool|pool)\b", evidence_text):
        filters["any_pool"] = True


def apply_explicit_change_rules(payload: dict[str, Any], current_message: str) -> None:
    filters = payload.setdefault("filters", {})

    if re.search(r"\b(add|with|need|include)\s+parking\b", current_message):
        filters["parking"] = True

    if re.search(r"\b(remove|without|no|exclude)\s+(the\s+)?(swimming\s+)?pool\b", current_message):
        filters["any_pool"] = False
        filters["indoor_pool"] = False
        filters["outdoor_pool"] = False
        filters["rooftop_pool"] = False
        filters["heated_pool"] = False
        filters["childrens_pool"] = False

    if re.search(r"\b(remove|without|no|exclude)\s+breakfast\b", current_message):
        filters["breakfast"] = False


def extract_room_size_min(evidence_text: str) -> int | None:
    patterns = (
        r"(?:at least|minimum|min\.?|from)\s+(\d{1,3})\s*(?:square meters|square metres|sqm|sq m|m2)",
        r"(\d{1,3})\s*(?:square meters|square metres|sqm|sq m|m2)\s+(?:or more|minimum|min)",
    )
    for pattern in patterns:
        match = re.search(pattern, evidence_text)
        if match is not None:
            return int(match.group(1))
    return None


def clear_guessed_dates(payload: dict[str, Any], evidence_text: str) -> None:
    if find_partial_date_range(evidence_text) is not None:
        payload["check_in_date"] = None
        payload["check_out_date"] = None


def apply_explicit_date_rules(payload: dict[str, Any], evidence_text: str) -> None:
    date_range = extract_explicit_date_range(evidence_text)
    if date_range is None:
        return

    check_in, check_out = date_range
    payload["check_in_date"] = check_in
    payload["check_out_date"] = check_out


def extract_explicit_date_range(evidence_text: str) -> tuple[str, str] | None:
    month_names = "|".join(MONTH_NUMBERS)

    full_range = re.search(
        rf"\b(?:from\s+)?({month_names})\s+(\d{{1,2}}),?\s+(20\d{{2}})\s+"
        rf"(?:to|until|through|-|–)\s+({month_names})\s+(\d{{1,2}}),?\s+(20\d{{2}})\b",
        evidence_text,
        flags=re.IGNORECASE,
    )
    if full_range is not None:
        start_month, start_day, start_year, end_month, end_day, end_year = full_range.groups()
        return (
            format_date(int(start_year), MONTH_NUMBERS[start_month.lower()], int(start_day)),
            format_date(int(end_year), MONTH_NUMBERS[end_month.lower()], int(end_day)),
        )

    same_month_range = re.search(
        rf"\b(?:from\s+)?({month_names})\s+(\d{{1,2}})\s*(?:-|–|to)\s*(\d{{1,2}}),?\s+(20\d{{2}})\b",
        evidence_text,
        flags=re.IGNORECASE,
    )
    if same_month_range is not None:
        month, start_day, end_day, year = same_month_range.groups()
        month_number = MONTH_NUMBERS[month.lower()]
        return (
            format_date(int(year), month_number, int(start_day)),
            format_date(int(year), month_number, int(end_day)),
        )

    return None


def format_date(year: int, month: int, day: int) -> str:
    return date(year, month, day).isoformat()


def apply_explicit_updates_to_previous_state(
    previous_state: dict[str, Any] | None,
    user_message: str,
    conversation_history: list[dict[str, str]],
) -> dict[str, Any] | None:
    if previous_state is None:
        return None

    evidence_text = build_evidence_text(conversation_history, user_message)
    updated_state = copy.deepcopy(previous_state)
    before = json.dumps(updated_state, sort_keys=True, ensure_ascii=False)

    apply_explicit_date_rules(updated_state, evidence_text)
    apply_explicit_guest_rule(updated_state, evidence_text, user_message, conversation_history, previous_state)
    apply_explicit_change_rules(updated_state, user_message.lower())

    after = json.dumps(updated_state, sort_keys=True, ensure_ascii=False)
    if before == after:
        return None
    return updated_state


def apply_explicit_guest_rule(
    payload: dict[str, Any],
    evidence_text: str,
    user_message: str,
    conversation_history: list[dict[str, str]],
    previous_state: dict[str, Any] | None,
) -> None:
    guest_count = extract_guest_count(evidence_text)
    if guest_count is None and last_assistant_asked_for_guests(conversation_history):
        guest_count = extract_guest_count(user_message.lower(), allow_standalone=True)
    if guest_count is not None:
        payload["guests"] = guest_count
        return

    if previous_state is not None and previous_state.get("guests") is not None:
        payload["guests"] = previous_state["guests"]
        return

    payload["guests"] = None


def apply_short_guest_reply_to_previous_state(
    previous_state: dict[str, Any] | None,
    user_message: str,
    conversation_history: list[dict[str, str]],
) -> dict[str, Any] | None:
    if previous_state is None or not last_assistant_asked_for_guests(conversation_history):
        return None

    guest_count = extract_guest_count(user_message.lower(), allow_standalone=True)
    if guest_count is None:
        return None

    updated_state = copy.deepcopy(previous_state)
    updated_state["guests"] = guest_count
    return updated_state


def last_assistant_asked_for_guests(conversation_history: list[dict[str, str]]) -> bool:
    for message in reversed(conversation_history):
        if message["role"] != "assistant":
            continue
        content = message["content"].lower()
        return (
            "how many guests" in content
            or "number of guests" in content
            or "guests will stay" in content
        )
    return False


def last_assistant_asked_conflict(conversation_history: list[dict[str, str]]) -> bool:
    for message in reversed(conversation_history):
        if message["role"] != "assistant":
            continue
        content = message["content"].lower()
        return "which is more important" in content
    return False


def conflict_was_answered(conversation_history: list[dict[str, str]]) -> bool:
    for index, message in enumerate(conversation_history):
        if message["role"] != "assistant":
            continue
        if "which is more important" not in message["content"].lower():
            continue
        return any(
            later_message["role"] == "user"
            for later_message in conversation_history[index + 1 :]
        )
    return False


def should_ask_conflict(conversation_history: list[dict[str, str]]) -> bool:
    return not last_assistant_asked_conflict(conversation_history) and not conflict_was_answered(conversation_history)


def extract_guest_count(evidence_text: str, allow_standalone: bool = False) -> int | None:
    standalone_text = evidence_text.strip().lower()
    if allow_standalone:
        if re.fullmatch(r"\d{1,2}", standalone_text):
            return int(standalone_text)
        if standalone_text in NUMBER_WORDS:
            return NUMBER_WORDS[standalone_text]

    if re.search(r"\b(solo|alone|single traveler|single traveller|traveling solo|travelling solo)\b", evidence_text):
        return 1

    if re.search(r"\bcouple\b", evidence_text):
        return 2

    digit_patterns = (
        r"\b(\d{1,2})\s+(?:guests?|people|persons?|adults?|travellers?|travelers?)\b",
        r"\b(?:for|with|party of)\s+(\d{1,2})\b",
    )
    for pattern in digit_patterns:
        match = re.search(pattern, evidence_text)
        if match is not None:
            return int(match.group(1))

    word_group = "|".join(NUMBER_WORDS)
    word_patterns = (
        rf"\b({word_group})\s+(?:guests?|people|persons?|adults?|travellers?|travelers?)\b",
        rf"\b(?:for|with|party of)\s+({word_group})\b",
    )
    for pattern in word_patterns:
        match = re.search(pattern, evidence_text)
        if match is not None:
            return NUMBER_WORDS[match.group(1)]

    return None


def detect_conflict_question(payload: dict[str, Any], evidence_text: str) -> str | None:
    filters = payload.get("filters", {})
    if not isinstance(filters, dict):
        filters = {}

    meal_conflict = detect_meal_conflict(filters, evidence_text)
    if meal_conflict is not None:
        return meal_conflict

    bed_conflict = detect_bed_conflict(filters, evidence_text)
    if bed_conflict is not None:
        return bed_conflict

    pet_conflict = detect_pet_conflict(filters, evidence_text)
    if pet_conflict is not None:
        return pet_conflict

    return None


def detect_meal_conflict(filters: dict[str, Any], evidence_text: str) -> str | None:
    no_meals_requested = re.search(
        r"\b(no|without|exclude|excluding)\s+(meals?|food|meal plan)\b|\broom only\b",
        evidence_text,
    )
    if no_meals_requested is None:
        return None

    requested_meals = []
    meal_labels = {
        "breakfast": "breakfast",
        "lunch": "lunch",
        "dinner": "dinner",
        "all_meals": "all meals",
        "all_inclusive": "all inclusive",
        "room_service": "room service",
    }
    for key, label in meal_labels.items():
        if filters.get(key) is True or re.search(rf"\b{re.escape(label)}\b", evidence_text):
            requested_meals.append(label)

    if not requested_meals:
        return None

    meal_text = ", ".join(dict.fromkeys(requested_meals))
    return f"You asked for {meal_text} but also no meals. Which is more important?"


def detect_bed_conflict(filters: dict[str, Any], evidence_text: str) -> str | None:
    wants_real_double = (
        filters.get("real_double_bed_not_twins") is True
        or filters.get("king_queen_bed_150cm_plus") is True
        or re.search(r"\breal double bed\b|\bking bed\b|\bqueen bed\b", evidence_text) is not None
    )
    wants_single_or_twins = (
        filters.get("single_twin_bed_80_130cm") is True
        or re.search(r"\b(two\s+)?(twins|twin beds|single beds)\b", evidence_text) is not None
    )

    explicitly_rejects_twins = re.search(r"\bnot\s+(two\s+)?(twins|twin beds|single beds)\b", evidence_text)
    if wants_real_double and wants_single_or_twins and explicitly_rejects_twins is None:
        return "You asked for a real double bed but also twin/single beds. Which bed type is more important?"

    return None


def detect_pet_conflict(filters: dict[str, Any], evidence_text: str) -> str | None:
    wants_all_pets = filters.get("all_pets_allowed") is True or "all pets" in evidence_text
    rejects_dogs = filters.get("dogs_allowed") is False or re.search(r"\b(no|without)\s+dogs\b", evidence_text)
    rejects_cats = filters.get("cats_allowed") is False or re.search(r"\b(no|without)\s+cats\b", evidence_text)

    if wants_all_pets and rejects_dogs:
        return "You asked for all pets allowed but dogs not allowed. Which is more important?"
    if wants_all_pets and rejects_cats:
        return "You asked for all pets allowed but cats not allowed. Which is more important?"

    return None


def build_missing_required_question(payload: dict[str, Any], evidence_text: str) -> str | None:
    if not payload.get("destination"):
        return "What destination should I search in?"

    if not payload.get("check_in_date") or not payload.get("check_out_date"):
        partial_dates = find_partial_date_range(evidence_text)
        if partial_dates is not None:
            return f"What year is {partial_dates} for?"
        return "What are the check-in and check-out dates? Please use YYYY-MM-DD format."

    if not payload.get("guests"):
        return "How many guests will stay?"

    return None


def validate_stay_dates(payload: dict[str, Any], today: date | None = None) -> str | None:
    check_in_raw = payload.get("check_in_date")
    check_out_raw = payload.get("check_out_date")
    if not isinstance(check_in_raw, str):
        return None

    try:
        check_in = datetime.strptime(check_in_raw, "%Y-%m-%d").date()
    except ValueError:
        return "Please provide check-in date in YYYY-MM-DD format."

    current_date = today or date.today()
    if check_in < current_date:
        return (
            f"The check-in date {check_in_raw} has already passed. "
            "Please provide future check-in and check-out dates."
        )

    if not isinstance(check_out_raw, str):
        return None

    try:
        check_out = datetime.strptime(check_out_raw, "%Y-%m-%d").date()
    except ValueError:
        return "Please provide check-out date in YYYY-MM-DD format."

    if check_out <= check_in:
        return "Check-out date must be after check-in date. Please provide valid stay dates."

    return None


def find_partial_date_range(evidence_text: str) -> str | None:
    if re.search(r"\b20\d{2}\b", evidence_text):
        return None

    match = re.search(
        r"\b(\d{1,2}\s*[-–]\s*\d{1,2}\s+"
        r"(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|"
        r"aug|august|sep|sept|september|oct|october|nov|november|dec|december))\b",
        evidence_text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group(1)


def format_llm_error(error: LLMError) -> str:
    message = str(error)
    if "localhost:11434" in message or "WinError 10061" in message:
        return (
            "LLM error: cannot connect to Ollama at http://localhost:11434.\n"
            "Start Ollama in another terminal first:\n"
            "  ollama pull llama3.1:8b\n"
            "  ollama serve\n\n"
            "After Ollama starts, run scripts\\start.bat again or retry your request at the > prompt."
        )

    return f"LLM error: {message}"


def extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = strip_json_line_comments(strip_markdown_fence(text.strip()))
    decoder = json.JSONDecoder()

    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    return None


def strip_json_line_comments(text: str) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if char == "\\" and in_string:
            result.append(char)
            escaped = not escaped
            index += 1
            continue

        if char == '"' and not escaped:
            in_string = not in_string

        escaped = False

        if not in_string and char == "/" and next_char == "/":
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue

        result.append(char)
        index += 1

    return "".join(result)


def strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


if __name__ == "__main__":
    raise SystemExit(run())
