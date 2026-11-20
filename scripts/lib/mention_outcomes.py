"""The published shape of a topic mention's follow-through (what the minutes record).

generate_topic_mentions.py attaches `followThrough`, `outcomes`, `minutesUrl` and
`minutesDraft` to a mention when the place has a recorded-votes record for that
meeting, keeping only the keys that are set (the topic pages fetch those feeds whole).
The published dataset is read by people who did not write it, so here every key is
present and an unset one is null, and the three different "no outcome" cases stay
apart:

  followThrough null           we hold no recorded-votes record for the meeting
                               (no reader for the platform, minutes not posted or
                               not read yet). Says nothing about what happened.
  "no-results"                 minutes read, they record no actions we can read.
  "not-in-minutes"             minutes read, no recorded item names the topic.
  "recorded"                   `outcomes` lists the recorded items that do.

`result` is "passed" / "failed" only for adopted or failed wording; a step (held,
referred, recommended …) is null with its `resultClass`, and `resultText` is the
body's own wording. Vote counts only: who voted which way stays on the source.

Pure (no third-party imports) so the offline test job can import it.
"""

FOLLOW_THROUGH = ["recorded", "not-in-minutes", "no-results", None]
MOTION_KEYS = ["motion", "result", "resultClass", "resultText", "tally",
               "yes", "no", "abstain", "absent", "next", "textDisagrees"]
_COUNT_KEYS = ("yes", "no", "abstain", "absent")


def publish_motion(mo):
    out = {k: mo.get(k) for k in MOTION_KEYS}
    for k in _COUNT_KEYS:
        out[k] = out[k] or 0
    out["tally"] = list(out["tally"]) if out["tally"] else None
    out["textDisagrees"] = bool(out["textDisagrees"])
    return out


def publish_outcomes(m):
    """The four follow-through fields of one feed mention, every key present."""
    return {
        "followThrough": m.get("followThrough"),
        "outcomes": [{"reference": o.get("reference"), "outline": o.get("outline"),
                      "name": o.get("name"),
                      "motions": [publish_motion(mo) for mo in o.get("motions") or []]}
                     for o in m.get("outcomes") or []],
        "minutesUrl": m.get("minutesUrl"),
        "minutesDraft": m.get("minutesDraft") if m.get("followThrough") else None,
    }


def motion_text(mo):
    """'Adopted substitute 11-0' / 'Referred without objection' / ''."""
    label = mo.get("resultText") or (mo.get("result") or "").capitalize()
    t = mo.get("tally")
    if t:
        label = ("%s %d-%d" % (label, t[0], t[1])).strip()
    elif mo.get("yes") or mo.get("no"):
        label = ("%s %d-%d" % (label, mo.get("yes") or 0, mo.get("no") or 0)).strip()
    if mo.get("textDisagrees"):
        label += " (minutes' text disagrees with this tally)"
    return label


def outcome_summary(outcomes):
    """One CSV cell: each recorded item's reference, then its motions in order."""
    parts = []
    for o in outcomes or []:
        motions = [s for s in (motion_text(mo) for mo in o.get("motions") or []) if s]
        if not motions:
            continue
        ref = o.get("reference") or o.get("outline")
        parts.append(("%s: " % ref if ref else "") + ", then ".join(motions))
    return "; ".join(parts) or None


def outcome_schema():
    """JSON Schema properties for the four fields."""
    motion = {
        "type": "object",
        "properties": {
            "motion": {"type": ["string", "null"], "description": "the motion as recorded, where the portal names it"},
            "result": {"enum": ["passed", "failed", None],
                       "description": "passed/failed only for adopted or failed wording; null for a step"},
            "resultClass": {"type": ["string", "null"],
                            "description": "normalized result wording (adopted, adopted-substitute, held, referred, recommended, adversed, ...); null when the wording is not one we recognise"},
            "resultText": {"type": ["string", "null"], "description": "the body's own result wording"},
            "tally": {"type": ["array", "null"], "items": {"type": "integer"},
                      "description": "[yes, no] as printed by the minutes, when printed"},
            "yes": {"type": "integer"}, "no": {"type": "integer"},
            "abstain": {"type": "integer"}, "absent": {"type": "integer"},
            "next": {"type": ["string", "null"], "description": "where the item goes next (committee and date), when recorded"},
            "textDisagrees": {"type": "boolean",
                              "description": "the minutes' own narrative contradicts this recorded tally; read the minutes"},
        },
    }
    return {
        "followThrough": {"enum": FOLLOW_THROUGH,
                          "description": "recorded = outcomes lists recorded items naming this topic; not-in-minutes = minutes read, no recorded item names it; no-results = minutes read, no readable recorded actions; null = no recorded-votes record for this meeting (says nothing about what happened)"},
        "outcomes": {"type": "array", "description": "the same meeting's recorded agenda items whose caption carries this topic, joined on the portal's own meeting id",
                     "items": {"type": "object", "properties": {
                         "reference": {"type": ["string", "null"], "description": "the body's file number, where it has one"},
                         "outline": {"type": ["string", "null"], "description": "agenda outline number, where items are numbered rather than filed"},
                         "name": {"type": ["string", "null"], "description": "the agenda caption, truncated to about 300 characters"},
                         "motions": {"type": "array", "items": motion}}}},
        "minutesUrl": {"type": ["string", "null"], "description": "the minutes the outcomes were read from"},
        "minutesDraft": {"type": ["boolean", "null"], "description": "true when those minutes are marked draft (re-read until final)"},
    }
