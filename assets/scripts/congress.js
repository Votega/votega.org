// ---------- CONFIG -------------------------------------------------
const DATA_URL  = 'assets/data/current-members.json';
// The member list is prebuilt by GitHub Actions and served as static JSON.
// -------------------------------------------------------------------

function formatMemberName(m) {
  const honorific = m.honorificName || '';
  const firstName = m.firstName || '';
  const lastName = m.lastName || '';
  const fallback = m.name || 'Unknown';
  return (firstName && lastName)
    ? `${honorific} ${firstName} ${lastName}`.trim()
    : (honorific ? `${honorific} ${fallback}` : fallback);
}

// Site is served at the domain root (www.votega.org), so the base path is '/'.
function getBasePath() {
  return '/';
}

function partyAbbrev(partyName) {
  if (!partyName) return '';
  const p = partyName.toLowerCase();
  if (p.startsWith('d')) return 'D';
  if (p.startsWith('r')) return 'R';
  return partyName[0].toUpperCase();
}

const tabBar      = document.getElementById('tabBar');
const countyWrap  = document.getElementById('countyFilterWrap');
const countySel   = document.getElementById('countySelect');
const statusLine  = document.getElementById('status');
const membersOut  = document.getElementById('membersOutput');

let allMembers = [];
let activeTab  = 'house'; // 'house' | 'senate'

// Set by a location lookup (see federal-reps.html): the U.S. House district(s) the
// voter's location falls in. An address resolves to exactly one; a bare ZIP resolves
// to every district touching it, which is why this is a list. null means no filter,
// which is also what every other control resets it to -- picking a county or
// switching chambers is the voter saying "show me something else", so the narrowed
// view must not survive it.
let exactDistricts = null;   // number[] | null
let exactNote      = '';     // already-escaped HTML, or '' for no note
let exactShares    = null;   // district -> share of the ZIP, for a ZIP filter only

const lookupNote = document.getElementById('lookupNote');

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// Narrow the list to one district. `label` is the matched address, shown so the
// voter can see which address the geocoder actually resolved -- it is echoed
// back into the page, so it is escaped here rather than trusted.
function setExactDistrict(district, label) {
  exactShares = null;
  if (!Number.isInteger(district)) {
    exactDistricts = null;
    exactNote = '';
  } else {
    exactDistricts = [district];
    exactNote = `Showing <strong>District ${district}</strong>`
      + (label ? ` for <strong>${escHtml(label)}</strong>` : ' from your earlier address lookup')
      + '. <button type="button" class="lookup-reset" id="lookupReset">Show all districts</button>';
  }
  renderMembers();
}

// Narrow the list to every district touching a ZIP. A ZIP is not a location -- it
// can span several districts and only a street address says which is the voter's --
// so the note says so. `districts` are the table's integers; `sourceHtml` is the
// ZIP table's own provenance line, already escaped by the page ('' for none).
// `shares` maps district -> its share of the ZIP, for the per-row label.
function setZipDistricts(districts, zip, sourceHtml, shares) {
  exactShares = shares || null;
  const list = Array.isArray(districts) ? districts.filter(Number.isInteger) : [];
  if (!list.length) {
    exactDistricts = null;
    exactNote = '';
  } else {
    const which = list.length === 1 ? `District ${list[0]}` : `Districts ${list.join(', ')}`;
    exactNote = `Showing <strong>${which}</strong> touching <strong>ZIP ${escHtml(zip)}</strong>.`
      + (list.length > 1
          ? ' A ZIP can span several districts &mdash; enter your full address to narrow this to yours.'
          : '')
      + ' <button type="button" class="lookup-reset" id="lookupReset">Show all districts</button>'
      + (sourceHtml ? `<div class="lookup-source">${sourceHtml}</div>` : '');
    exactDistricts = list;
  }
  renderMembers();
}

function clearExactDistrict() {
  if (exactDistricts == null) return;
  exactDistricts = null;
  exactNote = '';
  exactShares = null;
}

if (typeof window !== 'undefined') {
  window.FederalReps = { setExactDistrict, setZipDistricts, clearExactDistrict };
}

