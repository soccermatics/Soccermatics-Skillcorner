#!/usr/bin/env python3
"""Build every derived artefact for one team, or for all downloaded teams.

Runs the three build stages in the order they depend on each other:

    build_dynamic        matches.parquet + dynamic/{id}.parquet   (needs raw CSVs)
    create_freeze_frames freeze/{id}.parquet                      (needs dynamic/)
    create_velocities    velocities/{id}.parquet                  (needs tracking)

Every stage skips work already on disk, so this is safe to re-run.

Usage:
    python scripts/build_all.py             # every team under data/
    python scripts/build_all.py Arsenal     # one team
"""
import sys
import time
import traceback

import build_dynamic
import create_freeze_frames
import create_velocities
import sc_paths


def build_team(team: str) -> dict:
    """Run all three stages for one team. Returns per-stage timings."""
    timings = {}
    ids = sc_paths.match_ids(team)
    print(f'\n=== {team}: {len(ids)} matches ===', flush=True)

    t0 = time.time()
    usable = set()
    for match_id in ids:
        if build_dynamic.build_dynamic(team, match_id):
            usable.add(match_id)
    build_dynamic.build_matches(team, usable)
    timings['dynamic'] = time.time() - t0
    print(f'  dynamic   {timings["dynamic"]:6.1f}s', flush=True)

    t0 = time.time()
    freeze_dir = sc_paths.team_dir(team) / sc_paths.DERIVED_FREEZE
    freeze_dir.mkdir(parents=True, exist_ok=True)
    for match_id in sorted(usable):
        out = freeze_dir / f'{match_id}.parquet'
        if out.exists():
            continue
        create_freeze_frames.freeze_frames_for_match(team, match_id).to_parquet(out, index=False)
    timings['freeze'] = time.time() - t0
    print(f'  freeze    {timings["freeze"]:6.1f}s', flush=True)

    t0 = time.time()
    vel_dir = sc_paths.team_dir(team) / sc_paths.DERIVED_VELOCITIES
    vel_dir.mkdir(parents=True, exist_ok=True)
    for match_id in ids:
        out = vel_dir / f'{match_id}.parquet'
        if out.exists():
            continue
        tmp = out.with_suffix('.parquet.part')
        create_velocities.process_match(team, match_id, tmp)
        tmp.replace(out)
    timings['velocities'] = time.time() - t0
    print(f'  velocity  {timings["velocities"]:6.1f}s', flush=True)

    return timings


def main():
    teams = [sys.argv[1]] if len(sys.argv) > 1 else sc_paths.available_teams()
    if not teams:
        print('No team folders found under data/.')
        return 1
    print(f'{len(teams)} team(s): {", ".join(teams)}')

    failures = []
    t_start = time.time()
    for i, team in enumerate(teams, 1):
        print(f'\n########## {i}/{len(teams)} ##########', flush=True)
        try:
            build_team(team)
        except Exception:                                  # noqa: BLE001
            failures.append(team)
            print(f'  FAILED {team}:\n{traceback.format_exc()}', flush=True)

    print(f'\ntotal {(time.time() - t_start) / 60:.1f} min')
    if failures:
        print(f'{len(failures)} team(s) failed: {", ".join(failures)}')
        return 1
    print('all teams built')
    return 0


if __name__ == '__main__':
    sys.exit(main())
