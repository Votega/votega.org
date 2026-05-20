import csv, json, re, os, sys
from collections import OrderedDict

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root  = os.path.dirname(os.path.dirname(script_dir))  # assets/scripts -> assets -> repo root

# Accept the CSV path as an optional argument; default to the most recent
# "Total Votes - *.csv" file in assets/data/
if len(sys.argv) > 1:
    csv_path = sys.argv[1]
else:
    import glob
    data_dir = os.path.join(repo_root, "assets", "data")
    matches = sorted(glob.glob(os.path.join(data_dir, "Total Votes - *.csv")))
    if not matches:
        print(f"ERROR: No 'Total Votes - *.csv' found in {data_dir}")
        sys.exit(1)
    csv_path = matches[-1]  # alphabetical sort puts the latest timestamp last
    print(f"Using CSV: {os.path.basename(csv_path)}")

out_path = os.path.join(repo_root, "ga-primary-results.html")

contests = {}
with open(csv_path, newline='', encoding='utf-8-sig') as f:
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        if len(row) < 6: continue
        office, cid, ballot_name, choice_id, party, total_str = row[0], row[1], row[2], row[3], row[4], row[5]
        try:
            total = int(total_str.strip()) if total_str.strip() else 0
        except:
            total = 0
        if cid not in contests:
            contests[cid] = {'office': office, 'cid': cid, 'party': party, 'totalVotes': 0, 'candidates': []}
        if ballot_name == 'Total Votes':
            contests[cid]['totalVotes'] = total
        elif ballot_name != 'Ballots Cast':
            name = ballot_name
            incumbent = name.endswith('(I)')
            if incumbent:
                name = name[:-4].strip()
            contests[cid]['candidates'].append({'name': name, 'votes': total, 'incumbent': incumbent})
        if party and not contests[cid]['party']:
            contests[cid]['party'] = party

def clean_office(office):
    return re.sub(r'/ .*$', '', office).strip()

def district_num(office):
    m = re.search(r'District (\d+)', office)
    return int(m.group(1)) if m else 999

by_office = OrderedDict()
for cid, c in contests.items():
    key = clean_office(c['office'])
    if key not in by_office:
        by_office[key] = []
    by_office[key].append(c)

statewide_prefixes = ['US Senate', 'Governor', 'Lieutenant Governor', 'Secretary of State',
                      'Attorney General', 'Commissioner of Agriculture', 'Commissioner of Insurance',
                      'State School Superintendent', 'Commissioner of Labor', 'PSC']

court_prefixes = ['Justice -', 'Judge -', 'District Attorney -']

raw = {'statewide': [], 'us-house': [], 'state-senate': [], 'state-house': [], 'courts': []}
for office, cl in by_office.items():
    if any(office.startswith(p) for p in statewide_prefixes):
        raw['statewide'].append((office, cl))
    elif office.startswith('US House'):
        raw['us-house'].append((office, cl))
    elif office.startswith('State Senate') or office.startswith('Special State Senate'):
        raw['state-senate'].append((office, cl))
    elif office.startswith('State House'):
        raw['state-house'].append((office, cl))
    elif any(office.startswith(p) for p in court_prefixes):
        raw['courts'].append((office, cl))

for k in ['us-house', 'state-senate', 'state-house']:
    raw[k].sort(key=lambda x: district_num(x[0]))

# Sort courts: Supreme Court first, then Court of Appeals, then Superior Court by circuit name,
# then District Attorney by circuit name
def court_sort_key(x):
    office = x[0]
    if office.startswith('Justice'):
        return (0, office)
    if office.startswith('Judge - Court of Appeals'):
        return (1, office)
    if office.startswith('Judge - Superior'):
        return (2, office)
    return (3, office)  # District Attorney

raw['courts'].sort(key=court_sort_key)

def group_district_races(pairs):
    races = OrderedDict()
    for office, cl in pairs:
        base = re.sub(r'\s*-\s*(Rep|Dem)$', '', office).strip()
        if base not in races:
            races[base] = {'office': base, 'contests': []}
        for c in cl:
            races[base]['contests'].append(c)
    return list(races.values())

def to_js_contest(c):
    party = c['party'].upper() if c['party'] else ''
    p = 'rep' if party == 'REP' else ('dem' if party == 'DEM' else 'np')
    cands = sorted(c['candidates'], key=lambda x: -x['votes'])
    return {'party': p, 'totalVotes': c['totalVotes'],
            'candidates': [{'name': cd['name'], 'votes': cd['votes'], 'incumbent': cd['incumbent']} for cd in cands]}

