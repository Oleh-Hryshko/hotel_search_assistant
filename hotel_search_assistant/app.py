from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import date, datetime, timedelta
from json import JSONDecodeError
from typing import Any

from .config import DEFAULT_CONFIG_PATH, load_config
from .llm import LLMClient, LLMError


EXIT_COMMANDS = {"exit", "quit", "q"}
SHOW_FILTER_COMMANDS = {"filters"}
REQUIRED_FIELDS = ("destination", "check_in_date", "check_out_date", "guests")
REMOVE_WORDS_PATTERN = r"(remove|delete|drop|without|exclude|no)"
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
NIGHT_WORDS = NUMBER_WORDS
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
    "kitchen": ("self-catering", "self catering", "kitchen", "kitchenette"),
}
BOOLEAN_REMOVE_ALIASES = {
    "pool": ("any_pool", "indoor_pool", "outdoor_pool", "rooftop_pool", "heated_pool", "childrens_pool"),
    "swimming pool": ("any_pool", "indoor_pool", "outdoor_pool", "rooftop_pool", "heated_pool", "childrens_pool"),
    "breakfast": ("breakfast",),
    "parking": ("parking",),
    "wi-fi": ("wi_fi",),
    "wifi": ("wi_fi",),
    "full board": ("all_meals", "all_inclusive"),
    "all meals": ("all_meals",),
}
MEAL_FILTER_LABELS = {
    "breakfast": "breakfast",
    "lunch": "lunch",
    "dinner": "dinner",
    "all_meals": "all meals",
    "all_inclusive": "all inclusive",
    "room_service": "room service",
}
PET_FILTER_LABELS = {
    "all_pets_allowed": "all pets allowed",
    "dogs_allowed": "dogs allowed",
    "cats_allowed": "cats allowed",
    "pets_allowed_public_areas": "pets in public areas",
    "pets_welcome_restaurant": "pets welcome in restaurant",
    "allows_2_pets": "2 pets allowed",
    "allows_3_plus_pets": "3+ pets allowed",
    "pet_weight_10kg_allowed": "pets up to 10kg",
    "pet_weight_15kg_allowed": "pets up to 15kg",
    "pet_weight_20kg_allowed": "pets up to 20kg",
    "unattended_pets_allowed": "unattended pets allowed",
    "in_room_pet_station": "in-room pet station",
    "additional_pet_services": "additional pet services",
    "pet_walking_area_nearby": "pet walking area nearby",
    "pet_towels": "pet towels",
    "pet_toys": "pet toys",
}
PARKING_FILTER_LABELS = {
    "parking": "parking",
    "ev_charging": "EV charging",
    "accessible_parking_on_site": "accessible parking",
}
POOL_FILTER_LABELS = {
    "any_pool": "pool",
    "indoor_pool": "indoor pool",
    "outdoor_pool": "outdoor pool",
    "rooftop_pool": "rooftop pool",
    "heated_pool": "heated pool",
    "childrens_pool": "children's pool",
}
KIDS_FILTER_LABELS = {
    "kids_friendly_bathroom": "kids-friendly bathroom",
    "babysitting": "babysitting",
    "child_friendly_menu": "child-friendly menu",
    "family_friendly": "family-friendly hotel",
    "safe_balcony": "safe balcony",
    "tv_for_kids": "TV for kids",
    "playground_or_playroom": "playground or playroom",
    "childrens_pool": "children's pool",
    "entertainment_for_kids": "entertainment for kids",
    "safe_for_toddlers_kids": "safe for toddlers/kids",
    "crib_available": "crib available",
}
BEACH_FILTER_LABELS = {
    "beachfront": "beachfront",
    "private_beach_area": "private beach area",
    "beach_pool_towels": "beach/pool towels",
}
ELEVATOR_FILTER_LABELS = {
    "elevator_access": "elevator access",
    "wheelchair_accessible_elevator": "wheelchair-accessible elevator",
}
TEXT_FILTER_CONFLICTS = [
    {
        "negative_label": "no meals",
        "negative_pattern": r"\b(no|without|exclude|excluding)\s+(meals?|food|meal plan)\b|\broom only\b",
        "positive_filters": MEAL_FILTER_LABELS,
    },
    {
        "negative_label": "breakfast only",
        "negative_pattern": r"\b(breakfast only|only breakfast)\b",
        "positive_filters": {
            "lunch": "lunch",
            "dinner": "dinner",
            "all_meals": "all meals",
            "all_inclusive": "all inclusive",
            "room_service": "room service",
        },
    },
    {
        "negative_label": "no pets",
        "negative_pattern": r"\b(no|without|exclude|excluding)\s+pets?\b|\bpet[-\s]?free\b",
        "positive_filters": PET_FILTER_LABELS,
    },
    {
        "negative_label": "no dogs",
        "negative_pattern": r"\b(no|without|exclude|excluding)\s+dogs?\b",
        "positive_filters": {
            "dogs_allowed": "dogs allowed",
            "all_pets_allowed": "all pets allowed",
        },
    },
    {
        "negative_label": "no cats",
        "negative_pattern": r"\b(no|without|exclude|excluding)\s+cats?\b",
        "positive_filters": {
            "cats_allowed": "cats allowed",
            "all_pets_allowed": "all pets allowed",
        },
    },
    {
        "negative_label": "no parking",
        "negative_pattern": r"\b(no|without|exclude|excluding)\s+(parking|car park|garage)\b",
        "positive_filters": PARKING_FILTER_LABELS,
    },
    {
        "negative_label": "no pool",
        "negative_pattern": r"\b(no|without|exclude|excluding)\s+(pool|swimming pool)\b",
        "positive_filters": POOL_FILTER_LABELS,
    },
    {
        "negative_label": "adults only / no kids",
        "negative_pattern": r"\b(adults only|adult-only|no kids|without kids|no children|without children)\b",
        "positive_filters": KIDS_FILTER_LABELS,
    },
    {
        "negative_label": "family/kids stay",
        "negative_pattern": r"\b(with kids|with children|family trip|family stay|family-friendly)\b",
        "positive_filters": {"adults_only": "adults only"},
    },
    {
        "negative_label": "smoking allowed",
        "negative_pattern": r"\b(smoking allowed|smoking room|smoker friendly)\b",
        "positive_filters": {"smoke_free_property": "smoke-free property"},
    },
    {
        "negative_label": "no elevator",
        "negative_pattern": r"\b(no|without|exclude|excluding)\s+elevators?\b",
        "positive_filters": ELEVATOR_FILTER_LABELS,
    },
    {
        "negative_label": "no beach",
        "negative_pattern": r"\b(no|without|exclude|excluding)\s+beach\b",
        "positive_filters": BEACH_FILTER_LABELS,
    },
]
MUTUALLY_EXCLUSIVE_FILTER_GROUPS = [
    {
        "left_label": "adults only",
        "left_filters": ("adults_only",),
        "right_label": "kids/family facilities",
        "right_filters": tuple(KIDS_FILTER_LABELS),
    },
    {
        "left_label": "a real double/king/queen bed",
        "left_filters": ("real_double_bed_not_twins", "king_queen_bed_150cm_plus"),
        "right_label": "single/twin beds",
        "right_filters": ("single_twin_bed_80_130cm",),
    },
]


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
    print("Type your hotel request. Commands: filters, exit, quit, q")
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
        updated_state = apply_short_guest_reply_to_previous_state(
            previous_state,
            user_message,
            conversation_history,
        )
        if updated_state is None:
            updated_state = apply_nights_conflict_reply_to_previous_state(
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
            return respond_from_state(updated_state, evidence_text, conversation_history, user_message)

        if should_ask_conflict(conversation_history):
            conflict_question = detect_conflict_question(previous_state or {"filters": {}}, evidence_text)
            if conflict_question is not None:
                remember_message(conversation_history, "user", user_message)
                remember_message(conversation_history, "assistant", conflict_question)
                print_assistant_response(conflict_question)
                return previous_state, 0

        assistant_reply = reply.strip()
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", assistant_reply)
        print_assistant_response(assistant_reply)
        return None, 0

    evidence_text = build_evidence_text(conversation_history, user_message)
    sanitized = sanitize_filter_payload(parsed, client.config.json_schema, previous_state, evidence_text)
    extraction_text = evidence_text if previous_state is None else user_message.lower()
    apply_explicit_filter_rules(sanitized, extraction_text)
    apply_explicit_change_rules(sanitized, user_message.lower())
    apply_explicit_date_rules(sanitized, evidence_text)
    clear_guessed_dates(sanitized, evidence_text)
    apply_nights_to_missing_checkout(sanitized, evidence_text)
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

    stay_length_conflict = validate_requested_nights(
        sanitized,
        evidence_text,
        conversation_history,
        current_message=user_message,
    )
    if stay_length_conflict is not None:
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", stay_length_conflict)
        print_assistant_response(stay_length_conflict)
        return sanitized, 0

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


def respond_from_state(
    state: dict[str, Any],
    evidence_text: str,
    conversation_history: list[dict[str, str]],
    user_message: str,
) -> tuple[dict[str, Any] | None, int]:
    date_validation_error = validate_stay_dates(state)
    if date_validation_error is not None:
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", date_validation_error)
        print_assistant_response(date_validation_error)
        return None, 0

    stay_length_conflict = validate_requested_nights(
        state,
        evidence_text,
        conversation_history,
        current_message=user_message,
    )
    if stay_length_conflict is not None:
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", stay_length_conflict)
        print_assistant_response(stay_length_conflict)
        return state, 0

    if should_ask_conflict(conversation_history):
        conflict_question = detect_conflict_question(state, evidence_text)
        if conflict_question is not None:
            remember_message(conversation_history, "user", user_message)
            remember_message(conversation_history, "assistant", conflict_question)
            print_assistant_response(conflict_question)
            return state, 0

    clarifying_question = build_missing_required_question(state, evidence_text)
    if clarifying_question is not None:
        remember_message(conversation_history, "user", user_message)
        remember_message(conversation_history, "assistant", clarifying_question)
        print_assistant_response(clarifying_question)
        return state, 0

    assistant_reply = json.dumps(state, indent=2, ensure_ascii=False)
    remember_message(conversation_history, "user", user_message)
    remember_message(conversation_history, "assistant", assistant_reply)
    print_assistant_response(assistant_reply)
    return state, 0


def build_user_prompt(
    user_message: str,
    previous_state: dict[str, Any] | None,
    conversation_history: list[dict[str, str]],
) -> str:
    sections = [
        f"Current date: {date.today().isoformat()}",
        "Use the current date above when resolving dates without a year.",
        "Use the full conversation context below, including all earlier user messages and assistant replies.",
        "Do not ask again for destination, dates, guests, or filter preferences if they were already provided earlier.",
        "If the current user message is a short confirmation like 'yes', apply it to the previous assistant question and the original hotel request.",
        "Never default guests to 2. If guests are not explicitly provided in the conversation, set guests to null or ask how many guests will stay.",
        "If there are contradictory requests, ask about that conflict before asking for missing guests.",
        "When returning JSON, return only a strict JSON object. Do not include intro text, Markdown fences, comments, or explanations.",
        "Inside filters, include only keys from the configured schema. Do not invent aliases like soundproofing ratings.",
        "Do not infer filters from vague preferences. For example, cozy does not imply heating, and hotel room does not imply private_bathroom.",
        "For removed boolean filters, omit the filter key from filters instead of setting it to false.",
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
        "filters": dict(previous_filters),
    }

    filters = payload.get("filters")
    if not isinstance(filters, dict):
        return sanitized

    for key, value in filters.items():
        if key not in allowed_filters:
            continue
        if value is False and is_boolean_filter(filter_schema, key):
            sanitized["filters"].pop(key, None)
            continue
        if value is True and not has_filter_evidence(key, evidence_text):
            continue
        sanitized["filters"][key] = value

    return sanitized


def is_boolean_filter(filter_schema: dict[str, Any], key: str) -> bool:
    return filter_schema.get(key, {}).get("type") == "boolean"


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

    if re.search(r"\bself[-\s]?catering\b|\bkitchenette\b|\bkitchen facilities\b", evidence_text):
        filters["kitchen"] = True

    if re.search(r"\bfull board\b", evidence_text):
        filters["all_meals"] = True

    if re.search(r"\bbreakfast included\b|\bwith breakfast\b", evidence_text):
        filters["breakfast"] = True

    apply_price_rules(payload, evidence_text)


def apply_explicit_change_rules(payload: dict[str, Any], current_message: str) -> None:
    filters = payload.setdefault("filters", {})

    apply_replace_rules(filters, current_message)

    if re.search(r"\b(add|with|need|include)\s+parking\b", current_message):
        filters["parking"] = True

    if re.search(r"\b(remove|without|no|exclude)\s+(the\s+)?(swimming\s+)?pool\b", current_message):
        remove_boolean_filters(filters, BOOLEAN_REMOVE_ALIASES["pool"])

    if re.search(r"\b(remove|without|no|exclude)\s+breakfast\b", current_message):
        remove_boolean_filters(filters, BOOLEAN_REMOVE_ALIASES["breakfast"])

    if re.search(r"\b(remove|without|no|exclude)\s+parking\b", current_message):
        remove_boolean_filters(filters, BOOLEAN_REMOVE_ALIASES["parking"])

    remove_boolean_filters_by_message(filters, current_message)


def apply_replace_rules(filters: dict[str, Any], current_message: str) -> None:
    if re.search(r"\breplace\s+full board\s+with\s+breakfast\b", current_message):
        remove_boolean_filters(filters, BOOLEAN_REMOVE_ALIASES["full board"])
        filters["breakfast"] = True
        return

    if re.search(r"\breplace\s+all meals\s+with\s+breakfast\b", current_message):
        remove_boolean_filters(filters, BOOLEAN_REMOVE_ALIASES["all meals"])
        filters["breakfast"] = True
        return

    if re.search(r"\breplace\s+breakfast\s+with\s+(full board|all meals)\b", current_message):
        remove_boolean_filters(filters, BOOLEAN_REMOVE_ALIASES["breakfast"])
        filters["all_meals"] = True
        return


def apply_price_rules(payload: dict[str, Any], evidence_text: str) -> None:
    filters = payload.setdefault("filters", {})

    price_range = extract_price_range(evidence_text)
    if price_range is not None:
        minimum, maximum = price_range
        filters["total_price_min"] = minimum
        filters["total_price_max"] = maximum
        return

    max_price = extract_price_bound(evidence_text, bound="max")
    if max_price is not None:
        filters["total_price_max"] = max_price

    min_price = extract_price_bound(evidence_text, bound="min")
    if min_price is not None:
        filters["total_price_min"] = min_price


def extract_price_range(evidence_text: str) -> tuple[int, int] | None:
    patterns = (
        r"\bbetween\s+\$?\s*(\d{1,6})\s*(?:and|to|-|–)\s*\$?\s*(\d{1,6})\b",
        r"\b(?:price|prices|budget|cost|total price|room prices?)\D{0,40}\$?\s*(\d{1,6})\s*(?:and|to|-|–)\s*\$?\s*(\d{1,6})\b",
        r"\$\s*(\d{1,6})\s*(?:and|to|-|–)\s*\$\s*(\d{1,6})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, evidence_text)
        if match is None:
            continue
        first, second = sorted((int(match.group(1)), int(match.group(2))))
        return first, second
    return None


def extract_price_bound(evidence_text: str, bound: str) -> int | None:
    if bound == "max":
        patterns = (
            r"\b(?:under|below|less than|up to|max(?:imum)?|no more than)\s+\$?\s*(\d{1,6})\b",
            r"\b(?:budget|price|cost|total price)\D{0,20}(?:under|below|less than|up to|max(?:imum)?|no more than)\s+\$?\s*(\d{1,6})\b",
        )
    else:
        patterns = (
            r"\b(?:over|above|more than|at least|min(?:imum)?)\s+\$?\s*(\d{1,6})\b",
            r"\b(?:budget|price|cost|total price)\D{0,20}(?:over|above|more than|at least|min(?:imum)?)\s+\$?\s*(\d{1,6})\b",
        )

    for pattern in patterns:
        match = re.search(pattern, evidence_text)
        if match is not None:
            return int(match.group(1))
    return None


def remove_boolean_filters(filters: dict[str, Any], filter_names: tuple[str, ...]) -> None:
    for filter_name in filter_names:
        if isinstance(filters.get(filter_name), bool):
            filters.pop(filter_name, None)


def remove_boolean_filters_by_message(filters: dict[str, Any], current_message: str) -> None:
    for alias, filter_names in BOOLEAN_REMOVE_ALIASES.items():
        if re.search(rf"\b{REMOVE_WORDS_PATTERN}\s+(?:the\s+)?{re.escape(alias)}\b", current_message):
            remove_boolean_filters(filters, filter_names)

    for filter_name, value in list(filters.items()):
        if not isinstance(value, bool):
            continue

        readable_name = filter_name.replace("_", " ")
        if re.search(rf"\b{REMOVE_WORDS_PATTERN}\s+(?:the\s+)?{re.escape(readable_name)}\b", current_message):
            filters.pop(filter_name, None)
            continue

        if re.search(rf"\b{REMOVE_WORDS_PATTERN}\s+(?:the\s+)?{re.escape(filter_name)}\b", current_message):
            filters.pop(filter_name, None)


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
    if extract_explicit_date_range(evidence_text) is not None:
        return
    if has_explicit_year(evidence_text):
        return
    if extract_explicit_single_date(evidence_text) is not None:
        payload["check_out_date"] = None
        return
    if find_partial_date_range(evidence_text) is not None:
        payload["check_in_date"] = None
        payload["check_out_date"] = None


def apply_explicit_date_rules(payload: dict[str, Any], evidence_text: str) -> None:
    date_range = extract_explicit_date_range(evidence_text)
    if date_range is not None:
        check_in, check_out = date_range
        payload["check_in_date"] = check_in
        payload["check_out_date"] = check_out
        return

    single_date = extract_explicit_single_date(evidence_text)
    if single_date is not None:
        payload["check_in_date"] = single_date
        payload["check_out_date"] = None


def apply_nights_to_missing_checkout(payload: dict[str, Any], evidence_text: str) -> None:
    if payload.get("check_out_date") is not None:
        return

    check_in_raw = payload.get("check_in_date")
    if not isinstance(check_in_raw, str):
        return

    requested_nights = extract_requested_nights(evidence_text)
    if requested_nights is None:
        return

    try:
        check_in = datetime.strptime(check_in_raw, "%Y-%m-%d").date()
    except ValueError:
        return

    payload["check_out_date"] = (check_in + timedelta(days=requested_nights)).isoformat()


def extract_explicit_date_range(evidence_text: str) -> tuple[str, str] | None:
    month_names = "|".join(MONTH_NUMBERS)
    current_year = date.today().year
    ordinal_suffix = r"(?:st|nd|rd|th)?"

    iso_range = re.search(
        r"\b(20\d{2})-(\d{2})-(\d{2})\s*(?:-|–|to)\s*(20\d{2})-(\d{2})-?(\d{2})\b",
        evidence_text,
        flags=re.IGNORECASE,
    )
    if iso_range is not None:
        start_year, start_month, start_day, end_year, end_month, end_day = iso_range.groups()
        return (
            format_date(int(start_year), int(start_month), int(start_day)),
            format_date(int(end_year), int(end_month), int(end_day)),
        )

    full_range = re.search(
        rf"\b(?:from\s+)?({month_names})\s+(\d{{1,2}}){ordinal_suffix},?\s+(20\d{{2}})\s+"
        rf"(?:to|until|through|-|–)\s+({month_names})\s+(\d{{1,2}}){ordinal_suffix},?\s+(20\d{{2}})\b",
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
        rf"\b(?:from\s+)?({month_names})\s+(\d{{1,2}}){ordinal_suffix}\s*(?:-|–|to)\s*(?:{month_names}\s+)?(\d{{1,2}}){ordinal_suffix},?\s+(20\d{{2}})\b",
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

    same_month_range_without_year = re.search(
        rf"\b(?:from\s+)?(\d{{1,2}}){ordinal_suffix}\s*(?:-|–|to)\s*(\d{{1,2}}){ordinal_suffix}\s+({month_names})\b",
        evidence_text,
        flags=re.IGNORECASE,
    )
    if same_month_range_without_year is not None:
        start_day, end_day, month = same_month_range_without_year.groups()
        month_number = MONTH_NUMBERS[month.lower()]
        return (
            format_date(current_year, month_number, int(start_day)),
            format_date(current_year, month_number, int(end_day)),
        )

    month_first_range_without_year = re.search(
        rf"\b(?:from\s+)?({month_names})\s+(\d{{1,2}}){ordinal_suffix}\s*(?:-|–|to)\s*(?:{month_names}\s+)?(\d{{1,2}}){ordinal_suffix}\b",
        evidence_text,
        flags=re.IGNORECASE,
    )
    if month_first_range_without_year is not None:
        month, start_day, end_day = month_first_range_without_year.groups()
        month_number = MONTH_NUMBERS[month.lower()]
        return (
            format_date(current_year, month_number, int(start_day)),
            format_date(current_year, month_number, int(end_day)),
        )

    return None


def extract_explicit_single_date(evidence_text: str, today: date | None = None) -> str | None:
    month_names = "|".join(MONTH_NUMBERS)
    current_date = today or date.today()
    ordinal_suffix = r"(?:st|nd|rd|th)?"

    month_day = re.search(
        rf"\b(?:on|for)?\s*({month_names})\s+(\d{{1,2}}){ordinal_suffix}(?:,?\s+(20\d{{2}}))?\b",
        evidence_text,
        flags=re.IGNORECASE,
    )
    if month_day is not None:
        month, day, year = month_day.groups()
        return format_date(int(year) if year else current_date.year, MONTH_NUMBERS[month.lower()], int(day))

    day_month = re.search(
        rf"\b(?:on|for)?\s*(\d{{1,2}}){ordinal_suffix}\s+({month_names})(?:,?\s+(20\d{{2}}))?\b",
        evidence_text,
        flags=re.IGNORECASE,
    )
    if day_month is not None:
        day, month, year = day_month.groups()
        return format_date(int(year) if year else current_date.year, MONTH_NUMBERS[month.lower()], int(day))

    return None


def has_explicit_year(evidence_text: str) -> bool:
    return re.search(r"\b20\d{2}\b", evidence_text) is not None


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

    apply_explicit_filter_rules(updated_state, user_message.lower())
    apply_conflict_resolution_rules(updated_state, user_message.lower(), conversation_history)
    apply_explicit_date_rules(updated_state, evidence_text)
    clear_guessed_dates(updated_state, evidence_text)
    apply_nights_to_missing_checkout(updated_state, evidence_text)
    apply_explicit_guest_rule(updated_state, evidence_text, user_message, conversation_history, previous_state)
    apply_explicit_change_rules(updated_state, user_message.lower())

    after = json.dumps(updated_state, sort_keys=True, ensure_ascii=False)
    if before == after:
        return None
    return updated_state


def apply_conflict_resolution_rules(
    payload: dict[str, Any],
    current_message: str,
    conversation_history: list[dict[str, str]],
) -> None:
    if not last_assistant_asked_conflict(conversation_history):
        return

    filters = payload.setdefault("filters", {})
    if re.search(r"\b(no meals?|without (any )?meals?|room only)\b", current_message):
        remove_boolean_filters(filters, tuple(MEAL_FILTER_LABELS))
        return

    if re.search(r"\b(full board|all meals)\b", current_message):
        filters["all_meals"] = True
        return

    if re.search(r"\bbreakfast\b", current_message):
        filters["breakfast"] = True
        filters.pop("all_meals", None)
        filters.pop("all_inclusive", None)


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


def apply_nights_conflict_reply_to_previous_state(
    previous_state: dict[str, Any] | None,
    user_message: str,
    conversation_history: list[dict[str, str]],
) -> dict[str, Any] | None:
    if previous_state is None or not last_assistant_asked_nights_conflict(conversation_history):
        return None

    normalized_message = user_message.lower().strip()
    if re.search(r"\b(these dates|the dates|dates)\b", normalized_message):
        return copy.deepcopy(previous_state)

    if re.search(r"\b(nights?|use nights?|three nights?|3 nights?)\b", normalized_message):
        requested_nights = extract_requested_nights(build_evidence_text(conversation_history, user_message))
        check_in_raw = previous_state.get("check_in_date")
        if requested_nights is None or not isinstance(check_in_raw, str):
            return None

        try:
            check_in = datetime.strptime(check_in_raw, "%Y-%m-%d").date()
        except ValueError:
            return None

        updated_state = copy.deepcopy(previous_state)
        updated_state["check_out_date"] = (check_in + timedelta(days=requested_nights)).isoformat()
        return updated_state

    return None


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


def last_assistant_asked_nights_conflict(conversation_history: list[dict[str, str]]) -> bool:
    for message in reversed(conversation_history):
        if message["role"] != "assistant":
            continue
        content = message["content"].lower()
        return (
            "you asked for" in content
            and "nights" in content
            and "which should i use" in content
        )
    return False


def nights_conflict_was_answered_with_dates(conversation_history: list[dict[str, str]]) -> bool:
    for index, message in enumerate(conversation_history):
        if message["role"] != "assistant":
            continue
        content = message["content"].lower()
        if not ("you asked for" in content and "nights" in content and "which should i use" in content):
            continue
        return any(
            later_message["role"] == "user"
            and re.search(r"\b(these dates|the dates|dates)\b", later_message["content"].lower())
            for later_message in conversation_history[index + 1 :]
        )
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
        if re.match(r"^\d{1,2}\b", standalone_text):
            return int(re.match(r"^\d{1,2}\b", standalone_text).group(0))
        if standalone_text in NUMBER_WORDS:
            return NUMBER_WORDS[standalone_text]

    if re.search(r"\b(solo|alone|single traveler|single traveller|traveling solo|travelling solo)\b", evidence_text):
        return 1

    if re.search(r"\bcouple\b", evidence_text):
        return 2

    digit_patterns = (
        r"\b(\d{1,2})\s+(?:guests?|people|persons?|adults?|travellers?|travelers?)\b",
        r"\b(?:for|with|party of)\s+(\d{1,2})(?!\s+nights?)\b",
    )
    for pattern in digit_patterns:
        match = re.search(pattern, evidence_text)
        if match is not None:
            return int(match.group(1))

    word_group = "|".join(NUMBER_WORDS)
    word_patterns = (
        rf"\b({word_group})\s+(?:guests?|people|persons?|adults?|travellers?|travelers?)\b",
        rf"\b(?:for|with|party of)\s+({word_group})(?!\s+nights?)\b",
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

    mapped_conflict = detect_mapped_filter_conflict(filters)
    if mapped_conflict is not None:
        return mapped_conflict

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


def detect_mapped_filter_conflict(filters: dict[str, Any]) -> str | None:
    for conflict_group in MUTUALLY_EXCLUSIVE_FILTER_GROUPS:
        left_filters = conflict_group["left_filters"]
        right_filters = conflict_group["right_filters"]

        left_matches = [filter_name for filter_name in left_filters if filters.get(filter_name) is True]
        right_matches = [filter_name for filter_name in right_filters if filters.get(filter_name) is True]
        if not left_matches or not right_matches:
            continue

        return (
            f"You asked for {conflict_group['left_label']} but also "
            f"{conflict_group['right_label']}. Which is more important?"
        )

    return None


def detect_meal_conflict(filters: dict[str, Any], evidence_text: str) -> str | None:
    for conflict_rule in TEXT_FILTER_CONFLICTS:
        if re.search(str(conflict_rule["negative_pattern"]), evidence_text) is None:
            continue

        positive_filters = conflict_rule["positive_filters"]
        requested_labels = []
        for key, label in positive_filters.items():
            if filters.get(key) is True or re.search(rf"\b{re.escape(label)}\b", evidence_text):
                requested_labels.append(label)

        if not requested_labels:
            continue

        positive_text = ", ".join(dict.fromkeys(requested_labels))
        return f"You asked for {positive_text} but also {conflict_rule['negative_label']}. Which is more important?"

    return None


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


def validate_requested_nights(
    payload: dict[str, Any],
    evidence_text: str,
    conversation_history: list[dict[str, str]] | None = None,
    current_message: str = "",
) -> str | None:
    if conversation_history is not None and last_assistant_asked_nights_conflict(conversation_history):
        if user_chose_dates_for_nights_conflict(current_message):
            return None

    if conversation_history is not None and nights_conflict_was_answered_with_dates(conversation_history):
        return None

    requested_nights = extract_requested_nights(evidence_text)
    if requested_nights is None:
        return None

    check_in_raw = payload.get("check_in_date")
    check_out_raw = payload.get("check_out_date")
    if not isinstance(check_in_raw, str) or not isinstance(check_out_raw, str):
        return None

    try:
        check_in = datetime.strptime(check_in_raw, "%Y-%m-%d").date()
        check_out = datetime.strptime(check_out_raw, "%Y-%m-%d").date()
    except ValueError:
        return None

    actual_nights = (check_out - check_in).days
    if actual_nights == requested_nights:
        return None

    return (
        f"You asked for {requested_nights} nights, but {check_in_raw} to {check_out_raw} "
        f"is {actual_nights} nights. Which should I use: {requested_nights} nights or these dates?"
    )


def user_chose_dates_for_nights_conflict(user_message: str) -> bool:
    return re.search(r"\b(these dates|the dates|dates|date range|use dates)\b", user_message.lower()) is not None


def extract_requested_nights(evidence_text: str) -> int | None:
    digit_match = re.search(r"\b(\d{1,2})\s+nights?\b", evidence_text)
    if digit_match is not None:
        return int(digit_match.group(1))

    word_group = "|".join(NIGHT_WORDS)
    word_match = re.search(rf"\b({word_group})\s+nights?\b", evidence_text)
    if word_match is None:
        return None
    return NIGHT_WORDS[word_match.group(1)]


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
