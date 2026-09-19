#!/usr/bin/env python3
"""Build matches.parquet and dynamic/{match_id}.parquet for one team.

The Real Madrid course folder shipped these two artefacts pre-made. Our
downloader stores SkillCorner's raw payloads instead, so this script produces
them:

* ``matches.parquet``          -- the match list the app's dropdown reads
* ``dynamic/{id}.parquet``     -- the four dynamic event types merged into one
                                  frame, which is what ``st_dynamic.py`` expects

Usage:  python scripts/build_dynamic.py [Team]
"""
import json
import sys

import pandas as pd

import sc_paths


def build_matches(team: str, usable_ids=None) -> pd.DataFrame:
    """matches.parquet: id, date_time, home_team/away_team as dicts (app unpacks them).

    ``usable_ids`` restricts the list to matches that actually have dynamic events.
    SkillCorner permanently refuses a few matches with 400 "Data does not meet the
    quality standard required for usage", and the app is built entirely around
    selecting a pass -- so a match with no events would only offer the user a dead
    end. Their raw tracking stays on disk for anyone who wants it.
    """
    path = sc_paths.team_dir(team) / 'reference' / 'matches.json'
    with open(path, encoding='utf-8') as fh:
        matches = json.load(fh)
    if usable_ids is not None:
        dropped = [m for m in matches if m['id'] not in usable_ids]
        for m in dropped:
            print(f'    excluding {m["id"]} ({m["date_time"][:10]} vs '
                  f'{m["away_team"]["short_name"]}) -- no dynamic events')
        matches = [m for m in matches if m['id'] in usable_ids]
    df = pd.DataFrame(matches).sort_values('date_time').reset_index(drop=True)
    out = sc_paths.team_dir(team) / 'matches.parquet'
    df.to_parquet(out, index=False)
    print(f'matches.parquet: {len(df)} matches -> {out}')
    return df


def build_dynamic(team: str, match_id) -> int:
    """Merge the per-event-type CSVs into a single long frame for one match.

    Column sets differ between event types (209 cols for player_possessions,
    118 for off_ball_runs, ...), so the concat is by column name and missing
    columns become NaN -- which is exactly what the app's per-event-type
    filtering expects.
    """
    base = sc_paths.team_dir(team) / sc_paths.RAW_DYNAMIC
    frames = []
    for event_type in sc_paths.EVENT_TYPES:
        csv = base / event_type / f'{match_id}.csv'
        if not csv.exists():
            print(f'    missing {event_type}', flush=True)
            continue
        frames.append(pd.read_csv(csv, low_memory=False))
    if not frames:
        return 0

    df = pd.concat(frames, ignore_index=True, sort=False)

    out_dir = sc_paths.team_dir(team) / sc_paths.DERIVED_DYNAMIC
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / f'{match_id}.parquet', index=False)
    return len(df)


def main():
    team = sys.argv[1] if len(sys.argv) > 1 else 'Liverpool'
    ids = sc_paths.match_ids(team)
    print(f'merging dynamic events for {len(ids)} matches')
    total, usable = 0, set()
    for i, match_id in enumerate(ids, 1):
        n = build_dynamic(team, match_id)
        total += n
        if n:
            usable.add(match_id)
        print(f'  [{i}/{len(ids)}] {match_id}  {n:,} events', flush=True)
    build_matches(team, usable)
    print(f'\n{total:,} events across {len(usable)}/{len(ids)} matches')


if __name__ == '__main__':
    main()
