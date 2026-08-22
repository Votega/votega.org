// sample-ballot.js
// Resolves a Georgia voter (by address, or by county as a fallback) to the set of
// contests that appear on their ballot, then groups them for display.
//
// Data-correctness spine only — no rendering here. A page (sample-ballot.html) calls
// resolveBallot() and renders the grouped result.
//
// Requires ga-districts.js to be loaded first (provides the geographic maps):
//   COUNTY_US_HOUSE_DISTRICTS, COUNTY_HOUSE_DISTRICTS, COUNTY_SENATE_DISTRICTS,
//   CIRCUIT_COUNTIES, COUNTY_CIRCUIT
// Consumes assets/data/races.json and assets/data/ga-ballot-measures.json.
//
// Resolution precision (see the contest-resolvability map):
//   • Statewide (U.S. Senate, state executives, PSC, appellate courts) — everyone.
//   • U.S. House / state House / state Senate — exact from an address geocode; with
//     county only, every overlapping district is returned and flagged `ambiguous`.
//   • Superior Court — exact from county (circuits are whole-county groupings).
//   • Ballot measures — statewide unless a measure carries a `scope`/`counties` field.

'use strict';

/* ------------------------------------------------------------------ *
 * Config
 * ------------------------------------------------------------------ */

const CENSUS_GEOCODER_URL = 'https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress';
// Census sends no CORS header, so the browser must use JSONP (a <script> tag with a
// callback), not fetch(). benchmark/vintage "Current" track the active districts.
const CENSUS_PARAMS = 'benchmark=Public_AR_Current&vintage=Current_Current&layers=all&format=jsonp';
const CENSUS_TIMEOUT_MS = 12000;

function sbBasePath() {
  return window.location.pathname.includes('/votega.org-TEST/') ? '/votega.org-TEST/' : '/';
}

/* ------------------------------------------------------------------ *
 * Step 1 — Address → districts (Census Geocoder, via JSONP)
 * ------------------------------------------------------------------ */

// Match a geographies layer by substring so year-prefixed keys ("119th Congressional
// Districts", "2024 State Legislative Districts - Lower") keep resolving after
// redistricting renames the layer.
function pickLayer(geographies, needle) {
  const key = Object.keys(geographies).find(k => k.toLowerCase().includes(needle));
  const entry = key && geographies[key] && geographies[key][0];
  return entry || null;
}

// Parse one Census addressMatch into a location object. Returns null if the match is
// not in Georgia or is missing the layers we need.
function parseCensusMatch(match) {
  const g = match.geographies || {};
  const state = pickLayer(g, 'states');
  if (state && String(state.GEOID) !== '13') return null; // 13 = Georgia (FIPS)

  const county   = pickLayer(g, 'counties');
  const usHouse  = pickLayer(g, 'congressional districts');
  const stHouse  = pickLayer(g, 'legislative districts - lower');
  const stSenate = pickLayer(g, 'legislative districts - upper');
  if (!county) return null;

  const toInt = e => (e && e.BASENAME != null ? parseInt(e.BASENAME, 10) : null);
  return {
    source: 'address',
    matchedAddress: match.matchedAddress || null,
    county: county.BASENAME,                 // e.g. "Fulton", "DeKalb" (no "County" suffix)
    usHouse: toInt(usHouse),                  // int or null
    stateHouse: toInt(stHouse),               // int or null
    stateSenate: toInt(stSenate),             // int or null
  };
}

// Geocode a one-line address via JSONP. Resolves to a location object, or rejects with
// a user-facing Error. Browser-only (needs document); tests exercise parseCensusMatch().
function geocodeAddress(address) {
  return new Promise((resolve, reject) => {
    const cb = '__sbGeo' + Math.random().toString(36).slice(2);
    const script = document.createElement('script');
    let done = false;

    const cleanup = () => {
      if (script.parentNode) script.parentNode.removeChild(script);
      try { delete window[cb]; } catch (_) { window[cb] = undefined; }
      clearTimeout(timer);
    };
    const fail = msg => { if (done) return; done = true; cleanup(); reject(new Error(msg)); };

    const timer = setTimeout(
      () => fail('The address lookup timed out. Check your connection and try again.'),
      CENSUS_TIMEOUT_MS);

    window[cb] = payload => {
      if (done) return;
      done = true;
      cleanup();
      try {
        const matches = payload && payload.result && payload.result.addressMatches;
        if (!matches || !matches.length) {
          reject(new Error('That address could not be found. Try a full street address, or pick your county below.'));
          return;
        }
        const loc = parseCensusMatch(matches[0]);
        if (!loc) {
          reject(new Error('That address does not appear to be in Georgia.'));
          return;
        }
        resolve(loc);
      } catch (e) {
        reject(new Error('The address lookup returned unexpected data. Try your county below.'));
      }
    };

    script.onerror = () => fail('The address lookup service could not be reached. Try again, or pick your county below.');
    script.src = `${CENSUS_GEOCODER_URL}?address=${encodeURIComponent(address)}&${CENSUS_PARAMS}&callback=${cb}`;
    document.body.appendChild(script);
  });
}

