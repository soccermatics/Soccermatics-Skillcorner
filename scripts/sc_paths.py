"""Shared path helpers for the SkillCorner pipeline.

The downloader (``download_liverpool.py``) writes SkillCorner's raw payloads in a
layout that differs from the Real Madrid course folder in two ways:

* tracking is stored gzipped (``tracking/{id}.json.gz``, not ``tracking/{id}.json``)
* match metadata lives in ``match_metadata/``, not ``meta/``
* dynamic events are one CSV per event type under ``dynamic_events/<type>/``,
  rather than a single pre-merged ``dynamic/{id}.parquet``

These helpers hide those differences so the course scripts and the Streamlit app
can stay close to their originals.
"""
import gzip
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / 'data'

# Raw, as written by download_liverpool.py
RAW_TRACKING = 'tracking'
RAW_META = 'match_metadata'
RAW_DYNAMIC = 'dynamic_events'

# Derived, as consumed by the Streamlit app
DERIVED_DYNAMIC = 'dynamic'
DERIVED_FREEZE = 'freeze'
DERIVED_VELOCITIES = 'velocities'

# Event types merged into dynamic/{id}.parquet. phases_of_play is deliberately
# excluded: it has no `event_type` column, sits at a different granularity
# (phases, not events) and the app never reads it.
EVENT_TYPES = [
    'player_possessions',
    'off_ball_runs',
    'passing_options',
    'on_ball_engagements',
]


def team_dir(team: str) -> Path:
    """Directory holding one team's data, e.g. data/Liverpool."""
    return DATA_ROOT / team


def available_teams() -> list:
    """Team folders that contain at least one downloaded match."""
    if not DATA_ROOT.is_dir():
        return []
    teams = []
    for path in sorted(DATA_ROOT.iterdir()):
        if path.is_dir() and any((path / RAW_TRACKING).glob('*.json*')):
            teams.append(path.name)
    return teams


def match_ids(team: str) -> list:
    """Match ids with tracking data on disk, sorted by kickoff where known."""
    tracking = team_dir(team) / RAW_TRACKING
    ids = sorted({p.name.split('.')[0] for p in tracking.glob('*.json*')})
    return [int(i) for i in ids]


def load_tracking(team: str, match_id) -> list:
    """Read a tracking file, transparently handling .json.gz and .json."""
    base = team_dir(team) / RAW_TRACKING / str(match_id)
    gz = base.with_suffix('.json.gz')
    if gz.exists():
        with gzip.open(gz, 'rt', encoding='utf-8') as fh:
            return json.load(fh)
    plain = base.with_suffix('.json')
    with open(plain, encoding='utf-8') as fh:
        return json.load(fh)


def load_meta(team: str, match_id) -> dict:
    """Read a match metadata file."""
    with open(team_dir(team) / RAW_META / f'{match_id}.json', encoding='utf-8') as fh:
        return json.load(fh)
