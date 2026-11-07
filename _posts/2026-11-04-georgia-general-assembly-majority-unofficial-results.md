---
layout: post
title: What the Unofficial Results Mean for the Georgia General Assembly
subtitle: A seat-by-seat projection of the House and Senate, with every flipped seat marked
share-title: Georgia General Assembly Projection, 2026 Unofficial Results
share-description: "What Georgia's unofficial 2026 general election results would mean for the General Assembly: a seat-by-seat projection of the House and Senate, with every flipped seat marked, updated as counting continues."
tags: [elections, results, 2026 general election, General Assembly, data]
---

{%- assign proj = site.data.projected_majority_2026 -%}
{%- assign house = proj.chambers["House of Representatives"] -%}
{%- assign senate = proj.chambers["Senate"] -%}
If the unofficial results from the **November 3, 2026** general election hold, the 2027 Georgia General Assembly would look like this. Each seat below is filled by the leader in that district's race, or by the unopposed candidate. A seat outlined in black **flipped** from the party that holds it on the current roster.

<div class="projected-note" style="padding:.7rem 1rem;border:1px solid var(--color-border);border-radius:8px;background:var(--color-surface-tint);font-size:.9rem;margin:1rem 0;">
<strong>Unofficial and not certified.</strong> These figures use the Secretary of State's counts as built on <strong>{{ proj.metadata.resultsEpoch | date: "%B %-d, %Y" }} at {{ proj.metadata.resultsEpoch | date: "%-I:%M %p" }} ET</strong>, and the seat counts, flips and close races below are rebuilt from those counts every time results are published &mdash; so this page does not fall behind the count. What it is not is a live feed: it refreshes when we publish, and for the counts themselves see the <a href="{{ '/ga-general-2026-results/' | relative_url }}">results page</a>. Close races can still change in the canvass, and the seated roster does not change until the new General Assembly convenes in January 2027.<br><br>
<strong>Why this post changes.</strong> It first ran on November 4, when House district 154 led Democratic by 59 votes. Later counting put Gerald E. Greene (R) ahead there, a Republican hold rather than a flip, and the chamber totals moved with it. Rather than restate numbers by hand each time that happens, the figures here are generated from the published results.
</div>

{% include projected-majority-2026.html %}

## What the numbers show

| Chamber | Current roster | Projected | Majority line |
|---|---|---|---|
| House | {{ house.currentRepublican }} R, {{ house.currentDemocratic }} D (one Democratic seat suspended) | **{{ house.democratic }} D, {{ house.republican }} R** | {{ house.majority }} |
| Senate | {{ senate.currentRepublican }} R, {{ senate.currentDemocratic }} D | **{{ senate.democratic }} D, {{ senate.republican }} R** | {{ senate.majority }} |

{%- assign closest = proj.narrow | first -%}
{%- assign senate_narrow = proj.narrow | where: "chamber", "Senate" -%}
- **House:** {{ house.flipsToDemocratic }} seats change from Republican to Democratic and {{ house.flipsToRepublican }} from Democratic to Republican, a net gain of {{ house.netDemocraticGain }} for Democrats.
  {%- if house.democraticMargin > 0 %} That would put Democrats {{ house.democraticMargin }} seat{% if house.democraticMargin != 1 %}s{% endif %} above the {{ house.majority }}-seat majority line{% if house.democraticMargin == 1 %} — so a single district moving in the canvass would take the chamber to a {{ house.majority | minus: 1 }}&ndash;{{ house.majority | minus: 1 }} tie{% endif %}.
  {%- elsif house.democraticMargin == 0 %} That would leave Democrats exactly on the {{ house.majority }}-seat majority line.
  {%- else %} That would leave Democrats {{ 0 | minus: house.democraticMargin }} seat{% if house.democraticMargin != -1 %}s{% endif %} short of the {{ house.majority }}-seat majority line.
  {%- endif %}
- **Senate:** {{ senate.flipsToDemocratic }} seats change from Republican to Democratic{% if senate.flipsToRepublican > 0 %} and {{ senate.flipsToRepublican }} from Democratic to Republican{% endif %}.
  {%- if senate.democraticMargin < 0 %} Democrats would be {{ 0 | minus: senate.democraticMargin }} seat{% if senate.democraticMargin != -1 %}s{% endif %} short of the {{ senate.majority }}-seat majority line{% if senate.republicanMargin == 0 %}, and Republicans would sit exactly on it{% endif %}.
  {%- else %} Democrats would hold {{ senate.democraticMargin }} seat{% if senate.democraticMargin != 1 %}s{% endif %} more than the {{ senate.majority }}-seat majority line.
  {%- endif %}
- **Narrow margins:** {{ proj.narrow | size }} seats are decided by under {{ proj.metadata.narrowPoints }} points. The closest is {% if closest.chamber == "Senate" %}Senate{% else %}House{% endif %} district {{ closest.district }}, where {{ closest.marginDisplay }} votes separate the candidates out of {{ closest.totalDisplay }} cast.{%- if senate_narrow.size == 0 %} No Senate seat is inside that margin.
  {%- elsif senate_narrow.size == 1 %}{% assign sn = senate_narrow | first %} Senate district {{ sn.district }} is the only Senate seat inside it, at {{ sn.marginDisplay }} votes.
  {%- else %} {{ senate_narrow.size }} of them are Senate seats.
  {%- endif %} These are the seats most likely to move in the canvass or a recount — House district 154 was one of them on November 4, and has already changed hands once.
- **Unopposed seats:** seats marked in amber had no major-party opponent, so they were never contested between the two parties.

A bill needs a majority of all the members the chamber is entitled to, whether or not every seat can vote (Ga. Const. Art. III, Sec. V, Para. V), so the majority line is 91 in the House and 29 in the Senate regardless of vacancies.

## Method

Seats are filled by the leading candidate in each district from the Secretary of State's unofficial results, which also feed the [2026 results page]({{ '/ga-general-2026-results/' | relative_url }}). "Flipped" compares the projected party with the party of the member on the current [Majority Tracker]({{ '/ga-majority-tracker.html' | relative_url }}) roster. Names shown are the projected winners. This post does not account for recounts, runoffs or later changes to the results.

The chart and every figure above are generated by `scripts/build_projected_majority.py` from the published results, so they are not retyped and cannot drift apart from each other. Where a district has changed hands mid-term and the roster holds both members, the one with the later term start is treated as the sitting member.
