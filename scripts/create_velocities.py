#!/usr/bin/env python3
"""Calculate smoothed vx/vy velocities for every player in every tracking frame.

Brought across from the Soccermatics course folder, where this lived under the
name ``create_freeze_frames.py`` even though it computes velocities -- the name
clashed with the separate freeze-frame script, so it is renamed here.

Adapted to this repo: gzipped tracking via sc_paths, team as a CLI argument, and
completed matches are skipped so the run is resumable.

Output: data/{Team}/velocities/{match_id}.parquet
Columns: frame, period, time_s, player_id, is_detected, x, y, vx, vy, speed
"""
import sys

import numpy as np
import pandas as pd
import scipy.signal as signal

import sc_paths

MAX_SPEED = 12    # m/s -- above this is treated as a positional error
WINDOW = 7        # Savitzky-Golay window length (must be odd)
POLYORDER = 1     # polynomial order for SG filter


def parse_timestamp(ts: str) -> float:
    """Convert HH:MM:SS.FF timestamp string to total seconds."""
    h, m, s = ts.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def calc_velocities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute smoothed vx/vy for each player.

    Expects a long-format DataFrame with columns:
        frame, period, time_s, player_id, is_detected, x, y
    (x/y are NaN when the player is not detected in that frame)

    Returns the same DataFrame with vx, vy, speed columns added.
    """
    results = []

    for _player_id, grp in df.groupby('player_id'):
        grp = grp.sort_values('frame').copy()
        dt = grp['time_s'].diff()

        vx = grp['x'].diff() / dt
        vy = grp['y'].diff() / dt

        # Remove outliers caused by position errors
        raw_speed = np.sqrt(vx**2 + vy**2)
        vx[raw_speed > MAX_SPEED] = np.nan
        vy[raw_speed > MAX_SPEED] = np.nan

        # Smooth separately per period (avoids half-time discontinuity)
        for _period, period_grp in grp.groupby('period'):
            idx = period_grp.index
            if len(idx) >= WINDOW:
                vx.loc[idx] = signal.savgol_filter(
                    vx.loc[idx].fillna(0).values,
                    window_length=WINDOW,
                    polyorder=POLYORDER,
                )
                vy.loc[idx] = signal.savgol_filter(
                    vy.loc[idx].fillna(0).values,
                    window_length=WINDOW,
                    polyorder=POLYORDER,
                )

        grp['vx'] = vx
        grp['vy'] = vy
        grp['speed'] = np.sqrt(vx**2 + vy**2)
        results.append(grp)

    return pd.concat(results, ignore_index=True)


def process_match(team: str, match_id, out_path):
    tracking = sc_paths.load_tracking(team, match_id)

    rows = []
    for frame_data in tracking:
        if frame_data['timestamp'] is None or not frame_data['player_data']:
            continue
        frame = frame_data['frame']
        period = frame_data['period']
        time_s = parse_timestamp(frame_data['timestamp'])
        for player in frame_data['player_data']:
            detected = player.get('is_detected', False)
            rows.append({
                'frame': frame,
                'period': period,
                'time_s': time_s,
                'player_id': player['player_id'],
                'is_detected': detected,
                'x': player['x'] if detected else np.nan,
                'y': player['y'] if detected else np.nan,
            })

    df = pd.DataFrame(rows)
    result = calc_velocities(df)

    # Downcast: full-match velocities are ~1M rows per match and float64 columns
    # dominate the file size. float32 is well beyond tracking's real precision.
    for col in ('x', 'y', 'vx', 'vy', 'speed'):
        result[col] = result[col].astype('float32')
    result['frame'] = result['frame'].astype('int32')
    result['player_id'] = result['player_id'].astype('int32')

    result.to_parquet(out_path, index=False, compression='zstd')
    return len(result)


def main():
    team = sys.argv[1] if len(sys.argv) > 1 else 'Liverpool'
    out_dir = sc_paths.team_dir(team) / sc_paths.DERIVED_VELOCITIES
    out_dir.mkdir(parents=True, exist_ok=True)

    ids = sc_paths.match_ids(team)
    print(f'{len(ids)} matches for {team}\n')
    for i, match_id in enumerate(ids, 1):
        out_path = out_dir / f'{match_id}.parquet'
        if out_path.exists():
            print(f'  [{i}/{len(ids)}] {match_id} skip', flush=True)
            continue
        tmp = out_path.with_suffix('.parquet.part')
        n = process_match(team, match_id, tmp)
        tmp.replace(out_path)
        print(f'  [{i}/{len(ids)}] {match_id} {n:,} rows '
              f'({out_path.stat().st_size / 1e6:.1f} MB)', flush=True)
    print('\nAll done.')


if __name__ == '__main__':
    main()