def build_section(sid, label, pairs):
    races = group_district_races(pairs)
    return {'id': sid, 'label': label,
            'races': [{'office': r['office'], 'contests': [to_js_contest(c) for c in r['contests']]} for r in races]}

sections_data = [
    build_section('statewide',    'Executive / Statewide',         raw['statewide']),
    build_section('us-house',     'U.S. House',                    raw['us-house']),
    build_section('state-senate', 'GA State Senate',               raw['state-senate']),
    build_section('state-house',  'GA State House',                raw['state-house']),
    build_section('courts',       'Courts',                        raw['courts']),
]

sections_json = json.dumps(sections_data, separators=(',', ':'))

# Jekyll page — layout: default supplies the nav, logo, and footer automatically.
HTML_TEMPLATE = """\
---
layout: default
title: Georgia 2026 Primary Results
---
<style>
  :root {{
    --rep: #c0392b; --rep-light: #fdf0ef; --rep-bar: #e74c3c;
    --dem: #2471a3; --dem-light: #eaf4fb; --dem-bar: #3498db;
    --border: #ddd; --card-bg: #fff;
    --muted: #777; --neutral: #555;
  }}

  /* ── Page header ── */
  .pr-page-header {{ margin-bottom: 1rem; }}
  .pr-page-header h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: .2rem; }}
  .pr-page-header .pr-meta {{ font-size: .82rem; color: #777; }}

  /* ── Tab bar — matches elections.html ── */
  .tab-bar {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin: 1.25rem 0 1rem 0;
    border-bottom: 2px solid #e5e7eb;
    padding-bottom: 0;
  }}
  .tab-btn {{
    padding: 0.45rem 1rem;
    border: none;
    background: none;
    cursor: pointer;
    font-size: 0.88rem;
    font-weight: 500;
    color: #555;
    border-bottom: 3px solid transparent;
    margin-bottom: -2px;
    border-radius: 4px 4px 0 0;
    transition: color 0.15s, border-color 0.15s;
    white-space: nowrap;
  }}
  .tab-btn:hover {{ color: #1a56a8; }}
  .tab-btn.active {{ color: #1a56a8; border-bottom-color: #1a56a8; font-weight: 600; }}

  /* ── Tab panels ── */
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}

  /* ── Filter / search bar ── */
  .pr-filter-bar {{ display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; margin-bottom: .75rem; }}
  .filter-btn {{ border: 1px solid var(--border); background: var(--card-bg); padding: .35rem 1rem; border-radius: 20px; cursor: pointer; font-size: .82rem; font-weight: 500; color: var(--neutral); }}
  .filter-btn.active {{ background: #1a1a2e; color: #fff; border-color: #1a1a2e; }}
  .filter-btn.rep.active {{ background: var(--rep); border-color: var(--rep); }}
  .filter-btn.dem.active {{ background: var(--dem); border-color: var(--dem); }}
  .search-row {{ margin-bottom: 1.25rem; }}
  .search-row input {{ width: 100%; padding: .45rem .9rem; border: 1px solid var(--border); border-radius: 20px; font-size: .85rem; outline: none; }}
  .search-row input:focus {{ border-color: #999; }}

  /* ── Notice ── */
  .pr-notice {{ background: #fff8e1; border: 1px solid #f9a825; border-radius: 6px; padding: .6rem 1rem; font-size: .82rem; color: #5d4037; margin-bottom: 1rem; }}

  /* ── Race cards ── */
  .race-card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; margin-bottom: .6rem; overflow: hidden; }}
  .race-card.rep {{ border-top: 3px solid var(--rep); }}
  .race-card.dem {{ border-top: 3px solid var(--dem); }}
  .race-card.np  {{ border-top: 3px solid #888; }}
  .race-card.runoff-race {{ background: #fff8e1; }}
  .race-card.winner-race {{ background: #f0faf0; }}
  .race-card.no-results  {{ opacity: .6; }}
  .race-header {{ display: flex; align-items: center; justify-content: space-between; padding: .6rem 1rem .35rem; flex-wrap: wrap; gap: .25rem; }}
  .race-title  {{ font-weight: 600; font-size: .92rem; }}
  .race-meta   {{ display: flex; gap: .4rem; align-items: center; flex-shrink: 0; }}
  .party-badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 10px; font-size: .7rem; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; }}
  .party-badge.rep {{ background: var(--rep-light); color: var(--rep); }}
  .party-badge.dem {{ background: var(--dem-light); color: var(--dem); }}
  .party-badge.np  {{ background: #f0f0f0; color: #555; }}
  .status-badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 10px; font-size: .7rem; font-weight: 600; }}
  .status-badge.winner     {{ background: #e8f8e8; color: #1e7e34; }}
  .status-badge.runoff     {{ background: #fff3cd; color: #856404; }}
  .status-badge.uncontested {{ background: #f0f0f0; color: #555; }}
  .status-badge.no-results {{ background: #f0f0f0; color: #aaa; }}
  .race-total  {{ font-size: .72rem; color: var(--muted); padding: 0 1rem .4rem; }}
  .candidates  {{ padding: 0 1rem .65rem; }}
  .cand-block  {{ margin-bottom: .5rem; }}
  .cand-top-line {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: .18rem; }}
  .cand-name   {{ font-size: .84rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 62%; }}
  .cand-name .inc {{ font-size: .68rem; color: var(--muted); margin-left: .2rem; }}
  .cand-name .wi  {{ color: #27ae60; margin-right: .1rem; }}
  .cand-votes  {{ font-size: .76rem; color: var(--muted); }}
  .cand-pct    {{ font-size: .84rem; font-weight: 600; min-width: 3rem; text-align: right; }}
  .bar-track   {{ height: 7px; background: #eee; border-radius: 4px; overflow: hidden; position: relative; }}
  .bar-track::after {{ content: ''; position: absolute; left: 50%; top: 0; height: 100%; width: 2px; background: rgba(0,0,0,.18); }}
  .bar-fill    {{ height: 100%; border-radius: 4px; }}
  .bar-fill.rep {{ background: var(--rep-bar); }}
  .bar-fill.dem {{ background: var(--dem-bar); }}
  .bar-fill.np  {{ background: #888; }}
  .bar-fill.trail {{ opacity: .42; }}
</style>

<div class="pr-page-header">
  <h1>Georgia 2026 Primary Results</h1>
  <div class="pr-meta">Tuesday, May 19, 2026 &nbsp;&middot;&nbsp; Last updated: 10:00 PM ET &nbsp;&middot;&nbsp; Preliminary</div>
</div>
<div class="pr-notice">&#9888; Preliminary election night results &mdash; unofficial until certified. Georgia law requires a runoff if no candidate receives more than 50% of the vote.</div>

<div class="tab-bar" id="tabBar">
  <button class="tab-btn active" data-tab="statewide">Executive / Statewide</button>
  <button class="tab-btn" data-tab="us-house">U.S. House</button>
  <button class="tab-btn" data-tab="state-senate">GA State Senate</button>
  <button class="tab-btn" data-tab="state-house">GA State House</button>
  <button class="tab-btn" data-tab="courts">Courts</button>
</div>

<div class="pr-filter-bar">
  <button class="filter-btn active" data-filter="all">All Races</button>
  <button class="filter-btn rep" data-filter="rep">&#x25A0; Republican</button>
  <button class="filter-btn dem" data-filter="dem">&#x25A0; Democrat</button>
</div>
<div class="search-row"><input type="text" id="searchBox" placeholder="Search candidates or races…" /></div>

<div id="tab-statewide"    class="tab-panel active"></div>
<div id="tab-us-house"     class="tab-panel"></div>
<div id="tab-state-senate" class="tab-panel"></div>
<div id="tab-state-house"  class="tab-panel"></div>
<div id="tab-courts"       class="tab-panel"></div>

<script>
const SECTIONS={sections_json};

function fmt(n){{return n.toLocaleString();}}
function pct(v,t){{return t?((v/t)*100):0;}}

function getStatus(c){{
  if(!c.candidates||c.candidates.length===0||c.totalVotes===0)return 'no-results';
  if(c.candidates.length===1)return 'uncontested';
  return pct(c.candidates[0].votes,c.totalVotes)>50?'winner':'runoff';
}}

const STATUS_MAP={{
  winner:      {{cls:'winner',     text:'Leads >50%'}},
  runoff:      {{cls:'runoff',     text:'Runoff Likely'}},
  uncontested: {{cls:'uncontested',text:'Uncontested'}},
  'no-results':{{cls:'no-results', text:'Awaiting Results'}},
}};

function partyLabel(p){{
  return p==='rep'?'Republican':p==='dem'?'Democrat':'Nonpartisan';
}}

function renderContest(c,office){{
  const status=getStatus(c);
  const sl=STATUS_MAP[status];
  const p=c.party||'np';
  const noRes=c.totalVotes===0;
  const cardCls=status==='runoff'?'runoff-race':status==='winner'?'winner-race':status==='no-results'?'no-results':'';
  const pctColor=p==='rep'?'var(--rep)':p==='dem'?'var(--dem)':'#555';
  const candsHtml=(c.candidates||[]).map((cd,i)=>{{
    const pp=pct(cd.votes,c.totalVotes);
    const wi=i===0&&status==='winner'?'<span class="wi">&#10003;</span>':'';
    const inc=cd.incumbent?'<span class="inc">(I)</span>':'';
    return `<div class="cand-block">
      <div class="cand-top-line">
        <span class="cand-name">${{wi}}${{cd.name}}${{inc}}</span>
        <span style="display:flex;gap:.5rem;align-items:center">
          ${{noRes?'':`<span class="cand-votes">${{fmt(cd.votes)}}</span>`}}
          <span class="cand-pct" style="color:${{noRes?'#bbb':pctColor}}">${{noRes?'&mdash;':pp.toFixed(1)+'%'}}</span>
        </span>
      </div>
      <div class="bar-track"><div class="bar-fill ${{p}}${{i>0?' trail':''}}" style="width:${{noRes?0:Math.min(pp,100)}}%"></div></div>
    </div>`;
  }}).join('');
  const totalLine=noRes
    ?'<div class="race-total" style="color:#bbb">No results reported</div>'
    :`<div class="race-total">${{fmt(c.totalVotes)}} total votes</div>`;
  return `<div class="race-card ${{p}} ${{cardCls}}" data-party="${{p}}" data-office="${{office.toLowerCase()}}" data-cands="${{(c.candidates||[]).map(x=>x.name.toLowerCase()).join(' ')}}">
    <div class="race-header">
      <span class="race-title">${{office}}</span>
      <div class="race-meta">
        <span class="party-badge ${{p}}">${{partyLabel(p)}}</span>
        <span class="status-badge ${{sl.cls}}">${{sl.text}}</span>
      </div>
    </div>
    ${{totalLine}}
    <div class="candidates">${{candsHtml}}</div>
  </div>`;
}}

// Render all sections into their tab panels
SECTIONS.forEach(s=>{{
  const panel=document.getElementById('tab-'+s.id);
  if(!panel)return;
  panel.innerHTML=s.races.map(r=>
    r.contests.length===1
      ?renderContest(r.contests[0],r.office)
      :r.contests.map(c=>renderContest(c,r.office)).join('')
  ).join('');
}});

let curFilter='all';

function applyFilter(f){{
  curFilter=f;
  const q=(document.getElementById('searchBox').value||'').toLowerCase().trim();
  const activePanel=document.querySelector('.tab-panel.active');
  if(!activePanel)return;
  activePanel.querySelectorAll('.race-card').forEach(card=>{{
    const matchParty=f==='all'||card.dataset.party===f;
    const matchSearch=!q||(card.dataset.office||'').includes(q)||(card.dataset.cands||'').includes(q);
    card.style.display=(matchParty&&matchSearch)?'':'none';
  }});
}}

// Tab switching
document.getElementById('tabBar').addEventListener('click',e=>{{
  const btn=e.target.closest('.tab-btn');
  if(!btn)return;
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-'+btn.dataset.tab).classList.add('active');
  applyFilter(curFilter);
}});

// Party filter buttons
document.querySelectorAll('.filter-btn').forEach(btn=>{{
  btn.addEventListener('click',()=>{{
    document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    applyFilter(btn.dataset.filter);
  }});
}});

document.getElementById('searchBox').addEventListener('input',()=>applyFilter(curFilter));

applyFilter('all');
</script>"""

html = HTML_TEMPLATE.format(sections_json=sections_json)

with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Written: {out_path}")
print(f"File size: {os.path.getsize(out_path):,} bytes")
for s in sections_data:
    print(f"  {s['id']}: {len(s['races'])} races")