if (countySel && typeof COUNTY_US_HOUSE_DISTRICTS !== 'undefined') {
  Object.keys(COUNTY_US_HOUSE_DISTRICTS).sort().forEach(county => {
    const opt = document.createElement('option');
    opt.value = county;
    opt.textContent = county;
    countySel.appendChild(opt);
  });
}

// U.S. Senate has no districts, so the county filter only means anything for
// the House — hide it otherwise rather than showing a control that can't do
// anything for the selected chamber.
function updateCountyVisibility() {
  if (!countyWrap) return;
  const isHouse = activeTab === 'house';
  countyWrap.style.display = isHouse ? '' : 'none';
  if (!isHouse && countySel) countySel.value = '';
}

function renderMembers() {
  const county      = countySel ? countySel.value : '';
  const chamberName = activeTab === 'senate' ? 'Senate' : 'House of Representatives';
  const basePath    = getBasePath();

  // The Senate tab has no districts -- both senators represent the whole state --
  // so an address filter is meaningless there. exactDistricts is left set rather
  // than cleared, so switching back to the House tab keeps the lookup the voter
  // just did. Resolved here, above the Senate branch's early return, because a
  // note written only on the House path would stay on screen after that return.
  const exact = activeTab === 'house' ? exactDistricts : null;
  if (lookupNote) lookupNote.innerHTML = exact != null ? exactNote : '';

  const members = allMembers.filter(m => {
    const terms = m.terms?.item || m.terms || [];
    if (!Array.isArray(terms)) return false;
    const latestTerm = terms[terms.length - 1] || {};
    return latestTerm.chamber === chamberName;
  });

  if (activeTab === 'senate') {
    const senators = members
      .filter(m => m.currentMember !== false)
      .sort((a, b) => a.name.localeCompare(b.name));

    if (!senators.length) {
      membersOut.innerHTML = `<p class="empty-note">No senators found.</p>`;
      return;
    }

    membersOut.innerHTML = senators.map(m => {
      const abbrev = partyAbbrev(m.partyName);
      const pClass = abbrev === 'D' ? 'party-d' : abbrev === 'R' ? 'party-r' : '';
      return `<a class="member-row" href="${VoteGA.entityUrls.get('us-congress', m.bioguideId, `${basePath}member.html?bioguideId=${encodeURIComponent(m.bioguideId)}`)}">
        <span class="member-name">${formatMemberName(m)}${abbrev ? ` <span class="${pClass}">(${abbrev})</span>` : ''}</span>
        <span class="member-arrow">›</span>
      </a>`;
    }).join('');
    return;
  }

  // House — group by district to detect vacancies. A seat vacated by death,
  // resignation, or expulsion has no member in current-members.json at all, so
  // grouping the member list alone would silently drop the district. Take the
  // seat list from the county→district map when it is loaded, and otherwise
  // infer it as 1..highest-seen, so a vacancy shows up as a vacancy rather
  // than disappearing.
  const districtMap = new Map();
  members.forEach(m => {
    const dist = m.district ?? 'At-Large';
    if (!districtMap.has(dist)) districtMap.set(dist, []);
    districtMap.get(dist).push(m);
  });

  const seats = new Set(
    typeof COUNTY_US_HOUSE_DISTRICTS !== 'undefined'
      ? Object.values(COUNTY_US_HOUSE_DISTRICTS).flat()
      : []
  );
  const numbered = [...districtMap.keys()].filter(d => d !== 'At-Large').map(Number);
  if (!seats.size && numbered.length) {
    for (let i = 1; i <= Math.max(...numbered); i++) seats.add(i);
  }
  numbered.forEach(d => seats.add(d));

  let ordered = [...seats].sort((a, b) => a - b);
  if (districtMap.has('At-Large')) ordered.push('At-Large');

  if (county && typeof COUNTY_US_HOUSE_DISTRICTS !== 'undefined' && COUNTY_US_HOUSE_DISTRICTS[county]) {
    const countyDistricts = new Set(COUNTY_US_HOUSE_DISTRICTS[county]);
    ordered = ordered.filter(d => countyDistricts.has(d));
  }

  if (exact != null) ordered = ordered.filter(d => exact.includes(d));

  // Same rule as the Georgia legislator lists: when a ZIP or county leaves more than
  // one district in play, none of them is known to be the voter's, so each row says so.
  // An address (one district) and the unfiltered list carry no badge. A ZIP also says
  // how much of itself each district covers.
  const zipFiltered = exact != null && exactShares != null;
  const uncertain   = ordered.length > 1 && (zipFiltered || (exact == null && !!county));
  function noteFor(district) {
    if (!uncertain) return '';
    const share = zipFiltered && window.ZipDistricts
      ? window.ZipDistricts.shareLabel(exactShares[district]) : null;
    return `<span class="member-note">${share || ''}${share ? ' ' : ''}`
      + `<span class="member-badge">may not be your district</span></span>`;
  }

  if (!ordered.length) {
    membersOut.innerHTML = `<p class="empty-note">No House district found${county ? ` for ${county} County` : ''}.</p>`;
    return;
  }

  membersOut.innerHTML = ordered.map(district => {
    const districtMembers = districtMap.get(district) || districtMap.get(String(district)) || [];
    const current = districtMembers.find(m => m.currentMember !== false);

    if (current) {
      const abbrev = partyAbbrev(current.partyName);
      const pClass = abbrev === 'D' ? 'party-d' : abbrev === 'R' ? 'party-r' : '';
      return `<a class="member-row" href="${VoteGA.entityUrls.get('us-congress', current.bioguideId, `${basePath}member.html?bioguideId=${encodeURIComponent(current.bioguideId)}`)}">
        <span class="member-district">District ${district}</span>
        <span class="member-name">${formatMemberName(current)}${abbrev ? ` <span class="${pClass}">(${abbrev})</span>` : ''}${noteFor(district)}</span>
        <span class="member-arrow">›</span>
      </a>`;
    }

    // Vacant seat — shown inline (not gated behind a selection) since the
    // row list has no separate "choose then reveal" step.
    // Deliberately generic: this branch is reached only when current-members.json
    // has no sitting member for the district. A district-specific message here (the
    // old GA-13 text after Rep. Scott's death) goes stale the moment the seat is
    // filled and has to be remembered and removed by hand.
    const vacancyMsg = `District ${district} is currently vacant.`;
    return `<div class="member-row member-row-vacant">
      <span class="member-district">District ${district}</span>
      <span class="member-name">${vacancyMsg}${noteFor(district)}</span>
    </div>`;
  }).join('');
}

