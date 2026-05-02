# Agent Instructions for votega.org-TEST Project

## Scope
These instructions apply only to the votega.org-TEST project (a static GitHub Pages site using Congress.gov API data). They do not affect other projects or general coding tasks.

## Project Overview
VoteGA.org is a static GitHub Pages Jekyll site for Georgia voter information. It displays federal and state legislators, election info, and civic topics.

**Tech Stack:** Jekyll (Beautiful Jekyll theme) · Congress.gov API · GitHub Actions · Python · JavaScript

**Data Flow:**
```
Congress.gov API → GitHub Actions → Python script → assets/data/*.json → JS lookup → HTML pages
```

## Project Structure

```
votega.org-TEST/
├── _config.yml                          # Jekyll + Beautiful Jekyll theme config
├── claude.md                            # This file
├── README.md / CHANGELOG.md / LICENSE
├── Gemfile / Gemfile.lock               # Ruby dependencies
│
├── 📄 Pages (HTML/Markdown)
│   ├── index.html                       # Homepage (layout: home)
│   ├── about.md
│   ├── 404.html
│   ├── tags.html
│   ├── my-representatives.html          # Federal legislator lookup
│   ├── member.html                      # Federal legislator detail
│   ├── ga-representatives.html          # Georgia state legislator lookup
│   ├── ga-member.html                   # Georgia legislator detail
│   ├── flock-safety.md                  # Flock Safety surveillance info
│   └── flock-covington.md               # Covington PD/Flock Safety contract
│
├── _layouts/                            # Jekyll page templates (base, default, home, page, post, minimal)
├── _includes/                           # Reusable components (header, footer, nav, analytics, comments, search)
├── _posts/                              # Blog posts (YYYY-MM-DD-title.md)
├── _data/
│   └── ui-text.yml                      # UI text / localization
│
├── assets/
│   ├── data/                            # Generated JSON data (committed via GitHub Actions)
│   │   ├── current-members.json         # Federal Congress members (daily, from Congress.gov API)
│   │   ├── ga-members.json              # Georgia state legislators
│   │   └── searchcorpus.json            # Site search index
│   ├── scripts/                         # Client-side + data-gen scripts
│   │   ├── congress.js                  # Federal lookup: reads current-members.json, filters by state/chamber
│   │   ├── ga.js                        # GA lookup: county→district mapping, reads ga-members.json
│   │   ├── generate_current_members_data.py   # (also in scripts/ root — prefer root version)
│   │   ├── dynamic_get_sessions.py      # Georgia API: get legislative sessions
│   │   ├── ga_legis.py                  # Georgia legislator data processing
│   │   ├── ga_demo.py                   # Georgia demo data
│   │   ├── session_id.py                # Session ID utility
│   │   └── service_availability.py      # Service availability check
│   ├── css/                             # Theme stylesheets (beautifuljekyll.css, bootstrap-social.css, etc.)
│   ├── js/                              # Theme JS (beautifuljekyll.js, staticman.js)
│   ├── img/                             # Images (logo.png, avatar-icon.png, bgimage.png, etc.)
│   └── docs/                            # PDFs (flock_safety_covington_pd_contract.pdf)
│
├── scripts/                             # Build-time data generation (run by GitHub Actions)
│   ├── generate_current_members_data.py # Fetches federal data from Congress.gov → assets/data/current-members.json
│   └── generate_ga_members_data.py      # Generates GA legislator data → assets/data/ga-members.json
│
├── .github/workflows/
│   ├── update-current-members.yml       # Daily 06:00 UTC: runs generate_current_members_data.py, commits JSON
│   └── update-ga-members.yml            # Updates GA legislator data
│
├── .claude/settings.local.json          # Tool permissions (Congress.gov, GitHub, Python)
├── .vscode/settings.json
└── not in use/                          # Archived/unused files
```

## Core Principles
- **API Key Security First**: Never expose API keys in client-side code. Use build-time generation (GitHub Actions) to fetch data and serve static JSON. If live API calls are needed, implement a proxy.
- **Static Site Best Practices**: Prefer prebuilt data over dynamic fetches to avoid CORS issues and key exposure.
- **Congress.gov API Handling**: Map fields correctly (`partyHistory[0].partyName` for party, `terms.item[0].chamber` for chamber). Always filter client-side for state/chamber — the API doesn't support direct chamber queries. Note API limitations in UI (e.g., no contact info).
- **Error Handling**: Clear, actionable error messages for users ("Data file missing—run the workflow"). Log errors to console for debugging.
- **Environment Awareness**: Detect GitHub Pages paths (e.g., `/votega.org-TEST/`) and adjust redirects accordingly.
- **GitHub Actions**: Use secrets for sensitive data. Schedule workflows for daily updates. Include `fetch-depth: 0` only if git history is needed.

## Coding Patterns
- **JavaScript**: `async/await` for fetches. `fetch()` over XMLHttpRequest. Constants at top (e.g., `DATA_URL`).
- **HTML**: Semantic elements. Fallback links (e.g., back to search page). Inline scripts for simplicity.
- **Python**: `urllib` for requests, paginate with loops, output clean JSON with metadata (`updatedAt`, `count`).
- **Workflows**: Latest Node.js versions. `ubuntu-latest` runners.

## Project-Specific Conventions
- **Data format**: Congress member JSON includes `bioguideId`, `name`, `partyName`, `state`, `terms.item[]`, `depiction.imageUrl`.
- **Never commit secrets** — only generated JSON files go back to the repo via workflows.
- **UX**: Show loading states, handle empty data gracefully, explain API limitations in UI.

## Enforcement
- Check for API key exposure before suggesting any code changes.
- If proposing live API calls, suggest static/build-time alternatives first.
- For new features, verify against Congress.gov API docs and test with sample data.
- Comment the code where appropriate to give contextual clues for future iterations. 
