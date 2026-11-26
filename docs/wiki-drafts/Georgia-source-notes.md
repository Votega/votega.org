Notes on public sources VoteGA reads, for people building their own tools. These are observations, not official documentation, and the services can change without notice. Check the date on each section.

Please be considerate: request only what you need, cache what you fetch, and follow each site's terms. Much of this data is already cleaned up in the [repositories](Home#repositories), so you may not need the source at all.

## General Assembly web service

*Checked 26 November 2026.*

SOAP services at `http://webservices.legis.ga.gov/GGAServices/<Area>/Service.svc`, where `<Area>` includes `Session`, `Members`, `Committees`, `Legislation` and `Votes`. No key is needed. It is HTTP only, so call it from a server or script, not a web page.

```python
import urllib.request
import xml.etree.ElementTree as ET

SVC = "http://www.legis.ga.gov/2009/01/01/services/"
body = ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:s="{SVC}"><soap:Body><s:GetSessions></s:GetSessions>'
        '</soap:Body></soap:Envelope>')
req = urllib.request.Request(
    "http://webservices.legis.ga.gov/GGAServices/Session/Service.svc",
    data=body.encode("utf-8"),
    headers={"Content-Type": "text/xml; charset=utf-8",
             "SOAPAction": '"GetSessions"'})
with urllib.request.urlopen(req, timeout=60) as r:
    root = ET.fromstring(r.read())
for el in root.iter():
    if el.tag.endswith("}Description"):
        print(el.text)
```

Things that cost us time:

- **`SOAPAction` is not uniform.** `GetSessions` takes the bare operation name. Votes and Legislation operations take a full namespaced action. Read each service's WSDL.
- **Ask for session IDs, never guess them.** They are neither contiguous nor in date order.
- **`IsDefault` marks the current regular session,** which may not be the session now meeting.
- **Parameter names are case-sensitive.** A mis-cased parameter can be ignored, and you get an answer for the default session instead of an error.
- **Some roll calls aren't published.** Attendance roll calls return a fault.
- **A member ID of `0` is a placeholder** for an empty seat.
- **Listings are thinner than detail calls.** `GetMember` returns far more than the session member list.

## Secretary of State election results

*Checked 26 November 2026.*

The results site serves JSON:

| Request | Returns |
|---|---|
| `https://results.sos.ga.gov/results/public/api/jurisdictions/Georgia` | The list of elections, each with a `publicElectionId` |
| `https://results.sos.ga.gov/results/public/api/elections/Georgia/<publicElectionId>/data` | Contests, candidates and vote totals |

```python
import json, urllib.request

API = "https://results.sos.ga.gov/results/public/api"

def get(path):
    req = urllib.request.Request(f"{API}/{path}",
                                 headers={"User-Agent": "my-civic-tool/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8-sig"))

data = get("elections/Georgia/2024NovGen/data")
print("official:", data["election"]["isOfficialResults"])
first = data["ballotItems"][0]
print(first["name"][0]["text"])
for o in first["summaryResults"]["ballotOptions"]:
    print(" ", o["name"][0]["text"], o["voteCount"])
```

- **Name your tool in `User-Agent`.** A request with Python's default value was refused.
- **Look election IDs up.** Their format varies (`2024NovGen`, `12012026GeneralElectionRunoff`).
- **Check `isOfficialResults`** before treating counts as final.
- **County results** use the county's short name in place of `Georgia` in the elections path.
- **Local offices have little history.** In the counties we checked (September 2026), county and city offices appeared from about 2024; 2020 and 2022 had none.
- **Don't rely on `isWinner` for local races.** We found it unset on decided contests. The top vote count is not enough either: many Georgia offices require a majority, with a runoff held as a separate election.
- **Office names drift** between cycles, so don't match across years on the exact string.
- **No term dates** are provided.

## PeachFile (state campaign finance)

*From VoteGA's collection code, first written August 2026.*

[PeachFile](https://peachfile.ethics.ga.gov/) holds filings from 1 January 2026. Earlier records are at [ethics.ga.gov](https://ethics.ga.gov/records-search-all/). PeachFile offers bulk CSV downloads, which are the better choice for large pulls.

If you work with its records:

- **Pages are limited.** Requests for much more than 100 rows are rejected.
- **The reported row total is unreliable.** Page until you get a short page.
- **Results mix election cycles.** Filter on the cycle name, or one cycle's totals will appear on another's race.
- **No shared person ID.** Match on office, district and then name. Name alone will attribute one person's money to another.
- **No filing found is often correct,** for example when someone is running for a different office.
