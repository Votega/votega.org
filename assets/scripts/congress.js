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

// Handles both votega.github.io/votega.org-TEST/ and votega.github.io/.
function getBasePath() {
  return window.location.pathname.includes('/votega.org-TEST/')
    ? '/votega.org-TEST/'
    : '/';
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
      return `<a class="member-row" href="${basePath}member.html?bioguideId=${encodeURIComponent(m.bioguideId)}">
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
      return `<a class="member-row" href="${basePath}member.html?bioguideId=${encodeURIComponent(current.bioguideId)}">
        <span class="member-district">District ${district}</span>
        <span class="member-name">${formatMemberName(current)}${abbrev ? ` <span class="${pClass}">(${abbrev})</span>` : ''}</span>
        <span class="member-arrow">›</span>
      </a>`;
    }

    // Vacant seat — shown inline (not gated behind a selection) since the
    // row list has no separate "choose then reveal" step.
    const vacancyMsg = district === 13
      ? `Vacant following Rep. David Scott's death. See the <a href="${basePath}ga-special-2026-runoff-results/">2026 special election runoff results</a>.`
      : `District ${district} is currently vacant.`;
    return `<div class="member-row member-row-vacant">
      <span class="member-district">District ${district}</span>
      <span class="member-name">${vacancyMsg}</span>
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
  renderMembers();
});

if (countySel) countySel.addEventListener('change', renderMembers);
updateCountyVisibility();

async function loadData() {
  statusLine.textContent = 'Loading member data…';
  try {
    const res = await fetch(DATA_URL);
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
      });
    }
  } catch (err) {
    console.error('loadData()', err);
    statusLine.textContent = err.message.includes('HTTP') ?
      'API error: ' + err.message :
      err.message;
  }
}

loadData();