tabBar.addEventListener('click', e => {
  const btn = e.target.closest('.tab-btn');
  if (!btn) return;
  activeTab = btn.dataset.tab;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
  updateCountyVisibility();
  if (countySel) countySel.value = '';
  clearExactDistrict();
  renderMembers();
});

if (countySel) countySel.addEventListener('change', () => {
  clearExactDistrict();
  renderMembers();
});

// "Show all districts" inside the note. Delegated: the note is re-rendered on
// every pass, so a listener bound to the button itself would not survive.
if (lookupNote) lookupNote.addEventListener('click', e => {
  if (!e.target.closest('#lookupReset')) return;
  if (countySel) countySel.value = '';
  clearExactDistrict();
  renderMembers();
});
updateCountyVisibility();

async function loadData() {
  statusLine.textContent = 'Loading member data…';
  try {
    // Awaited before rendering so rows link straight to /us-congress/<slug>/
    // instead of the member.html shell that redirects there; {} if unavailable.
    await VoteGA.entityUrls.load(getBasePath());
    const res = await fetch(getBasePath() + DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const results = data.members || [];

    if (results.length === 0) {
      throw new Error('Legislator data is temporarily unavailable. Please try again later.');
    }

    // Site scope is limited to GA's federal delegation.
    allMembers = results.filter(m => m && typeof m === 'object' && m.state === 'Georgia' && m.name);
    statusLine.textContent = '';
    renderMembers();
    // Provenance stamp — see CODEBASE-REVIEW-2026-08-18.md finding 4.13.
    if (window.dataStamp) {
      window.dataStamp.render('dataStamp', {
        updated: (data.metadata || {}).generatedAt,
        source:  (data.metadata || {}).source || 'Congress.gov API',
        repo:    { url: 'https://github.com/Votega/ga-federal-legislators' },
      });
    }
  } catch (err) {
    console.error('loadData()', err);
    statusLine.textContent =
      'Data file missing or inaccessible. Check that assets/data/current-members.json exists.';
  }
}

loadData();
