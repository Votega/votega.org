// ---------- CONFIG -------------------------------------------------
const DATA_URL  = 'assets/data/current-members.json';
// The member list is prebuilt by GitHub Actions and served as static JSON.
// -------------------------------------------------------------------

function formatMemberName(m) {
  const honorific = m.honorificName || '';
  const firstName = m.firstName || '';
  const lastName = m.lastName || '';
  const fallback = m.directOrderName || m.name || 'Unknown';
  return (firstName && lastName)
    ? `${honorific} ${firstName} ${lastName}`.trim()
    : (honorific ? `${honorific} ${fallback}` : fallback);
}

const STATES = [
  {code:'AL',name:'Alabama'},{code:'AK',name:'Alaska'},{code:'AZ',name:'Arizona'},
  {code:'AR',name:'Arkansas'},{code:'CA',name:'California'},{code:'CO',name:'Colorado'},
  {code:'CT',name:'Connecticut'},{code:'DE',name:'Delaware'},{code:'FL',name:'Florida'},
  {code:'GA',name:'Georgia'},{code:'HI',name:'Hawaii'},{code:'ID',name:'Idaho'},
  {code:'IL',name:'Illinois'},{code:'IN',name:'Indiana'},{code:'IA',name:'Iowa'},
  {code:'KS',name:'Kansas'},{code:'KY',name:'Kentucky'},{code:'LA',name:'Louisiana'},
  {code:'ME',name:'Maine'},{code:'MD',name:'Maryland'},{code:'MA',name:'Massachusetts'},
  {code:'MI',name:'Michigan'},{code:'MN',name:'Minnesota'},{code:'MS',name:'Mississippi'},
  {code:'MO',name:'Missouri'},{code:'MT',name:'Montana'},{code:'NE',name:'Nebraska'},
  {code:'NV',name:'Nevada'},{code:'NH',name:'New Hampshire'},{code:'NJ',name:'New Jersey'},
  {code:'NM',name:'New Mexico'},{code:'NY',name:'New York'},{code:'NC',name:'North Carolina'},
  {code:'ND',name:'North Dakota'},{code:'OH',name:'Ohio'},{code:'OK',name:'Oklahoma'},
  {code:'OR',name:'Oregon'},{code:'PA',name:'Pennsylvania'},{code:'RI',name:'Rhode Island'},
  {code:'SC',name:'South Carolina'},{code:'SD',name:'South Dakota'},{code:'TN',name:'Tennessee'},
  {code:'TX',name:'Texas'},{code:'UT',name:'Utah'},{code:'VT',name:'Vermont'},
  {code:'VA',name:'Virginia'},{code:'WA',name:'Washington'},{code:'WV',name:'West Virginia'},
  {code:'WI',name:'Wisconsin'},{code:'WY',name:'Wyoming'}
];

const stateSel    = document.getElementById('stateSelect');
const chamberSel  = document.getElementById('chamberSelect');
const memberSel   = document.getElementById('memberSelect');
const statusLine  = document.getElementById('status');
const form        = document.getElementById('lookupForm');

// populate state dropdown once, defaulting to Georgia
STATES.forEach(s => {
  const opt=document.createElement('option');
  opt.value=s.code;
  opt.textContent=s.name;
  stateSel.appendChild(opt);
});
stateSel.value = 'GA';

chamberSel.addEventListener('change', loadMembers);
stateSel  .addEventListener('change', loadMembers);

// Load members

