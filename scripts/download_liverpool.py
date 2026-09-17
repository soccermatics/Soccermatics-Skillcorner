"""Download all available SkillCorner data for Liverpool home matches (PL 2025/26).

Resumable: skips any file already on disk, so it is safe to re-run after an
interruption. Tracking data is stored gzipped (lossless, ~10x smaller).
"""
import gzip
import json
import os
import sys
import time
import warnings

warnings.filterwarnings('ignore')
from skillcorner.client import SkillcornerClient

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'Liverpool')
COMPETITION_EDITION = 1198  # ENG - Premier League - 2025/2026
TEAM_SHORT_NAME = 'Liverpool'

# Dynamic events must be pinned to a data_version. The default (v1) is missing
# entirely for the last 6 home matches ("have not been processed"), and where it
# does exist it is an older, sparser processing run than v3 -- 458 vs 470 rows on
# match 2053314. Columns are identical across versions, so v3 is the only choice
# that yields one consistent dataset across all 19 matches. v2 and v3 return
# byte-identical payloads; 3 is pinned as the newest.
DYNAMIC_EVENTS_DATA_VERSION = 3


def make_client():
    """Read credentials from .env (tolerates quoting and the 'passwrod' typo)."""
    env = {}
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    with open(path) as fh:
        for line in fh:
            if '=' in line:
                key, value = line.split('=', 1)
                env[key.strip().lower()] = value.strip().strip('"').strip("'")
    return SkillcornerClient(
        username=env['username'],
        password=env.get('password') or env['passwrod'],
    )


def write_json(path, obj):
    with open(path, 'w') as fh:
        json.dump(obj, fh, separators=(',', ':'))


def write_json_gz(path, obj):
    with gzip.open(path, 'wt', compresslevel=6) as fh:
        json.dump(obj, fh, separators=(',', ':'))


def write_bytes(path, raw):
    with open(path, 'wb') as fh:
        fh.write(raw)


RETRIES = 4


def fetch(path, loader, writer):
    """Fetch and write unless path already exists. Returns bytes written, or -1 if skipped.

    The API intermittently drops connections mid-transfer (RemoteDisconnected,
    IncompleteRead), so transient errors are retried with a linear backoff.
    """
    if os.path.exists(path):
        return -1
    tmp = path + '.part'
    for attempt in range(1, RETRIES + 1):
        try:
            writer(tmp, loader())
            break
        except Exception as exc:                          # noqa: BLE001
            transient = any(
                marker in type(exc).__name__ or marker in str(exc)
                for marker in ('ConnectionError', 'Connection aborted', 'IncompleteRead',
                               'RemoteDisconnected', 'Timeout', 'timed out')
            )
            if not transient or attempt == RETRIES:
                raise
            print(f'      retry {attempt}/{RETRIES - 1} after {type(exc).__name__}', flush=True)
            time.sleep(3 * attempt)
    os.replace(tmp, path)  # atomic: a partial file never looks complete
    return os.path.getsize(path)


def main():
    client = make_client()

    def dyn(method, match_id):
        """Dynamic-events call pinned to DYNAMIC_EVENTS_DATA_VERSION."""
        return method(match_id=match_id, params={'data_version': DYNAMIC_EVENTS_DATA_VERSION})

    matches = [
        m for m in client.get_matches(params={'competition_edition': COMPETITION_EDITION})
        if m['home_team']['short_name'] == TEAM_SHORT_NAME
    ]
    matches.sort(key=lambda m: m['date_time'])
    print(f'{len(matches)} Liverpool home matches', flush=True)

    # --- reference data (once, not per match) ---
    ref = os.path.join(ROOT, 'reference')
    os.makedirs(ref, exist_ok=True)
    for name, loader in [
        ('teams', lambda: client.get_teams(params={'competition_edition': COMPETITION_EDITION})),
        ('players', lambda: client.get_players(params={'competition_edition': COMPETITION_EDITION})),
        ('competition_editions', lambda: [
            e for e in client.get_competition_editions() if e['id'] == COMPETITION_EDITION
        ]),
        ('seasons', client.get_seasons),
        ('matches', lambda: matches),
    ]:
        n = fetch(os.path.join(ref, f'{name}.json'), loader, write_json)
        print(f'  reference/{name}.json {"skip" if n < 0 else f"{n/1e3:.0f} KB"}', flush=True)

    # (subdir, filename suffix, writer, loader factory)
    TASKS = [
        ('tracking',                          '.json.gz', write_json_gz, lambda m: lambda: client.get_match_tracking_data(match_id=m)),
        ('match_metadata',                    '.json',    write_json,    lambda m: lambda: client.get_match(match_id=m)),
        ('match_instructions',                '.json',    write_json,    lambda m: lambda: client.get_match_instructions(match_id=m)),
        ('match_data_collection',             '.json',    write_json,    lambda m: lambda: client.get_match_data_collection(match_id=m)),
        ('dynamic_events/passing_options',     '.csv',    write_bytes,   lambda m: lambda: dyn(client.get_dynamic_events_passing_options, m)),
        ('dynamic_events/player_possessions',  '.csv',    write_bytes,   lambda m: lambda: dyn(client.get_dynamic_events_player_possessions, m)),
        ('dynamic_events/on_ball_engagements', '.csv',    write_bytes,   lambda m: lambda: dyn(client.get_dynamic_events_on_ball_engagements, m)),
        ('dynamic_events/off_ball_runs',       '.csv',    write_bytes,   lambda m: lambda: dyn(client.get_dynamic_events_off_ball_runs, m)),
        ('dynamic_events/phases_of_play',      '.csv',    write_bytes,   lambda m: lambda: dyn(client.get_dynamic_events_phases_of_play, m)),
        ('in_possession/passes',               '.json',   write_json,    lambda m: lambda: client.get_in_possession_passes(params={'match': m})),
        ('in_possession/off_ball_runs',        '.json',   write_json,    lambda m: lambda: client.get_in_possession_off_ball_runs(params={'match': m})),
        ('in_possession/on_ball_pressures',    '.json',   write_json,    lambda m: lambda: client.get_in_possession_on_ball_pressures(params={'match': m})),
    ]
    for subdir, _, _, _ in TASKS:
        os.makedirs(os.path.join(ROOT, subdir), exist_ok=True)

    total, failures = 0, []
    for i, m in enumerate(matches, 1):
        mid = m['id']
        label = f"{m['date_time'][:10]} vs {m['away_team']['short_name']}"
        print(f'[{i}/{len(matches)}] {mid} {label}', flush=True)
        for subdir, suffix, writer, loader_for in TASKS:
            path = os.path.join(ROOT, subdir, f'{mid}{suffix}')
            t0 = time.time()
            try:
                n = fetch(path, loader_for(mid), writer)
            except Exception as exc:                      # noqa: BLE001 - log and continue
                failures.append((mid, subdir, str(exc).splitlines()[0][:90]))
                print(f'    FAIL {subdir}: {failures[-1][2]}', flush=True)
                if os.path.exists(path + '.part'):
                    os.remove(path + '.part')
                continue
            if n < 0:
                print(f'    skip {subdir}', flush=True)
            else:
                total += n
                print(f'    {subdir:<36} {n/1e6:7.2f} MB  {time.time()-t0:5.1f}s', flush=True)

    print(f'\ndownloaded {total/1e9:.2f} GB this run', flush=True)
    if failures:
        print(f'{len(failures)} failures:', flush=True)
        for mid, sub, err in failures:
            print(f'  {mid} {sub}: {err}', flush=True)
        return 1
    print('all files present', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
