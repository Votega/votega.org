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

let allMembers = [];
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
  return window.location.pathname.includes('/votega.org-TEST/') ? '/votega.org-TEST/' : '/';
}

function drawPartyChart(members) {
  const canvas = document.getElementById('partyChart');
  const legend = document.getElementById('chartLegend');
  if (!canvas || !legend) return;

  const d = members.filter(m => partyAbbrev(m.party) === 'D').length;
  const r = members.filter(m => partyAbbrev(m.party) === 'R').length;
  const o = members.length - d - r;
  const total = members.length;

  const ctx    = canvas.getContext('2d');
  const cx     = canvas.width / 2;
  const cy     = canvas.height / 2;
  const radius = Math.min(cx, cy) - 4;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!total) { legend.innerHTML = ''; return; }

  const segments = [
    { count: d, color: '#2563eb', label: 'Democrat' },
    { count: r, color: '#dc2626', label: 'Republican' },
    { count: o, color: '#9ca3af', label: 'Other' },
  ].filter(s => s.count > 0);

  let startAngle = -Math.PI / 2;
  for (const seg of segments) {
    const sweep = (seg.count / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, startAngle, startAngle + sweep);
    ctx.closePath();
    ctx.fillStyle = seg.color;
    ctx.fill();
    startAngle += sweep;
  }

  // Centre hole for donut effect
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.52, 0, 2 * Math.PI);
  ctx.fillStyle = '#fff';
  ctx.fill();

  // Total count in centre
  ctx.fillStyle = '#374151';
  ctx.font = `bold ${Math.round(radius * 0.38)}px system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(total, cx, cy);

  legend.innerHTML = segments.map(s =>
    `<span><span class="legend-dot" style="background:${s.color}"></span>${s.label} ${Math.round(s.count / total * 100)}%</span>`
  ).join('');
}

function renderMembers() {
  const county = countySel.value;
  const chamberName      = activeTab === 'senate' ? 'Senate' : 'House of Representatives';
  const districtCounties = activeTab === 'senate' ? SENATE_DISTRICT_COUNTIES : HOUSE_DISTRICT_COUNTIES;
  const countyLookup     = activeTab === 'senate' ? COUNTY_SENATE_DISTRICTS  : COUNTY_HOUSE_DISTRICTS;
  const basePath         = getBasePath();

  let members = allMembers.filter(m => m.chamber === chamberName);

  if (county) {
    const countyDists = countyLookup[county] || [];
    members = members.filter(m => countyDists.includes(m.district));
  }

  members.sort((a, b) => (a.district ?? 999) - (b.district ?? 999));

  drawPartyChart(members);

  if (!members.length) {
    membersOut.innerHTML = `<p class="empty-note">No members found${county ? ` for ${county} County` : ''}.</p>`;
    return;
  }

  membersOut.innerHTML = members.map(m => {
    const isVacant = m.status === 'Vacant';
    const abbrev = partyAbbrev(m.party);
    const pClass = abbrev === 'D' ? 'party-d' : abbrev === 'R' ? 'party-r' : '';
    const counties = (districtCounties[m.district] || []).join(', ');
    const nameHtml = isVacant
      ? `<span style="color:#888;font-style:italic;">Vacant</span>`
      : `${m.name}${abbrev ? ` <span class="${pClass}">(${abbrev})</span>` : ''}`;
    return `<a class="member-row" href="${basePath}ga-member.html?id=${encodeURIComponent(m.id)}">
      <span class="member-district">District ${m.district}</span>
      <span class="member-name">${nameHtml}</span>
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

countySel.addEventListener('change', renderMembers);

async function loadData() {
  statusLine.textContent = 'Loading member data…';
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allMembers = data.members || [];
    statusLine.textContent = '';
    renderMembers();
  } catch (err) {
    statusLine.textContent = 'Could not load GA member data: ' + err.message;
  }
}

loadData();