// ---------- CONFIG -------------------------------------------------
const DATA_URL = 'assets/data/ga-members.json';
// -------------------------------------------------------------------

// County → district maps (COUNTY_HOUSE_DISTRICTS, COUNTY_SENATE_DISTRICTS,
// COUNTY_US_HOUSE_DISTRICTS) are defined in ga-districts.js, loaded before this.

function buildDistrictCounties(countyMap) {
  const result = {};
  Object.entries(countyMap).forEach(([county, districts]) => {
    districts.forEach(d => {
      if (!result[d]) result[d] = [];
      result[d].push(county);
    });
  });
  return result;
}
const HOUSE_DISTRICT_COUNTIES  = buildDistrictCounties(COUNTY_HOUSE_DISTRICTS);
const SENATE_DISTRICT_COUNTIES = buildDistrictCounties(COUNTY_SENATE_DISTRICTS);

const countySel    = document.getElementById('countySelect');
const statusLine   = document.getElementById('status');
const membersOut   = document.getElementById('membersOutput');

const lookupInput  = document.getElementById('lookupInput');
const lookupBtn    = document.getElementById('lookupBtn');
const lookupMsg    = document.getElementById('lookupMsg');
const lookupBanner = document.getElementById('lookupBanner');

let allMembers = [];
// What the address box resolved to, or null. {kind:'zip', zip, senate[], house[],
// shares:{senate:{}, house:{}}} lists EVERY district touching the ZIP; {kind:'address',
// senate[], house[]} is the exact pair (an empty list = the geocoder returned no
// layer, so that chamber is left unfiltered). Never persisted and never in the URL.
let locFilter = null;
let activeTab  = 'senate';

// Populate county dropdown
Object.keys(COUNTY_HOUSE_DISTRICTS).sort().forEach(county => {
  const opt = document.createElement('option');
  opt.value = county;
  opt.textContent = county;
  countySel.appendChild(opt);
});

function partyAbbrev(party) {
  if (!party) return '';
  const p = party.toLowerCase();
  if (p.startsWith('r')) return 'R';
  if (p.startsWith('d')) return 'D';
  return party[0].toUpperCase();
}

function getBasePath() {
  return '/';
}

// Canvas cannot take var(--token) as a fillStyle, so resolve the token to its computed color.
function tokenColor(v) {
  var m = /^var\((--[^)]+)\)$/.exec(v);
  return m ? getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() : v;
}

