#!/usr/bin/env python3
"""Generate freeze frames from the start and end frames of the dynamic events.

Brought across from the Soccermatics course (@gustimorth) and adapted to this
repo: tracking is read gzipped via sc_paths, the team is a CLI argument rather
than a hard-coded RealMadrid folder, and matches already present are skipped.

Output: data/{Team}/freeze/{match_id}.parquet
Columns: time, frame, period, player_id, is_detected, is_ball, x, y, visible_area
"""
import sys

import pandas as pd

import sc_paths


def freeze_frames_for_match(team: str, match_id) -> pd.DataFrame:
    """One row per player (plus one for the ball) for every event start/end frame."""
    dynamic_path = sc_paths.team_dir(team) / sc_paths.DERIVED_DYNAMIC / f'{match_id}.parquet'
    df_events = pd.read_parquet(dynamic_path)

    # Only the frames an event starts or ends on are needed, which is a small
    # fraction of the ~60k frames in a match.
    frames = set(df_events['frame_start'].dropna().astype(int).tolist())
    frames |= set(df_events['frame_end'].dropna().astype(int).tolist())

    tracking = sc_paths.load_tracking(team, match_id)

    rows = []
    for d in tracking:
        if d.get('frame') not in frames or d.get('timestamp') is None:
            continue
        common = {
            'time': d.get('timestamp'),
            'frame': int(d.get('frame')),
            'period': d.get('period'),
            'visible_area': d.get('image_corners_projection'),
        }
        for p in d['player_data']:
            rows.append({
                **common,
                'player_id': p.get('player_id'),
                'is_detected': p.get('is_detected'),
                'is_ball': False,
                'x': p.get('x'),
                'y': p.get('y'),
            })
        ball = d.get('ball_data')
        if ball and ball.get('is_detected') is not None:
            rows.append({
                **common,
                'player_id': -1,
                'is_detected': ball.get('is_detected'),
                'is_ball': True,
                'x': ball.get('x'),
                'y': ball.get('y'),
            })

    return pd.DataFrame(rows)


def main():
    team = sys.argv[1] if len(sys.argv) > 1 else 'Liverpool'
    out_dir = sc_paths.team_dir(team) / sc_paths.DERIVED_FREEZE
    out_dir.mkdir(parents=True, exist_ok=True)

    ids = sc_paths.match_ids(team)
    print(f'{len(ids)} matches for {team}\n')
    for i, match_id in enumerate(ids, 1):
        out_path = out_dir / f'{match_id}.parquet'
        if out_path.exists():
            print(f'  [{i}/{len(ids)}] {match_id} skip', flush=True)
            continue
        df = freeze_frames_for_match(team, match_id)
        df.to_parquet(out_path, index=False)
        print(f'  [{i}/{len(ids)}] {match_id} {len(df):,} rows '
              f'({df["frame"].nunique():,} frames)', flush=True)
    print('\nAll done.')


if __name__ == '__main__':
    main()
