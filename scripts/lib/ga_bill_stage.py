"""Where a GA bill is: its stage, derived from legis.ga.gov's status history.

One definition, computed at build time and stored on each bill as `stage`, so the bills
page, the legislator pages and the MCP index all say the same thing. Codes and their
meanings: docs/ga-soap-data-dictionary.md, 2.4.

    stage = {"kind": ..., "label": ..., "path": "full" | "short",
             "steps": [[state, headline, detail], ...]}

`path` "full" is six steps, in this order (the page names them from the bill's chamber):
origin committee, origin floor, other committee, other floor, final version, Governor.
"short" is two: filed, adopted, for a simple resolution one chamber adopts alone.
`state` is done | current | stopped | ahead. `kind` drives the page's filters:

    signed  vetoed  governor  agreement  committee  died-committee
    floor   died-floor  lost  adopted

A bill whose session is over and which never reached the Governor is dead: the step it
was on becomes `stopped` ("Died in Senate Finance"). See session_over().
"""
from datetime import datetime, timedelta

CHAMBER_WORD = {"lower": "House", "upper": "Senate"}
OTHER = {"lower": "upper", "upper": "lower"}

REFERRED = {"HFR", "HSR", "SRAR"}
REPORTED = {"HCFR", "SCFR"}
PASSED = {"HPA", "SPA", "SRECP", "HRA", "SRA"}
LOST = {"HTRL", "S3RLT"}
RECOMMITTED = {"HRECM", "SR"}
TABLED, UNTABLED = {"STAB"}, {"STT"}
AGREED = {"HASAS", "SAHAS", "HCA", "SCRA"}
SENT = {"HSG", "SSG"}

#: A session with no legislative action on ANY of its bills for this long has adjourned.
#: Georgia sits continuously from January to sine die; a special session is days long.
QUIET_DAYS = 45
#: Codes that come after adjournment and so do not count as legislative action.
_AFTER_ADJOURNMENT = {"HDSG", "SDSG", "EFF", "Signed Gov"}


def _chamber_of(code):
    return {"H": "lower", "S": "upper"}.get((code or "")[:1])