function drawPartyChart(members) {
  const canvas = document.getElementById('partyChart');
  const legend = document.getElementById('chartLegend');
  if (!canvas || !legend) return;

  const represented = members.filter(m => m.status !== 'Vacant');
  const d = represented.filter(m => partyAbbrev(m.party) === 'D').length;
  const r = represented.filter(m => partyAbbrev(m.party) === 'R').length;
  const o = represented.length - d - r;
  const total = represented.length;

  const ctx    = canvas.getContext('2d');
  const cx     = canvas.width / 2;
  const cy     = canvas.height / 2;
  const radius = Math.min(cx, cy) - 4;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!total) { legend.innerHTML = ''; return; }

  const segments = [
    { count: d, color: 'var(--color-party-d)', label: 'Democrat' },
    { count: r, color: 'var(--color-party-r)', label: 'Republican' },
    { count: o, color: 'var(--color-text-muted)', label: 'Other' },
  ].filter(s => s.count > 0);

  let startAngle = -Math.PI / 2;
  for (const seg of segments) {
    const sweep = (seg.count / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, startAngle, startAngle + sweep);
    ctx.closePath();
    ctx.fillStyle = tokenColor(seg.color);
    ctx.fill();
    startAngle += sweep;
  }

  // Centre hole for donut effect
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.52, 0, 2 * Math.PI);
  ctx.fillStyle = tokenColor('var(--color-surface-raised)');
  ctx.fill();

  // Total count in centre
  ctx.fillStyle = tokenColor('var(--color-text)');
  ctx.font = `bold ${Math.round(radius * 0.38)}px system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(total, cx, cy);

  legend.innerHTML = segments.map(s =>
    `<span><span class="legend-dot" style="background:${s.color}"></span>${s.label} ${Math.round(s.count / total * 100)}%</span>`
  ).join('');
}

// The districts the active filter allows in this chamber, or null for no filter.
function allowedDistricts(chamberKey, countyLookup, county) {
  if (locFilter) {
    const list = locFilter[chamberKey];
    return list.length ? list : (locFilter.kind === 'address' ? null : []);
  }
  return county ? (countyLookup[county] || []) : null;
}

function renderMembers() {
  const county = countySel.value;
  const chamberName      = activeTab === 'senate' ? 'Senate' : 'House of Representatives';
  const districtCounties = activeTab === 'senate' ? SENATE_DISTRICT_COUNTIES : HOUSE_DISTRICT_COUNTIES;
  const countyLookup     = activeTab === 'senate' ? COUNTY_SENATE_DISTRICTS  : COUNTY_HOUSE_DISTRICTS;
  const basePath         = getBasePath();

  let members = allMembers.filter(m => m.chamber === chamberName);

  const chamberKey = activeTab === 'senate' ? 'senate' : 'house';
  const allowed = allowedDistricts(chamberKey, countyLookup, county);
  if (allowed) members = members.filter(m => allowed.includes(m.district));
  // A county or ZIP that touches more than one district in this chamber cannot say
  // which is the voter's, so every row carries the badge (same wording as the sample
  // ballot). One district is theirs; an exact address is never badged.
  const uncertain = !!allowed && allowed.length > 1 && !(locFilter && locFilter.kind === 'address');

  members.sort((a, b) => (a.district ?? 999) - (b.district ?? 999));

  drawPartyChart(members);

  if (!members.length) {
    membersOut.innerHTML = `<p class="empty-note">No members found${county ? ` for ${county} County` : ''}.</p>`;
    return;
  }

  membersOut.innerHTML = members.map(m => {
    const isVacant = m.status === 'Vacant';
    const isSuspended = m.status === 'Suspended';
    const abbrev = partyAbbrev(m.party);
    const pClass = abbrev === 'D' ? 'party-d' : abbrev === 'R' ? 'party-r' : '';
    const counties = (districtCounties[m.district] || []).join(', ');
    // A suspended member keeps their seat (a suspension can be lifted and there
    // is no successor/Vacant entry), so they stay in the list — but with a badge
    // and muted name so they read as not-normally-seated, matching the amber
    // status banner on their ga-member.html detail page. Resigned/Removed/
    // Deceased are filtered out upstream in loadData().
    const suspendedPill = isSuspended
      ? ` <span style="display:inline-block;font-size:0.72em;font-weight:600;text-transform:uppercase;letter-spacing:0.03em;color:var(--color-warning);background:var(--color-warning-tint);border:1px solid var(--color-warning);border-radius:3px;padding:0.05em 0.4em;vertical-align:middle;">Suspended</span>`
      : '';
    const nameHtml = isVacant
      ? `<span style="color:var(--color-text-muted);font-style:italic;">Vacant</span>`
      : `<span${isSuspended ? ' style="color:var(--color-text-muted);"' : ''}>${m.name}${abbrev ? ` <span class="${pClass}">(${abbrev})</span>` : ''}</span>${suspendedPill}`;
    // Clean /ga-legislators/<slug>/ when the map has this member; the
    // ga-member.html shell (which only redirects there) is the fallback.
    const share = uncertain && locFilter && locFilter.kind === 'zip'
      ? window.ZipDistricts.shareLabel(locFilter.shares[chamberKey][m.district]) : null;
    const note = share || uncertain
      ? `<span class="member-note">${share || ''}${share && uncertain ? ' ' : ''}${uncertain ? `<span class="member-badge">may not be your district</span>` : ''}</span>` : '';
    const memberHref = VoteGA.entityUrls.get(
      'ga-legislator', m.id, `${basePath}ga-member.html?id=${encodeURIComponent(m.id)}`);
    return `<a class="member-row" href="${memberHref}">
      <span class="member-district">District ${m.district}</span>
      <span class="member-name">${nameHtml}${note}</span>
      <span class="member-counties">${counties}</span>
      <span class="member-arrow">›</span>
    </a>`;
  }).join('');
}

document.getElementById('tabBar').addEventListener('click', e => {
  const btn = e.target.closest('.tab-btn');
  if (!btn) return;
  activeTab = btn.dataset.tab;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
  countySel.value = '';
  renderMembers();
});

// One district filter at a time: picking a county drops a ZIP/address result.
countySel.addEventListener('change', () => { clearLookup(); renderMembers(); });

function clearLookup() {
  locFilter = null;
  lookupBanner.classList.remove('visible');
  lookupBanner.innerHTML = '';
  lookupMsg.textContent = '';
}

function showBanner(html) {
  lookupBanner.innerHTML = html + '<button type="button" id="lookupClear">Clear</button>';
  lookupBanner.classList.add('visible');
  document.getElementById('lookupClear').addEventListener('click', () => {
    clearLookup();
    lookupInput.value = '';
    lookupMsg.textContent = '';
    renderMembers();
  });
}

const ZIP_NEXT = ' Pick your county below, or enter your full street address.';

const addressLookup = window.AddressLookup.createAddressLookup({
  input: lookupInput,
  button: lookupBtn,
  subject: 'your districts',
  fallbackPhrase: 'pick your county below',
  eventName: 'reps_lookup',
  eventParams: { page: 'ga_state_reps' },
  save: false,   // derived districts stay on this page; nothing is carried over
  setStatus: (message, isError) => { lookupMsg.textContent = isError ? message : ''; },
  // A bare ZIP is answered from the static table, not refused: every district
  // touching it, fetched only now. A PO-box, unknown or failed-fetch ZIP clears
  // the previous filter and says what to do instead, so the list always matches
  // what is in the input box -- a stale "Showing ZIP 30004" under an error about
  // 30003 reads as a contradiction. Same behaviour as the other lookup pages.
  onZip: async (zip) => {
    const stop = (message, outcome) => {
      clearLookup();
      renderMembers();
      lookupMsg.textContent = message + ZIP_NEXT;   // after clearLookup(), which empties it
      return outcome;
    };
    let found;
    try {
      found = window.ZipDistricts.lookup(zip, await window.ZipDistricts.load(getBasePath()));
    } catch (err) {
      console.error('ZIP table', err);
      return stop('ZIP code data couldn\u2019t be loaded right now.', 'zip_error');
    }
    if (found.status === 'unknown') {
      return stop(`ZIP ${zip} isn\u2019t in our list of Georgia ZIP codes.`, 'zip_unknown');
    }
    if (found.status !== 'ok') {
      return stop(`ZIP ${zip} is a PO box ZIP, which doesn\u2019t map to any district.`, 'zip_no_districts');
    }
    countySel.value = '';
    locFilter = {
      kind: 'zip', zip, senate: found.stateSenate, house: found.stateHouse,
      shares: { senate: found.shares.stateSenate, house: found.shares.stateHouse },
    };
    showBanner(`<span>Showing districts touching ZIP <strong>${zip}</strong>. A ZIP can span several districts \u2014 enter your full address to narrow this to yours.</span>`);
    renderMembers();
    return 'zip';
  },
  onResolve: (loc) => {
    countySel.value = '';
    const one = v => (v == null ? [] : [v]);
    locFilter = { kind: 'address', senate: one(loc.stateSenate), house: one(loc.stateHouse) };
    const parts = [];
    if (loc.stateSenate != null) parts.push(`State Senate ${loc.stateSenate}`);
    if (loc.stateHouse != null) parts.push(`State House ${loc.stateHouse}`);
    showBanner(`<span>Showing your districts: <strong>${parts.join(' \u00b7 ') || 'none found'}</strong>.</span>`);
    renderMembers();
  },
});
lookupBtn.addEventListener('click', () => addressLookup.run());
lookupInput.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addressLookup.run(); } });

async function loadData() {
  statusLine.textContent = 'Loading member data…';
  try {
    // Awaited before the roster renders, so rows link clean on first paint.
    // Resolves to {} if the map is unavailable and every row keeps its shell.
    await VoteGA.entityUrls.load(getBasePath());
    const res = await fetch(getBasePath() + DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    // Resigned/Removed/Deceased entries are historical records kept only so
    // ga-member-votes.json can still join their earlier votes by OCD id — the
    // seat itself is already reflected by a successor or a separate Vacant
    // entry, so these must not appear as an extra current member here.
    allMembers = (data.members || []).filter(m => !['Resigned', 'Removed', 'Deceased'].includes(m.status));
    statusLine.textContent = '';
    renderMembers();
    // Provenance stamp — see CODEBASE-REVIEW-2026-08-18.md finding 4.13. One line, dated
    // from this file's own timestamp, naming the source and the published dataset (the
    // sibling repo, per CLAUDE.md, not the internal assets/data path). The links are fixed
    // author-set markup, so it is composed here rather than through dataStamp.render(),
    // which escapes its source text. The date is omitted, not faked, when the file has none.
    const stampEl = document.getElementById('dataStamp');
    if (stampEl) {
      const when = window.dataStamp ? window.dataStamp.formatDate((data.metadata || {}).generatedAt) : '';
      stampEl.classList.add('data-stamp');
      const stale = (when && window.VotegaFreshness)
        ? window.VotegaFreshness.suffix('ga-members', (data.metadata || {}).generatedAt) : '';
      stampEl.innerHTML = (when ? `Data last updated: ${when}${stale} &middot; ` : '')
        + 'Source: <a href="https://www.legis.ga.gov" target="_blank" rel="noopener">Georgia General Assembly</a>&rsquo;s official web service'
        + ' and published as open data at <a href="https://github.com/Votega/ga-legislators" target="_blank" rel="noopener">Votega/ga-legislators</a>';
    }
  } catch (err) {
    console.error('loadData()', err);
    statusLine.textContent =
      'Data file missing or inaccessible. Check that assets/data/ga-members.json exists.';
  }
}

loadData();