// County-only fallback: districts unknown, so downstream filtering widens to every
// district overlapping the county and flags those contests ambiguous.
function locationFromCounty(county) {
  return { source: 'county', matchedAddress: null, county,
           usHouse: null, stateHouse: null, stateSenate: null };
}

/* ------------------------------------------------------------------ *
 * Step 2/3 — Contest assembly + correctness guardrails
 * ------------------------------------------------------------------ */

// Newest cycle present, so a new election year "just works" without a code change
// (mirrors elections.html).
function newestCycle(races) {
  const cycles = [...new Set(races.map(r => r.cycle).filter(Boolean))].sort((a, b) => b - a);
  return cycles[0] ?? null;
}

// Count candidates in a phase across both storage shapes (partisan `ballots`, nonpartisan
// `candidates`), ignoring withdrawals.
function phaseCandidateCount(phase) {
  if (!phase) return 0;
  const flat = (phase.candidates || []).filter(c => !c.withdrawn).length;
  const keyed = Object.values(phase.ballots || {})
    .reduce((s, arr) => s + arr.filter(c => !c.withdrawn).length, 0);
  return flat + keyed;
}

// The phase of a race held on a given election date, or null.
function phaseForDate(race, date) {
  const phases = race.phases || {};
  const name = Object.keys(phases).find(p => phases[p] && phases[p].electionDate === date);
  return name ? Object.assign({ _name: name }, phases[name]) : null;
}

