// ---------- CONFIG -------------------------------------------------
const DATA_URL = 'assets/data/ga-members.json';
// -------------------------------------------------------------------

// County → House district numbers
// Source: GA General Assembly Office of Legislative & Congressional Reapportionment (2021)
const COUNTY_HOUSE_DISTRICTS = {
  'Appling':       [157, 178],
  'Atkinson':      [176],
  'Bacon':         [178],
  'Baker':         [154],
  'Baldwin':       [128, 133],
  'Banks':         [32],
  'Barrow':        [104, 119, 120],
  'Bartow':        [14, 15],
  'Ben Hill':      [148, 156],
  'Berrien':       [170],
  'Bibb':          [142, 143, 144, 145],
  'Bleckley':      [149],
  'Brantley':      [174],
  'Brooks':        [175],
  'Bryan':         [160, 164, 166],
  'Bulloch':       [158, 159, 160],
  'Burke':         [126],
  'Butts':         [118],
  'Calhoun':       [154],
  'Camden':        [180],
  'Candler':       [158],
  'Carroll':       [18, 70, 71, 72],
  'Catoosa':       [2, 3],
  'Charlton':      [174],
  'Chatham':       [161, 162, 163, 164, 165, 166],
  'Chattahoochee': [151],
  'Chattooga':     [12],
  'Cherokee':      [11, 14, 20, 21, 22, 23, 44, 46, 47],
  'Clarke':        [120, 121, 122, 124],
  'Clay':          [154],
  'Clayton':       [75, 76, 77, 78, 79, 116],
  'Clinch':        [174],
  'Cobb':          [22, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46],
  'Coffee':        [169, 176],
  'Colquitt':      [172],
  'Columbia':      [123, 125, 127, 131],
  'Cook':          [170, 172],
  'Coweta':        [65, 67, 70, 73, 136],
  'Crawford':      [145],
  'Crisp':         [148],
  'Dade':          [1],
  'Dawson':        [7, 9],
  'Decatur':       [171],
  'DeKalb':        [52, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95],
  'Dodge':         [149],
  'Dooly':         [150],
  'Dougherty':     [151, 152, 153, 154],
  'Douglas':       [61, 64, 65, 66],
  'Early':         [154],
  'Echols':        [174],
  'Effingham':     [159, 161],
  'Elbert':        [123],
  'Emanuel':       [158],
  'Evans':         [157],
  'Fannin':        [7],
  'Fayette':       [68, 69, 73, 74],
  'Floyd':         [5, 12, 13],
  'Forsyth':       [11, 24, 25, 26, 28, 100],
  'Franklin':      [33],
  'Fulton':        [25, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 65, 67, 68, 69],
  'Gilmer':        [7],
  'Glascock':      [128],
  'Glynn':         [167, 179, 180],
  'Gordon':        [5, 6],
  'Grady':         [171, 173],
  'Greene':        [124],
  'Gwinnett':      [30, 48, 88, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111],
  'Habersham':     [10, 32],
  'Hall':          [27, 28, 29, 30, 31, 100, 103],
  'Hancock':       [128],
  'Haralson':      [18],
  'Harris':        [138, 139],
  'Hart':          [33],
  'Heard':         [72],
  'Henry':         [74, 78, 91, 115, 116, 117, 118],
  'Houston':       [145, 146, 147, 148],
  'Irwin':         [169],
  'Jackson':       [31, 32, 119, 120],
  'Jasper':        [114, 118],
  'Jeff Davis':    [157],
  'Jefferson':     [132],
  'Jenkins':       [126],
  'Johnson':       [155],
  'Jones':         [133, 144],
  'Lamar':         [134, 135],
  'Lanier':        [176],
  'Laurens':       [155],
  'Lee':           [152],
  'Liberty':       [167, 168],
  'Lincoln':       [123],
  'Long':          [167],
  'Lowndes':       [174, 175, 176, 177],
  'Lumpkin':       [9, 27],
  'Macon':         [150],
  'Madison':       [33, 123],
  'Marion':        [151],
  'McDuffie':      [125, 128],
  'McIntosh':      [167],
  'Meriwether':    [136, 137],
  'Miller':        [154],
  'Mitchell':      [171],
  'Monroe':        [134, 144, 145],
  'Montgomery':    [156],
  'Morgan':        [114],
  'Murray':        [6],
  'Muscogee':      [137, 138, 139, 140, 141],
  'Newton':        [93, 113, 114],
  'Oconee':        [120, 121],
  'Oglethorpe':    [124],
  'Paulding':      [16, 17, 18, 19, 64],
  'Peach':         [145, 150],
  'Pickens':       [11],
  'Pierce':        [178],
  'Pike':          [135],
  'Polk':          [16],
  'Pulaski':       [148],
  'Putnam':        [118, 124],
  'Quitman':       [154],
  'Rabun':         [10],
  'Randolph':      [154],
  'Richmond':      [126, 127, 129, 130, 132],
  'Rockdale':      [91, 92, 93, 95],
  'Schley':        [151],
  'Screven':       [159],
  'Seminole':      [154],
  'Spalding':      [74, 117, 134],
  'Stephens':      [32],
  'Stewart':       [151],
  'Sumter':        [150, 151],
  'Talbot':        [137],
  'Taliaferro':    [124],
  'Tattnall':      [156, 157],
  'Taylor':        [150],
  'Telfair':       [149, 156],
  'Terrell':       [151],
  'Thomas':        [172, 173],
  'Tift':          [169, 170],
  'Toombs':        [156],
  'Towns':         [8],
  'Treutlen':      [158],
  'Troup':         [72, 136, 137, 138],
  'Turner':        [169],
  'Twiggs':        [149],
  'Union':         [8],
  'Upson':         [135],
  'Walker':        [1, 2],
  'Walton':        [111, 112],
  'Ware':          [174, 176],
  'Warren':        [128],
  'Washington':    [128],
  'Wayne':         [167, 178],
  'Webster':       [151],
  'Wheeler':       [156],
  'White':         [8, 9],
  'Whitfield':     [2, 4, 6],
  'Wilcox':        [148],
  'Wilkes':        [123],
  'Wilkinson':     [149],
  'Worth':         [152],
};

