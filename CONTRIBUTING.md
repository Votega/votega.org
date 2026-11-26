# Contributing to VoteGA.org

Thanks for your interest. Please read this before opening a pull request.

## License of contributions

By submitting a contribution (code, data corrections, content or anything else),
you agree that:

1. Your contribution is licensed to the project owner under the repository's
   license for the kind of material it is: the
   [PolyForm Noncommercial License 1.0.0](LICENSE) for code, and CC BY-SA 4.0 for
   site content and data.
2. In addition, you grant the project owner a perpetual, worldwide,
   non-exclusive, royalty-free, irrevocable license to use, reproduce, modify,
   distribute, **sublicense, relicense, and assign** your contribution, so that it
   may be relicensed or transferred to a successor nonprofit organization.
   (This second grant is needed because the PolyForm license on its own does not
   allow sublicensing or transfer.)
3. You wrote the contribution, or otherwise have the right to submit it under
   these terms, and it does not include material you do not have the right to
   license (including copyleft code such as GPL/AGPL).

"Project owner" means the copyright holder named in [LICENSE](LICENSE) and any
successor or assignee, including a nonprofit organization to which the project's
rights may later be assigned.

## Pull requests

Outside code pull requests are not accepted until this file is merged and in
effect. After that, open an issue first for anything larger than a small fix.

Found a data error? You do not need a pull request: open an issue or email
[admin@votega.org](mailto:admin@votega.org).

## Working on the site locally

The site is Jekyll. The data in `assets/data/` is committed, so you need no API keys to
build it.

**Build and serve**

```sh
bundle install                    # needs Ruby and Bundler. Gemfile.lock is not committed,
                                  # so each machine resolves its own platform.
python scripts/build_render_data.py
python scripts/build_entity_pages.py
bundle exec jekyll serve          # http://localhost:4000
```

The two Python steps generate the per-candidate, per-legislator and per-place pages
and their render data. The deploy workflow runs them before every build. Skip them and
the hand-written pages still build, but the entity pages 404. They need `pyyaml`:

```sh
pip install -c requirements-ci.txt pyyaml
```

**Run the tests**

There is no pytest or npm config on purpose. The suites are plain scripts:

```sh
for t in scripts/test_*.py; do python "$t" || echo "FAIL $t"; done   # Python 3.12
node --test tests/js/*.test.js                                        # Node 22
python scripts/validate_workflow_triggers.py                          # after editing a workflow
```

The Python suites are offline: no network, no repo writes, no third-party packages.
A suite that exits 77 skipped itself (for example, a parity check that needs `node`).
CI runs the same commands (`run-script-tests.yml`, `test-js.yml`).

`requirements-ci.txt` pins every package a workflow installs. Workflows install only
what they need, constrained by it (`pip install -c requirements-ci.txt <package>`).

**Secrets**

Only the data workflows need these, never a local build. Each is a repository secret:

| Secret | Used for | Workflows |
|---|---|---|
| `LEGIS_GA_CLIENT_KEY` | legis.ga.gov diagnostics | `inspect-legis-ga-votes` |
| `CONGRESS_API_KEY` | Congress.gov members and laws | `update-current-members`, `update-presidential-laws` |
| `GOVINFO_API_KEY` | GovInfo signed laws | `update-presidential-laws` |
| `FEC_API_KEY` | FEC campaign finance | `update-fec-data` |
| `COURTLISTENER_TOKEN` | Supreme Court decisions | `update-scotus-decisions` |
| `HUD_USER_TOKEN` | HUD ZIP-to-district crosswalk | `update-ga-zip-districts` |
| `OPENSTATES_API_KEY` | Open States diagnostics only | the four `inspect-*` Open States workflows |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | Deploying the MCP server | `deploy-mcp` |
| `GA_LEGISLATORS_TOKEN` | Pushing to Votega/ga-legislators | `update-ga-members`, `update-ga-votes`, `freeze-ga-roster`, `archive-ga-session` |
| `GA_FEDERAL_LEGISLATORS` | Pushing to Votega/ga-federal-legislators | `update-current-members`, `update-federal-votes`, `publish-federal-delegation-…`, `freeze-federal-delegation` |
| `GA_LEGISLATION_PUSH_TOKEN` | Pushing to Votega/ga-legislation | `update-ga-bills`, `update-ga-votes`, `publish-ga-bills-…`, `publish-ga-ballot-measures-…` |
| `GA_EXECUTIVE_ORDERS_TOKEN` | Pushing to Votega/ga-executive-orders | `update-ga-executive-orders`, `publish-ga-executive-orders`, `backfill-ga-executive-orders` |
| `GA_RACES_PUSH_TOKEN` | Pushing to Votega/ga-races-elections | `publish-races-…`, `publish-early-vote-…` |
| `GA_LOCAL_GOVERNMENT_TOKEN` | Pushing to Votega/ga-local-government | `update-local-government`, `update-ga-millage` |
| `GA_DISTRICT_INFORMATION_TOKEN` | Pushing to Votega/ga-district-information | `update-ga-zip-districts` |

Every other workflow uses the built-in `GITHUB_TOKEN`.

## Name and logo

The VoteGA name and logo are not licensed for use; see [NOTICE.md](NOTICE.md).