def _day(iso):
    """'2026-02-04T…' -> 'Feb 4, 2026'."""
    try:
        d = datetime.strptime((iso or "")[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return "%s %d, %d" % (d.strftime("%b"), d.day, d.year)


def session_over(bills, now, biennium_end_year=None):
    """True when the session these bills belong to has adjourned for good.

    No legislative action on any bill for QUIET_DAYS. A regular session spans the
    biennium: bills left in 2025 carry over to 2026, so it is over only when its last
    action falls in `biennium_end_year` (the second year). `now` is a datetime."""
    last = ""
    for b in bills:
        for row in b.get("statusHistory") or []:
            if row[1] not in _AFTER_ADJOURNMENT and row[0] > last:
                last = row[0]
    if not last:
        return False
    try:
        last_dt = datetime.strptime(last[:10], "%Y-%m-%d")
    except ValueError:
        return False
    if biennium_end_year and last_dt.year < biennium_end_year:
        return False
    return now.replace(tzinfo=None) - last_dt > timedelta(days=QUIET_DAYS)


def _walk(history):
    """Per chamber: {referred, reported, passed, lost, tabled} dates (or None), in order."""
    st = {c: dict.fromkeys(("referred", "reported", "passed", "lost", "tabled")) for c in OTHER}
    agreed = sent = None
    for date, code, *_ in history:
        c = _chamber_of(code)
        if code in SENT:
            sent = sent or date
        if code in AGREED:
            agreed = date
        if c is None:
            continue
        s = st[c]
        if code in REFERRED and not s["referred"]:
            s["referred"] = date
        elif code in REPORTED:
            s["reported"] = date
        elif code in RECOMMITTED and not s["passed"]:
            s["reported"] = None                     # back in committee
        elif code in PASSED:
            s["passed"], s["lost"], s["tabled"] = date, None, None
        elif code in LOST and not s["passed"]:
            s["lost"] = date
        elif code in TABLED and not s["passed"]:
            s["tabled"] = date
        elif code in UNTABLED:
            s["tabled"] = None
    return st, agreed, sent


def _floor_tally(bill, chamber, want, on=None):
    """'167–5' from the bill's passage vote in `chamber` with result `want`: the latest
    one on or before `on` (the day the status history records the pass or loss), so a
    later concurrence or conference-report vote does not stand in for the passage."""
    votes = [v for v in bill.get("passageVotes") or []
             if v.get("chamber") == chamber and v.get("result") == want]
    if on:
        votes = [v for v in votes if (v.get("date") or "") <= on[:10]] or votes
    if not votes:
        return ""
    v = max(votes, key=lambda v: (v.get("date") or "", v.get("time") or ""))
    return "%s–%s" % (v.get("yea"), v.get("nay"))


def _committee(bill, chamber):
    for c in bill.get("committees") or []:
        if c.get("chamber") == chamber and c.get("name"):
            return c["name"]
    return None


def bill_stage(bill, over):
    """The `stage` dict for one ga-bills.json bill. `over`: its session has adjourned."""
    history = bill.get("statusHistory") or []
    origin = bill.get("chamber") if bill.get("chamber") in OTHER else "lower"
    other = OTHER[origin]
    st, agreed, sent = _walk(history)
    ga = bill.get("governorAction") or {}

    simple = (bill.get("billType") == "resolution"
              and bill.get("legislationType") in ("PRIV", "NP", None)
              and not ga and not any(_chamber_of(r[1]) == other for r in history))
    if simple:
        o = st[origin]
        word = CHAMBER_WORD[origin]
        if o["passed"]:
            return {"kind": "adopted", "label": "Adopted by the %s" % word, "path": "short",
                    "steps": [["done", "Filed", ""], ["done", "Adopted", _day(o["passed"])]]}
        end = "stopped" if over else "current"
        return {"kind": "died-committee" if over else "committee",
                "label": ("Not adopted" if over else "Awaiting %s adoption" % word), "path": "short",
                "steps": [["done", "Filed", ""], [end, "Not adopted" if over else "Pending", ""]]}

    steps, at = [], None          # `at`: index of the first step not done

    def chamber_steps(c):
        s, word = st[c], CHAMBER_WORD[c]
        name = _committee(bill, c) or "Committee"
        if s["reported"] or s["passed"]:
            detail = ("Reported %s" % _day(s["reported"])) if s["reported"] else ""
            steps.append(["done", name, detail])
        else:
            detail = ("Referred %s" % _day(s["referred"])) if s["referred"] else ""
            steps.append(["current", name, detail])
        if s["passed"]:
            tally = _floor_tally(bill, c, "pass", s["passed"])
            steps.append(["done", ("Passed %s" % tally) if tally else "Passed", _day(s["passed"])])
        elif s["lost"]:
            tally = _floor_tally(bill, c, "fail", s["lost"])
            steps.append(["stopped", ("Lost %s" % tally) if tally else "Lost", _day(s["lost"])])
        elif s["tabled"]:
            steps.append(["stopped", "Tabled", _day(s["tabled"])])
        elif s["reported"]:
            steps.append(["current", "Awaiting %s vote" % word, ""])
        else:
            steps.append(["ahead", "—", ""])

    chamber_steps(origin)
    if st[origin]["passed"]:
        chamber_steps(other)
    else:
        steps += [["ahead", "—", ""], ["ahead", "—", ""]]

    both = st[origin]["passed"] and st[other]["passed"]
    if sent or ga:
        steps.append(["done", "Agreed" if agreed else "Same version passed", _day(agreed) if agreed else ""])
    elif both:
        steps.append(["current", "Chambers agreeing", ""])
    else:
        steps.append(["ahead", "—", ""])

    status = ga.get("status")
    if status == "Signed":
        act = ga.get("actNumber")
        steps.append(["done", "Signed", ("%s · Act %s" % (_day(ga.get("decisionDate")), act)) if act
                      else _day(ga.get("decisionDate"))])
    elif status == "Vetoed":
        vn = ga.get("vetoNumber")
        steps.append(["stopped", "Vetoed", ("%s · Veto %s" % (_day(ga.get("decisionDate")), vn)) if vn
                      else _day(ga.get("decisionDate"))])
    elif status == "Sent to Governor" or sent:
        steps.append(["current", "On the Governor's desk", "Sent %s" % _day(ga.get("sentDate") or sent)])
    else:
        steps.append(["ahead", "—", ""])

    # A step is ahead once an earlier one has not been passed: a bill sits in one place.
    for i, s in enumerate(steps):
        if s[0] in ("current", "stopped"):
            at = i
            for later in steps[i + 1:]:
                later[0], later[1], later[2] = "ahead", "—", ""
            break
    if at is not None and over and steps[at][0] == "current" and status != "Sent to Governor":
        steps[at][0] = "stopped"
        if steps[at][1].startswith("Awaiting"):
            steps[at][1] = "No vote"
        if at in (0, 2) and steps[at][2].startswith("Referred"):
            steps[at][2] += " · never reported"

    kind, label = _label(bill, steps, at, origin, other, status)
    return {"kind": kind, "label": label, "path": "full", "steps": steps}


def _label(bill, steps, at, origin, other, status):
    if status == "Signed":
        act = (bill.get("governorAction") or {}).get("actNumber")
        return "signed", ("Signed · Act %s" % act) if act else "Signed"
    if status == "Vetoed":
        return "vetoed", "Vetoed"
    if at is None:
        return "agreement", "Passed both chambers"
    state, headline = steps[at][0], steps[at][1]
    chamber = origin if at < 2 else other
    word = CHAMBER_WORD[chamber]
    lead = ("Passed %s · " % CHAMBER_WORD[origin]) if at >= 2 else ""
    if at in (0, 2):
        name = _committee(bill, chamber)
        where = ("%s %s" % (word, name)) if name else ("%s committee" % word)
        if state == "stopped":
            return "died-committee", lead + "Died in " + where
        return "committee", lead + "In " + where
    if at in (1, 3):
        if headline.startswith("Lost"):
            return "lost", lead + "Lost on the %s floor" % word
        if state == "stopped":
            return "died-floor", lead + ("Tabled in the %s" % word if headline == "Tabled"
                                         else "Died awaiting a %s vote" % word)
        return "floor", lead + "Awaiting %s vote" % word
    if at == 4:
        if state == "stopped":
            return "died-floor", "Passed both · no final version"
        return "agreement", "Passed both · chambers agreeing"
    return "governor", "Sent to Governor"


def sine_die(calendar_days):
    """The last scheduled legislative day ('YYYY-MM-DD') of a session's calendar, or None.
    For a regular session that is day 40 of the biennium's second year: first-year bills
    carry over, so only the last day of the whole calendar ends them."""
    dates = [d for _n, d in calendar_days or [] if d]
    return max(dates) if dates else None


#: Ga. Const. Art. III, Sec. V, Para. XIII(a): a bill becomes law unless vetoed within
#: six days of reaching the Governor, or within 40 days of adjournment sine die when the
#: General Assembly adjourns before those six days run out. Para. XIII(b) bars sending
#: bills during a session except on the Governor's request or a two-thirds order, so
#: nearly every bill gets the 40 days. Checked against 2025-26: all 743 decisions fell on
#: or before the deadline this computes, and the busiest days were the deadlines
#: themselves (May 14, 2025 and May 12, 2026).
GOVERNOR_DAYS, GOVERNOR_DAYS_AFTER_ADJOURNMENT = 6, 40


def governor_deadline(sent, calendar_days):
    """'YYYY-MM-DD' the Governor must act by on a bill sent on `sent`, or None.

    The adjournment that counts is the last legislative day of the year the bill was
    sent in (a regular session adjourns each year; a special session once). Sent after
    it, or with it falling inside the six days: 40 days from it. Otherwise six days."""
    if not sent:
        return None
    sent = sent[:10]
    try:
        sent_d = datetime.strptime(sent, "%Y-%m-%d")
    except ValueError:
        return None
    year_days = [d for _n, d in calendar_days or [] if d[:4] == sent[:4]]
    six = sent_d + timedelta(days=GOVERNOR_DAYS)
    if year_days:
        adjourned = datetime.strptime(max(year_days), "%Y-%m-%d")
        if adjourned < six:
            return (adjourned + timedelta(days=GOVERNOR_DAYS_AFTER_ADJOURNMENT)).strftime("%Y-%m-%d")
    return six.strftime("%Y-%m-%d")


def _apply_governor_deadline(bill, now, calendar_days):
    """On a bill waiting on the Governor: name the deadline, and once it has passed with
    no signature or veto on record, the bill became law without the Governor's signature
    (Para. XIII(a)); Georgia has no pocket veto."""
    stage = bill.get("stage") or {}
    if stage.get("kind") != "governor":
        return
    ga = bill.get("governorAction") or {}
    sent = ga.get("sentDate") or next((r[0] for r in bill.get("statusHistory") or [] if r[1] in SENT), None)
    deadline = governor_deadline(sent, calendar_days)
    if not deadline:
        return
    stage["governorDeadline"] = deadline
    step = stage["steps"][-1]
    if now.date().isoformat() > deadline:
        step[:] = ["done", "Law without signature", "Not signed or vetoed by %s" % _day(deadline)]
        stage["kind"], stage["label"] = "signed", "Became law without the Governor's signature"
    else:
        step[2] = "Sent %s · must act by %s" % (_day(sent), _day(deadline))
        stage["label"] = "Sent to Governor · must act by %s" % _day(deadline)


def apply_stages(bills, now, biennium_end_year=None, calendar=None):
    """Set `stage` on every bill, deciding per session whether it has adjourned.
    Returns {session: over}.

    `calendar` is metadata.legislativeCalendar ({session: {"lower": [[n, date]], ...}}):
    a session is over once `now` is past its last scheduled day, and a dead bill's
    stopped step names that day. A session with no calendar falls back to the
    45-quiet-days rule (session_over)."""
    by_session = {}
    for b in bills:
        by_session.setdefault(b.get("session"), []).append(b)
    over = {}
    for session, group in by_session.items():
        days = ((calendar or {}).get(session) or {}).get("lower") or []
        last = sine_die(days)
        if last:
            over[session] = now.date().isoformat() > last
        else:
            regular = not str(session or "").endswith("_ss")
            over[session] = session_over(group, now, biennium_end_year if regular else None)
        for b in group:
            b["stage"] = bill_stage(b, over[session])
            _apply_governor_deadline(b, now, days)
            if over[session] and last:
                for step in b["stage"]["steps"]:
                    if step[0] == "stopped" and step[2].endswith("never reported"):
                        step[2] += " · session ended %s" % _day(last)
    return over
