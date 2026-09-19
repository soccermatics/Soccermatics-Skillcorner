"""Download all available SkillCorner data for a team's home matches (PL 2025/26).

Every match in the competition is exactly one team's home match, so downloading
all 20 teams covers the full 380-match season with no duplication.

Usage:
    python scripts/download_liverpool.py                # Liverpool (default)
    python scripts/download_liverpool.py Arsenal        # one team
    python scripts/download_liverpool.py --all          # every team in the edition

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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
COMPETITION_EDITION = 1198  # ENG - Premier League - 2025/2026
DEFAULT_TEAM = 'Liverpool'


def team_root(team_short_name):
    """Data directory for one team, with '/' made filesystem-safe."""
    return os.path.join(DATA_ROOT, team_short_name.replace('/', '-'))

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
    path = os.path.join(REPO_ROOT, '.env')
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
            text = f'{type(exc).__name__} {exc}'
            # 502/503/504 are gateway hiccups and 'Connection reset by peer' is a
            # dropped socket -- both are worth retrying. A 400 "Data does not meet
            # the quality standard" is SkillCorner's permanent refusal, so it must
            # NOT match here or the run wastes four attempts on every such file.
            transient = any(marker in text for marker in (
                'ConnectionError', 'ConnectionReset', 'Connection aborted',
                'Connection reset', 'IncompleteRead', 'RemoteDisconnected',
                'Timeout', 'timed out', 'Errno 54', 'Errno 104',
                '(502', '(503', '(504', 'Bad Gateway', 'Service Unavailable',
            ))
            if not transient or attempt == RETRIES:
                raise
            print(f'      retry {attempt}/{RETRIES - 1} after {type(exc).__name__}', flush=True)
            time.sleep(3 * attempt)
    os.replace(tmp, path)  # atomic: a partial file never looks complete
    return os.path.getsize(path)


def download_team(client, team_short_name, all_matches, reference_loaders):
    """Download every data type for one team's home matches. Returns (bytes, failures)."""
    ROOT = team_root(team_short_name)

    def dyn(method, match_id):
        """Dynamic-events call pinned to DYNAMIC_EVENTS_DATA_VERSION."""
        return method(match_id=match_id, params={'data_version': DYNAMIC_EVENTS_DATA_VERSION})

    matches = [m for m in all_matches if m['home_team']['short_name'] == team_short_name]
    matches.sort(key=lambda m: m['date_time'])
    print(f'\n=== {team_short_name}: {len(matches)} home matches ===', flush=True)

    # --- reference data (once per team, so each folder is self-contained) ---
    ref = os.path.join(ROOT, 'reference')
    os.makedirs(ref, exist_ok=True)
    for name, loader in list(reference_loaders) + [('matches', lambda: matches)]:
        fetch(os.path.join(ref, f'{name}.json'), loader, write_json)

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

    return total, failures


def main():
    args = [a for a in sys.argv[1:]]
    client = make_client()

    all_matches = client.get_matches(params={'competition_edition': COMPETITION_EDITION})

    # Fetched once and reused for every team, rather than per team.
    reference_loaders = [
        ('teams', lambda: client.get_teams(params={'competition_edition': COMPETITION_EDITION})),
        ('players', lambda: client.get_players(params={'competition_edition': COMPETITION_EDITION})),
        ('competition_editions', lambda: [
            e for e in client.get_competition_editions() if e['id'] == COMPETITION_EDITION
        ]),
        ('seasons', client.get_seasons),
    ]

    if args and args[0] == '--all':
        teams = sorted({m['home_team']['short_name'] for m in all_matches})
    elif args:
        teams = [args[0]]
    else:
        teams = [DEFAULT_TEAM]

    print(f'{len(all_matches)} matches in edition {COMPETITION_EDITION}; '
          f'{len(teams)} team(s) to download', flush=True)

    grand_total, all_failures = 0, []
    for t_i, team in enumerate(teams, 1):
        print(f'\n########## team {t_i}/{len(teams)} ##########', flush=True)
        total, failures = download_team(client, team, all_matches, reference_loaders)
        grand_total += total
        all_failures += [(team,) + f for f in failures]

    print(f'\ndownloaded {grand_total/1e9:.2f} GB this run across {len(teams)} team(s)', flush=True)
    if all_failures:
        print(f'{len(all_failures)} failures:', flush=True)
        for team, mid, sub, err in all_failures:
            print(f'  {team} {mid} {sub}: {err}', flush=True)
        return 1
    print('all files present', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
