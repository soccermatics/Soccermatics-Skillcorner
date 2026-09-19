# SkillCorner — Team Home Games

Interactive exploration of SkillCorner tracking and dynamic-event data for one
team's home matches. The analysis code comes from the Soccermatics course; the data
comes from this repo's own downloader or the course's Dropbox folder.

All 20 Premier League teams of 2025/2026 are available, each with its own 19
home matches.

## Work with one team at a time

**You only need one team's folder.** Each is self-contained — its own matches,
tracking, events and reference data — and weighs about 400 MB. The full set of
20 teams is 7.9 GB, which you almost certainly do not want.

From the course Dropbox folder (`Shared Skillcorner`), copy the single team you
are working on into `data/` here, so you end up with `data/Liverpool/` or
`data/Arsenal/` and nothing else. In Dropbox you can use selective sync to
download just that one folder rather than the whole share. The app lists
whichever team folders it finds, so adding a second team later is just a matter
of copying it in.

## Quick start

Using data from the course Dropbox folder:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt pyarrow

mkdir -p data
cp -R ~/Dropbox/"Shared Skillcorner"/Liverpool data/   # your team, ~400 MB

.venv/bin/streamlit run app/st_dynamic.py
```

That folder already contains the derived files, so there is nothing to build.

Downloading from the API instead — this needs your own SkillCorner account with
access to the 2025/2026 Premier League, and credentials in a `.env` file
(`SKILLCORNER_USERNAME` / `SKILLCORNER_PASSWORD`):

```bash
.venv/bin/pip install skillcorner
.venv/bin/python scripts/download_liverpool.py Liverpool   # or --all for 20 teams
cd scripts && ../.venv/bin/python build_all.py Liverpool && cd ..
```

Python **3.11+ is required** — `mplsoccer` imports `dataclasses.KW_ONLY`, which
does not exist on 3.9.

## The app

Pick a team in the sidebar (each `data/<Team>` folder holds that team's home
matches), select one or more matches, then a pass, then which associated events
to draw. The pitch plot shows player positions with jersey numbers and colours,
the ball, velocity vectors, the camera's visible area, and optionally a
Spearman pitch-control surface.

## Layout

```
app/
├── st_dynamic.py     Streamlit app (@gustimorth; adapted for team selection)
└── PitchControl.py   Spearman (2018) pitch control, verbatim from the course
scripts/
├── download_liverpool.py    SkillCorner API -> data/<Team> (resumable; --all)
├── sc_paths.py              shared paths; hides raw-vs-derived layout
├── build_dynamic.py         matches.parquet + dynamic/{id}.parquet
├── create_freeze_frames.py  freeze/{id}.parquet  (from tracking + events)
├── create_velocities.py     velocities/{id}.parquet (Savitzky-Golay smoothing)
└── build_all.py             runs all three stages for one team or every team
data/<Team>/
├── tracking/            {id}.json.gz   raw, gzipped (~8 MB/match)
├── match_metadata/      {id}.json      lineups, pitch size, kit colours, GKs
├── match_instructions/  {id}.json
├── match_data_collection/{id}.json     SkillCorner's own QC flags
├── dynamic_events/      <type>/{id}.csv  5 event types, raw
├── in_possession/       <type>/{id}.json aggregated metrics
├── reference/           teams, players, matches, seasons, competition edition
├── matches.parquet      derived
├── dynamic/             derived — the 4 event types merged
├── freeze/              derived — player+ball positions at event frames
└── velocities/          derived — vx, vy, speed per player per frame
```

`data/` is gitignored: the raw data is re-downloadable and the derived parquet
files are regenerable from it.

## Notes on the data

**No physical data.** `get_physical()` returns HTTP 200 with zero rows for every
parameter combination — that dataset is not provisioned on this account. It is
not an auth error. The course's `RealMadrid/physical/` folder has no counterpart
here.

**Dynamic events are pinned to `data_version=3`.** The API default (v1) is
missing entirely for the last six home matches, and where it does exist it is an
older, sparser processing run — 458 vs 470 rows on match 2053314. Columns are
identical across versions, so v3 is the only choice that gives one consistent
dataset across all 19 matches. See `DYNAMIC_EVENTS_DATA_VERSION` in
`scripts/download_liverpool.py`.

**Two Brighton matches have no dynamic events.** `2059493` (vs Liverpool,
21 Mar) and `2064053` (vs Chelsea, 21 Apr) return 400 "Data does not meet the
quality standard required for usage" for every event type and every
`data_version`. This is permanent on SkillCorner's side, not a download failure.
Their tracking and metadata are intact, but they are left out of Brighton's
`matches.parquet` so the app does not offer a match with no passes to select —
Brighton therefore shows 17 matches rather than 19.

**`phases_of_play` is excluded from `dynamic/`.** It has no `event_type` column,
sits at a different granularity, and the app never reads it. The raw CSVs are
still downloaded under `dynamic_events/phases_of_play/`.

**Tracking is stored gzipped.** ~8 MB per match rather than ~78 MB, losslessly.
Read it with `sc_paths.load_tracking(team, match_id)`.

**The API drops connections.** Roughly 5% of dynamic-event requests fail with
`RemoteDisconnected` or `IncompleteRead`; the downloader retries transient
errors and is resumable, so re-running it fills any gaps.

## Adding another team

Copy another team's folder from the course Dropbox into `data/` and the app
picks it up automatically — the sidebar lists whatever it finds.

To pull one from the API instead:

```bash
.venv/bin/python scripts/download_liverpool.py "Aston Villa"
cd scripts && ../.venv/bin/python build_all.py "Aston Villa"
```

Team names must match SkillCorner's `short_name` exactly (`Manchester U`,
`Nottingham`, `Brentford FC`); `reference/teams.json` lists them. Every match in
the competition is exactly one team's home match, so the 20 teams partition the
380-match season with no duplication.

## Credits

This code written by Ágúst Pálmason Morthens, with some adjustments by David Sumpter 

- Pitch control implementation: Laurie Shaw (@EightyFivePoint)
- Pitch control methodology: William Spearman, *Beyond Expected Goals*, MIT Sloan 2018
- Streamlit app and freeze-frame generation: @gustimorth
- Data provider: SkillCorner

For educational use as part of the Soccermatics course.
