// ---------- CONFIG -------------------------------------------------
const DATA_URL = 'assets/data/ga-members.json';
// -------------------------------------------------------------------

// County → district maps (COUNTY_HOUSE_DISTRICTS, COUNTY_SENATE_DISTRICTS,
// COUNTY_US_HOUSE_DISTRICTS) are defined in ga-districts.js, which must be
// loaded before this script.

// Build reverse lookup: district number → counties served
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

const countySel      = document.getElementById('countySelect');
const chamberSel     = document.getElementById('chamberSelect');
const districtSel    = document.getElementById('districtSelect');
const statusLine     = document.getElementById('status');
const form           = document.getElementById('lookupForm');
const allMembersOut  = document.getElementById('allMembersOutput');

const chamberLabel   = chamberSel.closest('label');
const districtLabel  = districtSel.closest('label');
const submitBtn      = form.querySelector('button[type="submit"]');

let allMembers = [];

// Populate county dropdown — "All Members" first, then counties
const allOpt = document.createElement('option');
allOpt.value = '__all__';
allOpt.textContent = 'All Members';
countySel.appendChild(allOpt);

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
  return window.location.pathname.includes('/votega.org-TEST/') ? '/votega.org-TEST/' : '/';
}

async function loadData() {
  statusLine.textContent = 'Loading member data…';
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allMembers = data.members || [];
    statusLine.textContent = '';
    if (countySel.value === '__all__') renderAllMembers();
  } catch (err) {
    statusLine.textContent = 'Could not load GA member data: ' + err.message;
  }
}

function renderAllMembers() {
  const basePath = getBasePath();

  function memberRow(m, districtCounties) {
    const abbrev    = partyAbbrev(m.party);
    const partyClass = abbrev === 'D' ? 'party-d' : abbrev === 'R' ? 'party-r' : '';
    const counties  = (districtCounties[m.district] || []).join(', ');
    return `
      <a class="member-row" href="${basePath}ga-member.html?id=${encodeURIComponent(m.id)}">
        <span class="member-district">District ${m.district}</span>
        <span class="member-name">${m.name}${abbrev ? ` <span class="${partyClass}">(${abbrev})</span>` : ''}</span>
        <span class="member-counties">${counties}</span>
        <span class="member-arrow">›</span>
      </a>`;
  }

  const senate = allMembers
    .filter(m => m.chamber === 'Senate')
    .sort((a, b) => (a.district ?? 999) - (b.district ?? 999));

  const house = allMembers
    .filter(m => m.chamber === 'House of Representatives')
    .sort((a, b) => (a.district ?? 999) - (b.district ?? 999));

  allMembersOut.innerHTML = `
    <div class="directory-section">
      <h3>Senate (${senate.length} members)</h3>
      ${senate.map(m => memberRow(m, SENATE_DISTRICT_COUNTIES)).join('')}
    </div>
    <div class="directory-section">
      <h3>House of Representatives (${house.length} members)</h3>
      ${house.map(m => memberRow(m, HOUSE_DISTRICT_COUNTIES)).join('')}
    </div>`;
}

function setLookupVisible(visible) {
  chamberLabel.style.display  = visible ? '' : 'none';
  districtLabel.style.display = visible ? '' : 'none';
  submitBtn.style.display     = visible ? '' : 'none';
  if (!visible) allMembersOut.innerHTML = '';
}

function updateChamber() {
  const county = countySel.value;

  if (county === '__all__') {
    setLookupVisible(false);
    if (allMembers.length) renderAllMembers();
    return;
  }

  setLookupVisible(true);
  allMembersOut.innerHTML = '';
  chamberSel.disabled = !county;
  if (!county) {
    chamberSel.value = '';
    districtSel.innerHTML = '<option value="">— choose district —</option>';
    districtSel.disabled = true;
  } else {
    updateDistricts();
  }
}

function updateDistricts() {
  const county  = countySel.value;
  const chamber = chamberSel.value;

  districtSel.innerHTML = '<option value="">— choose district —</option>';
  districtSel.disabled = true;

  if (!county || !chamber || allMembers.length === 0) return;

  const chamberName = chamber === 'senate' ? 'Senate' : 'House of Representatives';
  let members = allMembers.filter(m => m.chamber === chamberName);

  const lookup = chamber === 'senate' ? COUNTY_SENATE_DISTRICTS : COUNTY_HOUSE_DISTRICTS;
  const countyDistricts = lookup[county] || [];
  members = members.filter(m => countyDistricts.includes(m.district));

  members = members.sort((a, b) => (a.district ?? 999) - (b.district ?? 999));

  members.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    const abbrev = partyAbbrev(m.party);
    opt.textContent = `District ${m.district} — ${m.name}${abbrev ? ` (${abbrev})` : ''}`;
    districtSel.appendChild(opt);
  });

  if (members.length > 0) districtSel.disabled = false;
}

countySel .addEventListener('change', updateChamber);
chamberSel.addEventListener('change', updateDistricts);

form.addEventListener('submit', e => {
  e.preventDefault();
  const id     = districtSel.value;
  const county = countySel.value;
  if (!id) {
    statusLine.textContent = 'Please select a district.';
    return;
  }
  const params = new URLSearchParams({ id, ...(county && { county }) });
  window.location.href = `${getBasePath()}ga-member.html?${params}`;
});

loadData();