// County → Senate district numbers
// Source: GA General Assembly Office of Legislative & Congressional Reapportionment (2021)
const COUNTY_SENATE_DISTRICTS = {
  'Appling':       [19],
  'Atkinson':      [8],
  'Bacon':         [19],
  'Baker':         [12],
  'Baldwin':       [25],
  'Banks':         [50],
  'Barrow':        [45, 46, 47],
  'Bartow':        [37, 52],
  'Ben Hill':      [13],
  'Berrien':       [13],
  'Bibb':          [18, 25, 26],
  'Bleckley':      [20],
  'Brantley':      [3],
  'Brooks':        [11],
  'Bryan':         [1],
  'Bulloch':       [4],
  'Burke':         [23],
  'Butts':         [25],
  'Calhoun':       [12],
  'Camden':        [3],
  'Candler':       [4],
  'Carroll':       [30],
  'Catoosa':       [53],
  'Charlton':      [3],
  'Chatham':       [1, 2, 4],
  'Chattahoochee': [15],
  'Chattooga':     [53],
  'Cherokee':      [21, 32, 56],
  'Clarke':        [46, 47],
  'Clay':          [12],
  'Clayton':       [34, 44],
  'Clinch':        [8],
  'Cobb':          [6, 32, 33, 37, 38, 56],
  'Coffee':        [13, 19],
  'Colquitt':      [11],
  'Columbia':      [23, 24],
  'Cook':          [11],
  'Coweta':        [28],
  'Crawford':      [18],
  'Crisp':         [13],
  'Dade':          [53],
  'Dawson':        [51],
  'Decatur':       [11],
  'DeKalb':        [10, 40, 41, 42, 43, 44, 55],
  'Dodge':         [20],
  'Dooly':         [20],
  'Dougherty':     [12],
  'Douglas':       [28, 30, 35],
  'Early':         [12],
  'Echols':        [8],
  'Effingham':     [4],
  'Elbert':        [24],
  'Emanuel':       [23],
  'Evans':         [4],
  'Fannin':        [51],
  'Fayette':       [16, 34],
  'Floyd':         [52, 53],
  'Forsyth':       [27, 48],
  'Franklin':      [50],
  'Fulton':        [6, 14, 21, 28, 35, 36, 38, 39, 48, 56],
  'Gilmer':        [51],
  'Glascock':      [23],
  'Glynn':         [3],
  'Gordon':        [52, 54],
  'Grady':         [11],
  'Greene':        [24],
  'Gwinnett':      [5, 7, 9, 40, 41, 45, 46, 48, 55],
  'Habersham':     [50],
  'Hall':          [49, 50],
  'Hancock':       [26],
  'Haralson':      [30],
  'Harris':        [29],
  'Hart':          [24],
  'Heard':         [28],
  'Henry':         [10, 17, 25],
  'Houston':       [18, 20, 26],
  'Irwin':         [13],
  'Jackson':       [47, 50],
  'Jasper':        [25],
  'Jeff Davis':    [19],
  'Jefferson':     [23],
  'Jenkins':       [23],
  'Johnson':       [26],
  'Jones':         [25],
  'Lamar':         [16],
  'Lanier':        [8],
  'Laurens':       [20],
  'Lee':           [13],
  'Liberty':       [1],
  'Lincoln':       [24],
  'Long':          [19],
  'Lowndes':       [8],
  'Lumpkin':       [51],
  'Macon':         [15],
  'Madison':       [47],
  'Marion':        [15],
  'McDuffie':      [23],
  'McIntosh':      [3],
  'Meriwether':    [29],
  'Miller':        [12],
  'Mitchell':      [12],
  'Monroe':        [18],
  'Montgomery':    [19],
  'Morgan':        [17],
  'Murray':        [54],
  'Muscogee':      [15, 29],
  'Newton':        [17, 43],
  'Oconee':        [46],
  'Oglethorpe':    [24],
  'Paulding':      [30, 31],
  'Peach':         [18],
  'Pickens':       [51],
  'Pierce':        [8],
  'Pike':          [16],
  'Polk':          [31],
  'Pulaski':       [20],
  'Putnam':        [25],
  'Quitman':       [12],
  'Rabun':         [50],
  'Randolph':      [12],
  'Richmond':      [22, 23],
  'Rockdale':      [43],
  'Schley':        [15],
  'Screven':       [23],
  'Seminole':      [11],
  'Spalding':      [16],
  'Stephens':      [50],
  'Stewart':       [12],
  'Sumter':        [12],
  'Talbot':        [15],
  'Taliaferro':    [23],
  'Tattnall':      [19],
  'Taylor':        [15],
  'Telfair':       [19],
  'Terrell':       [12],
  'Thomas':        [11],
  'Tift':          [13],
  'Toombs':        [19],
  'Towns':         [50],
  'Treutlen':      [20],
  'Troup':         [29],
  'Turner':        [13],
  'Twiggs':        [26],
  'Union':         [51],
  'Upson':         [18],
  'Walker':        [53],
  'Walton':        [17, 46],
  'Ware':          [3, 8],
  'Warren':        [23],
  'Washington':    [26],
  'Wayne':         [19],
  'Webster':       [12],
  'Wheeler':       [19],
  'White':         [50, 51],
  'Whitfield':     [54],
  'Wilcox':        [20],
  'Wilkes':        [24],
  'Wilkinson':     [26],
  'Worth':         [13],
};

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
