"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values."""

import json
import math
import os
import time

import httpx

from .questions import NEXT_ACTION, TARGET, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=25)


def post_json(url, key, body):
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError:
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in {429, 529, 503} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue
        if response.is_error:
            detail = ""
            try:
                detail = response.json().get("error", {}).get("message") or response.text[:200]
            except Exception:
                detail = response.text[:200]
            raise RuntimeError(
                f"Model provider returned HTTP {response.status_code}"
                + (f": {detail}" if detail else "")
                + "; no action executed."
            )
        return response.json()
    raise RuntimeError("Model unavailable")


def validate_choice(answer, ids):
    allowed = set(ids)
    label_to_id = {}
    if isinstance(ids, dict):
        for key, meta in ids.items():
            if isinstance(meta, str):
                label_to_id[meta] = key
            elif isinstance(meta, dict):
                if meta.get("label"):
                    label_to_id[meta["label"]] = key
                if meta.get("element"):
                    label_to_id[meta["element"]] = key
    try:
        answer = dict(answer)
        choice = answer.get("choice")
        if choice not in allowed and choice in label_to_id:
            answer["choice"] = label_to_id[choice]
        probabilities = answer.get("probabilities")
        if isinstance(probabilities, dict) and set(probabilities) != allowed:
            remapped = {}
            for key, value in probabilities.items():
                remapped[label_to_id.get(key, key)] = value
            answer["probabilities"] = remapped
            probabilities = remapped
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in allowed
            and set(probabilities) == allowed
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def decisions_config():
    """TypeSafe native API, or OpenRouter Decisions with the same request shape."""
    openrouter = os.environ.get("OPENROUTER_API_KEY")
    typesafe = os.environ.get("TYPESAFE_API_KEY")
    endpoint = os.environ.get("TYPESAFE_BASE_URL")
    if endpoint:
        key = typesafe or openrouter
        if not key:
            raise ValueError("TYPESAFE_BASE_URL set but no TYPESAFE_API_KEY or OPENROUTER_API_KEY")
        default_model = "~typesafe/jev-latest" if "openrouter.ai" in endpoint else "jev-latest"
        return endpoint, key, os.environ.get("TYPESAFE_MODEL", default_model)
    if typesafe and not (openrouter and typesafe == openrouter):
        # Prefer native TypeSafe when a distinct key is present.
        return (
            "https://api.typesafe.ai/v1/systemone",
            typesafe,
            os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        )
    if openrouter or typesafe:
        return (
            "https://openrouter.ai/api/alpha/decisions",
            openrouter or typesafe,
            os.environ.get("TYPESAFE_MODEL", "~typesafe/jev-latest"),
        )
    raise ValueError("Set OPENROUTER_API_KEY or TYPESAFE_API_KEY for decisions.")


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT", "pointer": "AIM"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        if kind == "pointer":
            # Canvas aim/boost: one AIM operation with direction/boost targets (no DOM node).
            group = targets.setdefault("AIM", {})
            target = action["id"]
            group[target] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def choose(state, goal, history):
    elements, targets, controls = action_space(state["actions"])
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
        "AIM": "Steer on a canvas game by aiming the pointer in a direction, or boost briefly.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    for operation, candidates in targets.items():
        if operation == "AIM":
            criteria = {index: a["label"] for index, a in candidates.items()}
        else:
            criteria = {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            }
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": criteria,
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    endpoint, api_key, model_name = decisions_config()
    body = {
        "model": model_name,
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text") if k in state},
            "game": state.get("game"),
            "elements": elements,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    last_error = None
    for attempt in range(3):
        try:
            result = post_json(endpoint, api_key, body)
            operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
            operation = operation_answer["choice"]
            target = None
            target_answer = None
            probabilities = {}
            if operation in targets:
                # Unused target heads cannot cause an action. Validate the head selected by the operation.
                head = targets[operation]
                criteria_for_validation = (
                    {k: v["label"] for k, v in head.items()} if operation == "AIM" else head
                )
                target_answer = validate_choice(
                    result["answers"].get(operation.lower() + "_target", {}),
                    criteria_for_validation,
                )
                target = target_answer["choice"]
                choice = head[target]["id"]
                probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in head.items()}
            else:
                choice = controls[operation]["id"] if operation in controls else operation
                probabilities[choice] = operation_answer["probabilities"][operation]
            return {
                "choice": choice,
                "operation": operation,
                "target": target,
                "confidence": operation_answer["confidence"],
                "probabilities": probabilities,
                "operation_probabilities": operation_answer["probabilities"],
                "target_probabilities": target_answer["probabilities"] if target_answer else {},
                "target_confidence": target_answer["confidence"] if target_answer else None,
                "raw_answers": result["answers"],
                "model": result["model"],
                "usage": result.get("usage", {}),
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "request": body,
            }
        except ValueError as error:
            last_error = error
            if attempt == 2:
                raise
            time.sleep(0.2 * (attempt + 1))
    raise last_error


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def field_text(context):
    key = os.environ.get("TEXT_MODEL_API_KEY")
    if not key:
        raise ValueError("TYPE_TEXT needs TEXT_MODEL_API_KEY; no text is hardcoded or guessed by the executor.")
    base = os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("TEXT_MODEL", "deepseek-chat")
    reasoning = {"thinking": {"type": "disabled"}} if "api.deepseek.com/" in base else {"reasoning": {"effort": "low"}}
    if os.environ.get("TEXT_MODEL_REASONING") == "none":
        reasoning = {"reasoning": {"enabled": False}}
    started = time.perf_counter()
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [
                {"role": "system", "content": TEXT_VALUE},
                {
                    "role": "user",
                    "content": json.dumps(context),
                },
            ],
        },
    )
    try:
        output = json.loads(result["choices"][0]["message"]["content"])
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
    }
