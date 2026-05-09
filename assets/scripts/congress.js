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

const stateSel    = document.getElementById('stateSelect');
const chamberSel  = document.getElementById('chamberSelect');
const memberSel   = document.getElementById('memberSelect');
const statusLine  = document.getElementById('status');
const form        = document.getElementById('lookupForm');

// Georgia-only — site scope is limited to GA federal delegation
stateSel.innerHTML = '<option value="GA">Georgia</option>';

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
    const stateName = 'Georgia'; // site is GA-only
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

