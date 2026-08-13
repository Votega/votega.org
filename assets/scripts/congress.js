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

const stateSel    = document.getElementById('stateSelect');
const chamberSel  = document.getElementById('chamberSelect');
const memberSel   = document.getElementById('memberSelect');
const statusLine  = document.getElementById('status');
const form        = document.getElementById('lookupForm');

// Populated per chamber load. Keyed by the vacant `<option value>` so the
// notice only appears once the user actually picks that district, not for
// every vacancy in the chamber up front.
const vacancyMessages = new Map();

// Georgia-only — site scope is limited to GA federal delegation
stateSel.innerHTML = '<option value="GA">Georgia</option>';

chamberSel.addEventListener('change', loadMembers);
stateSel  .addEventListener('change', loadMembers);
memberSel .addEventListener('change', () => {
  statusLine.innerHTML = vacancyMessages.get(memberSel.value) || '';
});

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
      console.error('current-members.json contained no members — run the update-current-members workflow.');
      throw new Error('Legislator data is temporarily unavailable. Please try again later.');
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
      // Check the member's most recent term only — a member who switched chambers
      // (e.g. House then Senate) should only match their current chamber.
      const latestTerm = terms[terms.length - 1] || {};
      const hasMatchingChamber = latestTerm.chamber === expectedChamber;
      if (!hasMatchingChamber) {
        console.log(`Filtered out "${m.name}": chambers=${terms.map(t => t.chamber).join('/')} (want "${expectedChamber}")`);
        return false;
      }
      return true;
    });
    
    console.log(`After filtering: ${results.length} members`);

    if (results.length === 0) {
      console.error(`No members matched ${stateName} ${expectedChamber} in current-members.json.`);
      throw new Error('Legislator data is temporarily unavailable. Please try again later.');
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

      // A seat vacated by death, resignation, or expulsion has no member in
      // current-members.json at all, so grouping the member list alone would silently
      // drop the district. Take the seat list from the county→district map when it is
      // loaded, and otherwise infer it as 1..highest-seen, so a vacancy shows up as a
      // vacancy rather than disappearing.
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

      const ordered = [...seats].sort((a, b) => a - b);
      if (districtMap.has('At-Large')) ordered.push('At-Large');

      vacancyMessages.clear();
      optionsHtml = ordered
        .map(district => {
          const members = districtMap.get(district) || districtMap.get(String(district)) || [];
          const current = members.find(m => m.currentMember !== false);
          if (current) {
            return `<option value="${current.bioguideId}">District ${district} - ${formatMemberName(current)} (${current.partyName})</option>`;
          }
          // Selectable rather than disabled, so choosing it is what reveals
          // the explanation instead of it appearing for every vacancy up front.
          const value = `vacant-${district}`;
          vacancyMessages.set(value, district === 13
            ? `District 13 is vacant following Rep. David Scott's death. See the <a href="${getBasePath()}ga-special-2026-runoff-results/">2026 special election runoff results</a>.`
            : `District ${district} is currently vacant.`);
          return `<option value="${value}">District ${district} - Vacant (no sitting representative)</option>`;
        }).join('');
    } else {
      // Senate: only show current members, sorted alphabetically
      vacancyMessages.clear();
      optionsHtml = results
        .filter(m => m.currentMember !== false)
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(m => `<option value="${m.bioguideId}">${formatMemberName(m)} (${m.partyName})</option>`)
        .join('');
    }

    memberSel.innerHTML = '<option value="">— choose —</option>' + optionsHtml;
    memberSel.disabled = false;
    statusLine.innerHTML = '';

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
  if (vacancyMessages.has(bioguideId)) {
    // No member page to send them to — the notice is already showing.
    return;
  }
  // Redirect to the member details page
  window.location.href = `${getBasePath()}member.html?bioguideId=${bioguideId}`;
});

