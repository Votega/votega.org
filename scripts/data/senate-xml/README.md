# Hand-saved Senate roll-call XML

senate.gov has refused every automated request under `/legislative/` since
2026-10-25, but the files open fine in a browser. Files saved here are read by
`generate_federal_votes_data.py` and `generate_vp_tie_votes.py` **before** senate.gov
or Voteview, and are treated as the official record (never "provisional").

## How to add a roll call

1. After a Senate vote, run the federal votes workflow (or wait for Sunday's). Its
   run summary lists every roll call still taken from Voteview, each with its URL.
2. Open the URL in a normal browser. If you are on the vote's HTML page instead, use
   the **XML** link at the top right of that page (not the availability page's link,
   which is broken).
3. **Save As** into this folder, keeping the name senate.gov gives it:
   `vote_119_2_00257.xml`. Use Save As or view-source. Copying from the browser's
   rendered XML tree gives you text, not XML, and is refused.
4. Commit the file, then re-run **Update federal legislative vote data** and
   **Update VP tie votes** (workflow_dispatch).

## What is checked

A file is ignored, with a warning, if it does not parse, is not a `roll_call_vote`,
or its congress/session/vote number disagrees with its filename (a saved bot-challenge
page, or a file saved under the wrong name). An official record the site already holds
is never replaced by a dropped file.

Only per-vote files (`vote_<congress>_<session>_<nnnnn>.xml`) are read. A saved
`vote_menu_*.xml` index is deliberately ignored.
