# SkillCorner — Team Home Games

Interactive exploration of SkillCorner tracking and dynamic-event data for one
team's home matches. The analysis code comes from the Soccermatics course; the data
comes from this repo's own downloader or the course's Dropbox folder.

Currently loaded: **Liverpool**, all 19 home matches, ENG Premier League 2025/2026.

## Quick start

```bash
python3.11 -m venv .venv
.venv/bin/pip install skillcorner -r requirements.txt pyarrow

.venv/bin/python scripts/download_liverpool.py      # raw data  (~220 MB)
cd scripts
../.venv/bin/python build_dynamic.py Liverpool      # matches.parquet + dynamic/
../.venv/bin/python create_freeze_frames.py Liverpool
../.venv/bin/python create_velocities.py Liverpool
cd ..

.venv/bin/streamlit run app/st_dynamic.py
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
├── download_liverpool.py    SkillCorner API -> data/Liverpool (resumable)
├── sc_paths.py              shared paths; hides raw-vs-derived layout
├── build_dynamic.py         matches.parquet + dynamic/{id}.parquet
├── create_freeze_frames.py  freeze/{id}.parquet  (from tracking + events)
└── create_velocities.py     velocities/{id}.parquet (Savitzky-Golay smoothing)
data/Liverpool/
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

**`phases_of_play` is excluded from `dynamic/`.** It has no `event_type` column,
sits at a different granularity, and the app never reads it. The raw CSVs are
still downloaded under `dynamic_events/phases_of_play/`.

**Tracking is stored gzipped.** ~8 MB per match rather than ~78 MB, losslessly.
Read it with `sc_paths.load_tracking(team, match_id)`.

**The API drops connections.** Roughly 5% of dynamic-event requests fail with
`RemoteDisconnected` or `IncompleteRead`; the downloader retries transient
errors and is resumable, so re-running it fills any gaps.

## Adding another team

The downloader is currently hard-coded to Liverpool home matches
(`TEAM_SHORT_NAME`). Change it, re-run, then re-run the three build scripts with
the new team name. The app picks up any `data/<Team>` folder automatically.

## Credits

This code written by Ágúst Pálmason Morthens, with some adjustments by David Sumpter 

- Pitch control implementation: Laurie Shaw (@EightyFivePoint)
- Pitch control methodology: William Spearman, *Beyond Expected Goals*, MIT Sloan 2018
- Streamlit app and freeze-frame generation: @gustimorth
- Data provider: SkillCorner

For educational use as part of the Soccermatics course.
