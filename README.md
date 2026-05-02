# votega.org-TEST
Test/Dev Site for votega.org

## Refreshing Congress member data

This repo uses a GitHub Actions workflow to generate `assets/data/current-members.json` from the Congress.gov API.

[![Update Congress.gov current members data](https://github.com/Votega/votega.org-TEST/actions/workflows/update-current-members.yml/badge.svg)](https://github.com/Votega/votega.org-TEST/actions/workflows/update-current-members.yml)

To refresh the data manually:

1. Go to the repository on GitHub.
2. Open the `Actions` tab.
3. Select the workflow `Update Congress.gov current members data`.
4. Click `Run workflow`.

The workflow uses the `CONGRESS_API_KEY` secret.