// The set of elections that actually have contests, newest data driving the list.
// An election is a date; labels come from ga-election-calendar.json (matched by date).
// Only dates carrying at least one contest (a race phase with candidates, or a measure)
// appear — so the dropdown never offers an empty election.
function availableElections(races, measures, calendar) {
  const dates = new Set();
  (races || []).forEach(r => Object.values(r.phases || {}).forEach(p => {
    if (p.electionDate && phaseCandidateCount(p) > 0) dates.add(p.electionDate);
  }));
  (measures || []).forEach(m => { if (m.electionDate) dates.add(m.electionDate); });

  const cal = calendar || [];
  return [...dates].sort().map(date => {
    const e = cal.find(c => c.date === date);
    return { date, id: e ? e.id : date, name: e ? e.name : date, type: e ? e.type : null };
  });
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

// Elections to offer in the selector: a sample ballot is forward-looking, so past
// elections are hidden (their results pages take over). Election day itself still
// counts as upcoming (date >= today). Off-season — when nothing is upcoming — fall back
// to the single most recent election so the tool still shows a ballot instead of an
// empty selector.
function selectableElections(available, today) {
  const t = today || todayISO();
  const upcoming = available.filter(e => e.date >= t).sort((a, b) => a.date < b.date ? -1 : 1);
  if (upcoming.length) return upcoming;
  const past = available.filter(e => e.date < t).sort((a, b) => a.date < b.date ? 1 : -1);
  return past.slice(0, 1);
}

// Default election: the next broad (non-special) election on or after today, since a
// special concerns only a sliver of voters and makes a poor landing default. Fall back
// to the next upcoming special if that's all there is, then to the most recent past one.
function defaultElectionDate(available, today) {
  const t = today || todayISO();
  const upcoming = available.filter(e => e.date >= t).sort((a, b) => a.date < b.date ? -1 : 1);
  const isSpecial = e => e.type && /special/i.test(e.type);
  const broad = upcoming.find(e => !isSpecial(e));
  if (broad) return broad.date;
  if (upcoming.length) return upcoming[0].date;
  const past = available.map(e => e.date).sort();
  return past[past.length - 1] || null;
}

// Derive the Superior Court circuit slug from a race id
// ("superior-court-<slug>-<name>-YYYY"). Circuit slugs and candidate surnames both
// contain hyphens, so match the id against the known circuit slugs (longest first).
function circuitSlugFromRaceId(id) {
  if (typeof CIRCUIT_COUNTIES === 'undefined') return null;
  const rest = String(id).replace(/^superior-court-/, '');
  const slugs = Object.keys(CIRCUIT_COUNTIES).sort((a, b) => b.length - a.length);
  return slugs.find(s => rest.startsWith(s + '-')) || null;
}

// Does this race belong on the ballot for `loc`? Returns { include, ambiguous }.
// Encapsulates the guardrails:
//   • PSC has a district number but is elected STATEWIDE — never filter it by district.
//   • District contests fall back to county overlap (ambiguous) when the district is
//     unknown (county-only lookup).
//   • Superior Court resolves by county → circuit (exact; circuits are whole counties).
function raceApplies(race, loc) {
  const NO  = { include: false, ambiguous: false };
  const YES = { include: true,  ambiguous: false };

  const byDistrict = (district, voterDistrict, countyMap) => {
    if (district == null) return YES;                       // treat as at-large
    if (voterDistrict != null) return district === voterDistrict ? YES : NO;
    // District unknown (county-only): include if the district overlaps the county.
    const dists = (countyMap && loc.county && countyMap[loc.county]) || [];
    return dists.includes(district) ? { include: true, ambiguous: true } : NO;
  };

  switch (race.level) {
    case 'federal':
      if (race.chamber === 'U.S. Senate') return YES;        // statewide
      if (race.chamber === 'U.S. House')
        return byDistrict(race.district, loc.usHouse, typeof COUNTY_US_HOUSE_DISTRICTS !== 'undefined' ? COUNTY_US_HOUSE_DISTRICTS : null);
      return YES;

    case 'state-executive':
      // Public Service Commissioner: district is a residency requirement, not the
      // electorate — every voter votes on it. Do NOT filter by district. (Guardrail)
      return YES;                                            // Gov, AG, PSC, etc. all statewide

    case 'state-judicial':
      if (race.chamber === 'Superior Court') {
        if (typeof COUNTY_CIRCUIT === 'undefined' || !loc.county) return NO;
        const voterCircuit = COUNTY_CIRCUIT[loc.county] || null;
        return voterCircuit && circuitSlugFromRaceId(race.id) === voterCircuit ? YES : NO;
      }
      return YES;                                            // Supreme Court, Court of Appeals — statewide

    case 'state':
      if (race.chamber === 'Georgia House of Representatives')
        return byDistrict(race.district, loc.stateHouse, typeof COUNTY_HOUSE_DISTRICTS !== 'undefined' ? COUNTY_HOUSE_DISTRICTS : null);
      if (race.chamber === 'Georgia State Senate')
        return byDistrict(race.district, loc.stateSenate, typeof COUNTY_SENATE_DISTRICTS !== 'undefined' ? COUNTY_SENATE_DISTRICTS : null);
      return NO;

    default:
      return NO;
  }
}

// Flatten a phase's candidates into one list. races.json stores two shapes: partisan
// races use `ballots` (party-keyed: {Democrat:[…], Republican:[…]}), while nonpartisan
// races (all judicial) use a flat `candidates` array. Handle both, as race.html and
// elections.html do. Withdrawn candidates are dropped.
function candidatesForPhase(phase) {
  if (!phase) return [];
  let out;
  if (phase.ballots) {
    out = [];
    Object.keys(phase.ballots).forEach(party => {
      (phase.ballots[party] || []).forEach(c => out.push({ party, ...c }));
    });
  } else {
    out = (phase.candidates || []).map(c => ({ ...c }));
  }
  return out.filter(c => !c.withdrawn);
}

// Back-compat: candidates for a race's own activePhase.
function candidatesForActivePhase(race) {
  return candidatesForPhase(race.phases && race.phases[race.activePhase]);
}

// Ballot-measure guardrail: statewide unless a measure declares scope/counties.
// (No current measure carries scope, so all resolve statewide — but the schema may add
// `scope: "local"` + `counties: [...]`, and this is forward-compatible with that.)
function measureApplies(measure, loc) {
  const scope = measure.scope || measure.jurisdiction || null;
  const counties = measure.counties || null;
  if (scope && String(scope).toLowerCase() === 'local' && Array.isArray(counties))
    return loc.county ? counties.includes(loc.county) : false;
  return true; // statewide
}

// Assemble the ballot for a resolved location and a chosen election.
// opts: { races, measures, calendar?, electionDate? }.
// electionDate selects which phase of each race to show; when omitted it defaults to the
// next upcoming election that has contests. Returns ordered contest groups plus the list
// of selectable elections (for the "Which election?" control).
function assembleBallot(loc, opts) {
  const races    = (opts && opts.races) || [];
  const measures = (opts && opts.measures) || [];
  const calendar = (opts && opts.calendar) || [];

  const available    = availableElections(races, measures, calendar);
  const electionDate = (opts && opts.electionDate) || defaultElectionDate(available);
  const election     = available.find(e => e.date === electionDate)
                       || { date: electionDate, id: electionDate, name: electionDate, type: null };

  const contests = [];
  races.forEach(race => {
    const phase = phaseForDate(race, electionDate);   // the phase held on this date, or null
    if (!phase) return;
    const candidates = candidatesForPhase(phase);
    if (!candidates.length) return;                   // race isn't on this election's ballot
    const verdict = raceApplies(race, loc);           // geography (unchanged)
    if (!verdict.include) return;
    contests.push({
      kind: 'race',
      id: race.id,
      level: race.level,
      chamber: race.chamber,
      district: race.district ?? null,
      phase: phase._name,                             // which phase this came from
      ambiguous: verdict.ambiguous,                   // true only for county-only district guesses
      candidates,
      race,
    });
  });

  // Measures on this election's ballot that pass the scope guardrail.
  const measureContests = measures
    .filter(m => m.electionDate === electionDate && measureApplies(m, loc))
    .map(m => ({ kind: 'measure', id: m.id, status: m.status || null, measure: m }));

  // Group in ballot order.
  const GROUPS = [
    { key: 'federal',         label: 'Federal',              levels: ['federal'] },
    { key: 'state-executive', label: 'Statewide Executive',  levels: ['state-executive'] },
    { key: 'state',           label: 'State Legislature',    levels: ['state'] },
    { key: 'state-judicial',  label: 'Judicial',             levels: ['state-judicial'] },
  ];
  const groups = GROUPS.map(g => ({
    key: g.key, label: g.label,
    contests: contests.filter(c => g.levels.includes(c.level)),
  })).filter(g => g.contests.length);

  if (measureContests.length)
    groups.push({ key: 'ballot-measures', label: 'Ballot Measures', contests: measureContests });

  return {
    election,                                // { date, id, name, type }
    electionDate,
    available,                               // all selectable elections (for the dropdown)
    location: loc,
    groups,
    totalContests: contests.length + measureContests.length,
    ambiguous: contests.some(c => c.ambiguous),
  };
}

/* ------------------------------------------------------------------ *
 * Orchestrator
 * ------------------------------------------------------------------ */

async function loadJson(relPath) {
  const res = await fetch(sbBasePath() + relPath);
  if (!res.ok) throw new Error(`Data file missing or inaccessible: ${relPath}`);
  return res.json();
}

// Resolve a full ballot. input: { address } (exact) or { county } (fallback).
// Returns the assembleBallot() result. Throws a user-facing Error on lookup failure.
async function resolveBallot(input) {
  const [racesDoc, measuresDoc, calendarDoc] = await Promise.all([
    loadJson('assets/data/races.json'),
    loadJson('assets/data/ga-ballot-measures.json').catch(() => ({ measures: [] })),
    loadJson('assets/data/ga-election-calendar.json').catch(() => ({ elections: [] })),
  ]);
  const races    = racesDoc.races || [];
  const measures = measuresDoc.measures || [];
  const calendar = calendarDoc.elections || [];

  let loc;
  if (input && input.address) loc = await geocodeAddress(input.address);
  else if (input && input.county) loc = locationFromCounty(input.county);
  else throw new Error('Enter an address or choose a county.');

  return assembleBallot(loc, { races, measures, calendar, electionDate: input && input.electionDate });
}

/* ------------------------------------------------------------------ *
 * Exports (browser global + node for tests)
 * ------------------------------------------------------------------ */

const SampleBallot = {
  geocodeAddress, parseCensusMatch, locationFromCounty,
  assembleBallot, raceApplies, measureApplies,
  circuitSlugFromRaceId, candidatesForPhase, candidatesForActivePhase,
  availableElections, selectableElections, defaultElectionDate, phaseForDate, newestCycle,
  resolveBallot,
};
if (typeof window !== 'undefined') window.SampleBallot = SampleBallot;
if (typeof module !== 'undefined' && module.exports) module.exports = SampleBallot;