async function loadMembers () {
  const state   = stateSel.value;
  const chamber = chamberSel.value;

  console.log('loadMembers called', {state, chamber});
  
  memberSel.disabled = true;
  memberSel.innerHTML = '';
  if (!state || !chamber) {
    console.log('Missing state or chamber, returning');
    return;
  }

  statusLine.textContent = 'Loading legislators…';
  try {
    const res  = await fetch(DATA_URL);
    if (!res.ok) {
      console.error(`HTTP error: ${res.status}`);
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();
    let results = data.members || [];
    console.log(`Got ${results.length} prebuilt members`);

    if (results.length === 0) {
      throw new Error('No prebuilt member data found. Run the GitHub Actions workflow to generate assets/data/current-members.json.');
    }
    
    // Filter by state name and chamber since API returns all members regardless of chamber filter
    const stateName = STATES.find(s => s.code === state)?.name;
    const chamberMap = { 'house': 'House of Representatives', 'senate': 'Senate' };
    const expectedChamber = chamberMap[chamber];
    
    console.log(`Filtering for state="${stateName}" chamber="${expectedChamber}". Total results: ${results.length}`);
    
    results = results.filter(m => {
      if (!m || typeof m !== 'object') {
        console.log('Filtered out: not an object');
        return false;
      }
      if (m.state !== stateName) {
        console.log(`Filtered out "${m.name}": state="${m.state}" (want "${stateName}")`);
        return false;
      }
      if (!m.name) {
        console.log('Filtered out: no name');
        return false;
      }
      // Check if the member has terms and if any term matches the requested chamber
      const terms = m.terms?.item || m.terms || [];
      if (!Array.isArray(terms)) {
        console.log(`"${m.name}": terms is not an array:`, terms);
        return false;
      }
      // Check if any term is for the requested chamber
      const hasMatchingChamber = terms.some(t => t.chamber === expectedChamber);
      if (!hasMatchingChamber) {
        console.log(`Filtered out "${m.name}": chambers=${terms.map(t => t.chamber).join('/')} (want "${expectedChamber}")`);
        return false;
      }
      return true;
    });
    
    console.log(`After filtering: ${results.length} members`);

    if (results.length === 0) {
      throw new Error(`No members returned for ${stateName} ${expectedChamber} – check API data.`);
    }

    let optionsHtml;
    if (expectedChamber === 'House of Representatives') {
      // Group by district to detect vacancies
      const districtMap = new Map();
      results.forEach(m => {
        const dist = m.district ?? 'At-Large';
        if (!districtMap.has(dist)) districtMap.set(dist, []);
        districtMap.get(dist).push(m);
      });

      optionsHtml = [...districtMap.entries()]
        .sort(([a], [b]) => {
          if (a === 'At-Large') return 1;
          if (b === 'At-Large') return -1;
          return Number(a) - Number(b);
        })
        .map(([district, members]) => {
          const current = members.find(m => m.currentMember !== false);
          if (current) {
            return `<option value="${current.bioguideId}">District ${district} - ${formatMemberName(current)} (${current.partyName})</option>`;
          }
          return `<option value="" disabled>District ${district} - Vacant</option>`;
        }).join('');
    } else {
      // Senate: only show current members, sorted alphabetically
      optionsHtml = results
        .filter(m => m.currentMember !== false)
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(m => `<option value="${m.bioguideId}">${formatMemberName(m)} (${m.partyName})</option>`)
        .join('');
    }

    memberSel.innerHTML = '<option value="">— choose —</option>' + optionsHtml;
    memberSel.disabled = false;
    statusLine.textContent = '';

  } catch (err) {
    console.error('loadMembers()', err);
    statusLine.textContent = err.message.includes('HTTP') ?
      'API error: ' + err.message :
      'Could not load data. Check the console.';
  }
}
// My-Representatives.html form submission. Fetches and displays details for the selected member.
form.addEventListener('submit',e=>{
  e.preventDefault();
  const bioguideId = memberSel.value;
  if (!bioguideId) {
    statusLine.textContent = 'Please select a member.';
    return;
  }
  // Redirect to the member details page
  // Get the base path (handles both votega.github.io/votega.org-TEST/ and votega.github.io/)
  const pathname = window.location.pathname;
  const basePath = pathname.includes('/votega.org-TEST/') 
    ? '/votega.org-TEST/' 
    : '/';
  window.location.href = `${basePath}member.html?bioguideId=${bioguideId}`;
});

