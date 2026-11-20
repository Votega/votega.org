# data-inputs/

Large or third-party source files that build scripts read but that are **not committed**: everything in this folder except this README is gitignored. They live here, not in a downloads folder, so a periodic clean-out doesn't lose them. Git does not back them up, so if one goes missing, re-download it from the source below and check its checksum.

## redistricting/

Official Georgia plan files from the Legislative and Congressional Reapportionment Office, https://www.legis.ga.gov/joint-office/reapportionment. Used by `scripts/build_ga_tract_district_table.py` (2023 plans) and by the seat-history block comparison (`docs/seat-history-design.md`, "The identity rule"). Every block-equivalency workbook covers the same 232,717 census blocks.

| File | Plan | Notes | MD5 | Bytes |
|---|---|---|---|---|
| `2021/congress-prop1-2021-block-equiv.xlsx` | Congress, as passed Nov 22, 2021 | Downloaded as `congress-prop1-20214703665e50b6445eb631193eef0581f7.xlsx` | `385267614f72060090dd3191ae376d2b` | 3,774,457 |
| `2021/senate-prop1-2021-block-equiv.xlsx` | GA Senate, 2021 | Downloaded as `senate-prop1-2021082f28844bdf42a3ac10210fd96a0304.xlsx` | `4ace822513bec9402259fe9adff96bda` | 3,798,590 |
| `2021/house-prop1-2021-block-equiv.xlsx` | GA House, 2021 | Downloaded as `house-prop1-2021ab455058f8d44f258145472b8b96f853.xlsx` | `cb7da32fe6ccc33abe20e9c89c5ef86c` | 3,844,987 |
| `2021/congress-prop1-2021-shape.zip` | Congress, 2021 shapefile | 14 district polygons (NAD83); attribute table has each district's official `POPULATION`, used to reconcile a 2021 roll-up | `c3064880434156cc35c93ab6a0656606` | 1,569,398 |
| `2023/congress-2023-block-equiv.xlsx` | Congress, 2023 | | `883ee3ba3825efdd7d523bb82dbaed3d` | 3,756,676 |
| `2023/senate-2023-block-equivalency.xlsx` | GA Senate, 2023 | | `fcd6c3196ee2d92be0d00ab19e570ab2` | 3,794,134 |
| `2023/house-2023-block-equiv.xlsx` | GA House, 2023 | | `df3816eb2ce36d99b0a41bb439311770` | 3,843,825 |
| `2023/senate-2023-packet-upd.pdf` | Senate 2023 plan packet | District totals; read via `pdftotext -layout` | `29eba5b0a77652bfb9dcb89d66fcb6ab` | 7,680,383 |
| `2023/house-2023-packet-upd.pdf` | House 2023 plan packet | | `14c10a0158ea583cd418a2972dd62213` | 7,796,734 |
| `2023/congress-2023-packet-upd.pdf` | Congress 2023 plan packet | The tract builder has no option to read it; Congress is checked against its county report | `e99fb6307a51ca2964b9bddc97d1166d` | 5,579,132 |
| `2023/senate-2023-county-report.pdf` | Senate 2023 county report | | `13f7ca0a30ccce80b975e6340fb8c66d` | 159,588 |
| `2023/house-2023-county-report.pdf` | House 2023 county report | | `2a4dc68014bd38878cfefcc6a27c7c8e` | 189,117 |
| `2023/congress-2023-county-report.pdf` | Congress 2023 county report | | `d9365edac597408a993286b7cd8d1934` | 150,478 |
| `2022-psc/psc-2022-block-equiv.xlsx` | Public Service Commission residency districts, 2022 | Not used by any script yet | `df5ec333f6369fd9ec0d01de61b9a99a` | 3,718,073 |

### redistricting/census/

Census 2020 PL 94-171 redistricting data for Georgia, public domain, from https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/Georgia/ga2020.pl.zip (downloaded 2026-11-20). `gageo2020.pl` is the only part the scripts read: it carries each block's `POP100`, read by `build_ga_tract_district_table.py --geo`. The three data segments stay inside the zip.

| File | Notes | MD5 | Bytes |
|---|---|---|---|
| `census/ga2020.pl.zip` | The download as published. Contains `ga000012020.pl`, `ga000022020.pl`, `ga000032020.pl` and `gageo2020.pl` | `7d7ce3e40128ac26164abdf8398d8f76` | 35,831,859 |
| `census/gageo2020.pl` | Extracted from the zip | `196b401389a3336979e0ba285f548273` | 126,739,688 |

Checked on download: 232,717 blocks (the same set as every block-equivalency workbook above), a state total of 10,711,908, 159 counties, and the 2021 congressional plan's block roll-up matches the shapefile's official `POPULATION` for all 14 districts exactly. So the 2021 plans can be reconciled to the person, like the 2023 ones.

To check every file: `md5sum -c` against the table, or `python -c "import hashlib,sys;print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" <file>`.
