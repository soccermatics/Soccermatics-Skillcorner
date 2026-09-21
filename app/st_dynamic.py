"""
Created on Fri May  9 09:39:47 2025

This Streamlit application provides an interactive platform for analyzing dynamic events in soccer matches using SkillCorner data.
The focus is on exploring passing events, visualizing player positions, and understanding the context of each pass through associated events and freeze frames.

Features:
- Select matches from a list to analyze their events.
- Explore dynamic events, including passes, player possessions, and associated actions.
- Visualize freeze frames with player positions, jersey numbers, and ball locations.
- Highlight specific events such as passes, off-ball runs, and on-ball engagements on the pitch.

Use this tool to get to know the SkillCorner data better and understand how to interpret the events in a match context.

author: @gustimorth
"""

import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np
import json
from matplotlib.patches import Polygon as MplPolygon
from mplsoccer import Pitch
import PitchControl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sc_paths  # noqa: E402

st.set_page_config(page_title="SkillCorner Home Games", layout="wide")
st.title("SkillCorner Dynamic Events - Passing Exploration")

# Which team's home games to explore. Each data/<Team> folder holds that team's
# home matches, so the selection picks both the team and its match set.
teams = sc_paths.available_teams()
if not teams:
    st.error(
        "No downloaded data found under data/. "
        "Run `python scripts/download_liverpool.py` first."
    )
    st.stop()

default_team = "Liverpool" if "Liverpool" in teams else teams[0]
team = st.sidebar.selectbox(
    "Team (home matches)", teams, index=teams.index(default_team)
)
DATA_FOLDER = str(sc_paths.team_dir(team))
st.caption(f"{team} home matches - ENG Premier League 2025/2026")


# Load the data in functions so that it is cached.
# This means that the data is only loaded once and then stored in memory.
# The ttl argument is the time to live, which means that the data will be reloaded after the amount of seconds specified.
@st.cache_data(ttl=10 * 60)
def get_matches(data_folder):
    # Set the data path to the JSONL file. Needs to be specified from the root of all repositories
    # Create a label column from home_team and away_team (dictionaies with keys id and short_name)
    df_matches = pd.read_parquet(f"{data_folder}/matches.parquet")
    df_matches["Match"] = (
        df_matches["home_team"].apply(lambda x: x["short_name"])
        + " vs "
        + df_matches["away_team"].apply(lambda x: x["short_name"])
    )

    # Transform the date_time column
    df_matches["Date"] = df_matches["date_time"].apply(lambda x: x[:10])
    return df_matches


# Get the dynamic data from the parquet file
@st.cache_data(ttl=10 * 60)
def get_dynamic_data(data_folder, match_ids=[]):
    # Load the data from the parquet file
    df_data = pd.DataFrame()
    for match_id in match_ids:
        df_events = pd.read_parquet(f"{data_folder}/dynamic/{match_id}.parquet")
        df_data = pd.concat([df_data, df_events], ignore_index=True)
    return df_data


# Get the velocity data from the parquet file
@st.cache_data(ttl=10 * 60)
def get_velocities(data_folder, match_id):
    return pd.read_parquet(f"{data_folder}/velocities/{match_id}.parquet")


# Get the freeze frames from the parquet file
@st.cache_data(ttl=10 * 60)
def get_freeze_frames(data_folder, match_ids=[]):
    # Load the data from the parquet file
    df_data = pd.DataFrame()
    for match_id in match_ids:
        df_frames = pd.read_parquet(f"{data_folder}/freeze/{match_id}.parquet")
        # Add the match_id to the dataframe
        df_frames["match_id"] = match_id
        df_data = pd.concat([df_data, df_frames], ignore_index=True)
    return df_data


# Get the meta data from the json file and create a dataframe with the player information
@st.cache_data(ttl=10 * 60)
def get_meta_data(data_folder, match_id):
    # Load the data from the json file. The downloader stores match metadata
    # under match_metadata/ (SkillCorner's own naming), not the course's meta/.
    meta_path = f"{data_folder}/{sc_paths.RAW_META}/{match_id}.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        match_data = json.load(f)

    pitch_length = match_data["pitch_length"]
    pitch_width = match_data["pitch_width"]
    home_team_id = match_data["home_team"]["id"]
    away_team_id = match_data["away_team"]["id"]

    # Create a dataframe with the team information, inlcuding the jersey colors
    df_teams = pd.concat(
        [
            pd.DataFrame([match_data["away_team"]]),
            pd.DataFrame([match_data["home_team"]]),
        ],
        ignore_index=True,
    )
    df_colors = pd.concat(
        [
            pd.DataFrame([match_data["away_team_kit"]]),
            pd.DataFrame([match_data["home_team_kit"]]),
        ],
        ignore_index=True,
    )

    df_teams = df_teams.rename(columns={"id": "team_id", "short_name": "team_name"})
    df_teams = df_teams.merge(df_colors, on="team_id")
    df_teams = df_teams[["team_id", "team_name", "jersey_color", "number_color"]]

    # Create dataframe with player info
    df_players = pd.DataFrame(match_data["players"])
    # Add team information to the player dataframe
    df_players = df_players.rename(
        columns={"id": "player_id", "team_id": "team_id", "number": "jersey_number"}
    )
    # Merge the two dataframes
    df_players = pd.merge(df_players, df_teams, on="team_id", how="left")
    df_players = df_players[
        [
            "player_id",
            "jersey_number",
            "short_name",
            "team_id",
            "team_name",
            "jersey_color",
            "number_color",
        ]
    ]

    # Identify goalkeepers for each team
    gk_records = [
        p for p in match_data["players"]
        if p.get("player_role", {}).get("name") == "Goalkeeper"
    ]
    home_gk = next((p["id"] for p in gk_records if p["team_id"] == home_team_id), None)
    away_gk = next((p["id"] for p in gk_records if p["team_id"] == away_team_id), None)
    GK_numbers = (home_gk, away_gk)

    return pitch_length, pitch_width, df_players, home_team_id, away_team_id, GK_numbers


# Function to plot the frame
def plot_frame(df_frame, pitch_length, pitch_width, only_detected, df_events, show_velocities=True, PPCFa=None, xgrid=None, ygrid=None):
    pitch = Pitch(
        pitch_type="skillcorner", pitch_width=pitch_width, pitch_length=pitch_length
    )
    fig, ax = pitch.draw()

    # Overlay pitch control heatmap
    if PPCFa is not None and xgrid is not None and ygrid is not None:
        extent = [
            xgrid[0] - (xgrid[1] - xgrid[0]) / 2,
            xgrid[-1] + (xgrid[1] - xgrid[0]) / 2,
            ygrid[0] - (ygrid[1] - ygrid[0]) / 2,
            ygrid[-1] + (ygrid[1] - ygrid[0]) / 2,
        ]
        im = ax.imshow(
            PPCFa,
            extent=extent,
            origin="lower",
            cmap="RdBu_r",
            vmin=0, vmax=1,
            alpha=0.5,
            aspect="auto",
            zorder=1,
        )
        # Clip imshow to the visible area polygon if available
        visible_area = df_frame.visible_area.values[0]
        poly_pts = [
            (visible_area["x_top_left"],    visible_area["y_top_left"]),
            (visible_area["x_bottom_left"],  visible_area["y_bottom_left"]),
            (visible_area["x_bottom_right"], visible_area["y_bottom_right"]),
            (visible_area["x_top_right"],   visible_area["y_top_right"]),
        ]
        if all(v is not None for pt in poly_pts for v in pt):
            clip_patch = MplPolygon(poly_pts, closed=True, transform=ax.transData)
            ax.add_patch(clip_patch)
            clip_patch.set_visible(False)
            im.set_clip_path(clip_patch)

    if only_detected:
        df_frame = df_frame[df_frame["is_detected"]]
    # Plot the players
    ball_data = df_frame[df_frame["is_ball"]]
    player_data = df_frame[df_frame["is_ball"] == False]

    # Plot the ball points
    ax.scatter(ball_data["x"], ball_data["y"], s=50, color="black", zorder=6)

    # Plot the players
    ax.scatter(
        player_data["x"],
        player_data["y"],
        s=150,
        color=player_data["jersey_color"],
        edgecolor="black",
        zorder=5,
    )

    # Draw velocity vectors
    if show_velocities:
        vel = player_data[player_data["is_detected"] & player_data["vx"].notna()].copy()
        if len(vel) > 0:
            ax.quiver(
                vel["x"], vel["y"],
                vel["vx"], vel["vy"],
                color=vel["jersey_color"],
                scale=0.5,
                scale_units="xy",
                angles="xy",
                width=0.004,
                headwidth=4,
                headlength=4,
                zorder=8,
            )

    # Add jersey numbers on the players
    for _, row in player_data.iterrows():
        ax.text(
            row["x"],
            row["y"],
            str(int(row["jersey_number"])),
            color=row["number_color"],
            ha="center",
            va="center",
            fontsize=8,
            weight="bold",
            zorder=6,
        )

    # Retrieve the game time and period from the frame data
    df_frame["time"] = df_frame["time"].apply(
        lambda x: str(int(x.split(":")[0]) * 60 + int(x.split(":")[1]))
        + ":"
        + x.split(":")[2]
    )
    game_time = df_frame["time"].iloc[0][0:5]
    period = int(df_frame["period"].iloc[0])

    # Display the match label
    ax.text(
        0,
        pitch_width / 2 + 12,
        f"{df_matches[df_matches['id'] == match_id]['Match'].values[0]}",
        ha="center",
        va="center",
        fontsize=15,
        color="black",
        fontweight="bold",
    )
    # Display the game time and period on top of the pitch
    ax.text(
        0,
        pitch_width / 2 + 7,
        f"Period {period} - Time {game_time}",
        ha="center",
        va="center",
        fontsize=15,
        color="black",
    )

    # Show visible area polygon only when pitch control is not shown
    if PPCFa is None:
        visible_area = df_frame.visible_area.values[0]
        polygon_points = [
            (visible_area["x_top_left"], visible_area["y_top_left"]),
            (visible_area["x_bottom_left"], visible_area["y_bottom_left"]),
            (visible_area["x_bottom_right"], visible_area["y_bottom_right"]),
            (visible_area["x_top_right"], visible_area["y_top_right"]),
        ]
        if all(v is not None for pt in polygon_points for v in pt):
            pitch.polygon([polygon_points], color=(1, 0, 0, 0.3), ax=ax)

    # Plot the events
    # We need to flip the coordinates for the events for the team that is not attacking left to right
    coord_columns = [
        "x_start",
        "x_end",
        "player_targeted_x_pass",
        "player_targeted_x_reception",
        "y_start",
        "y_end",
        "player_targeted_y_pass",
        "player_targeted_y_reception",
    ]
    df_events.loc[df_events["attacking_side"] == "right_to_left", coord_columns] = (
        -1
        * df_events.loc[df_events["attacking_side"] == "right_to_left", coord_columns]
    )
    # Add columns for the current x and y coordinates of the players at the moment of the event
    df_events = df_events.merge(
        df_frame[["player_id", "x", "y"]].rename(
            columns={"x": "x_current_frame", "y": "y_current_frame"}
        ),
        on="player_id",
        how="left",
    )
    # Extract the event types
    df_pass = df_events[(df_events["end_type"] == "pass")]
    df_press = df_events[(df_events["event_type"] == "on_ball_engagement")]
    df_run = df_events[df_events["event_type"] == "off_ball_run"]
    df_passing_option = df_events[df_events["event_type"] == "passing_option"]

    # Draw the pass as an arrow
    if len(df_pass) > 0:
        pitch.arrows(
            df_pass.x_end,
            df_pass.y_end,
            (
                df_pass.player_targeted_x_reception
                if df_pass.pass_outcome.values[0] == "successful"
                else df_pass.player_targeted_x_pass
            ),
            (
                df_pass.player_targeted_y_reception
                if df_pass.pass_outcome.values[0] == "successful"
                else df_pass.player_targeted_y_pass
            ),
            width=2,
            headwidth=4,
            headlength=6,
            color="black",
            label="Pass",
            zorder=7,
            ax=ax,
        )

    # Draw the off ball run as an arrow
    if len(df_run) > 0:
        pitch.arrows(
            df_run.x_current_frame,
            df_run.y_current_frame,
            df_run.x_end,
            df_run.y_end,
            width=1,
            headwidth=4,
            headlength=6,
            color="gray",
            label="Off ball run",
            zorder=7,
            ax=ax,
        )

    if len(df_press) > 0:
        # Draw an unfilled red circle for the press
        ax.scatter(
            df_press.x_current_frame,
            df_press.y_current_frame,
            s=200,
            edgecolor="red",
            facecolor="none",
            label="On ball engagement",
            zorder=1,
        )

    if len(df_passing_option) > 0:
        # Draw an unfilled blue circle for the passing option
        ax.scatter(
            df_passing_option.x_current_frame,
            df_passing_option.y_current_frame,
            s=200,
            edgecolor="blue",
            facecolor="none",
            label="Passing option",
            zorder=7,
        )

    # Add a legend to the plot
    ax.legend(
        loc="upper center",
        fontsize=7,
        frameon=False,
        ncol=4,  # Arrange the legend items in a single horizontal row
        bbox_to_anchor=(0.5, -0.02),  # Position the legend below the plot
    )

    return fig, ax


df_matches = get_matches(DATA_FOLDER)

# One match at a time, chosen in the sidebar. This used to be a multi-row
# dataframe selection, which concatenated the events of every selected match --
# so a pass from a previously selected fixture could still be picked, and the
# plot would then correctly show that other fixture. A single-select dropdown
# removes the ambiguity.
match_labels = [
    f"{row.Date}  {row.Match}" for row in df_matches.itertuples()
]
match_label = st.sidebar.selectbox("Match", match_labels, index=0)
match_row = df_matches.iloc[match_labels.index(match_label)]
match_id = match_row["id"]

selected_match_ids = [match_id]
df_events = get_dynamic_data(DATA_FOLDER, selected_match_ids)

st.subheader(f"{match_row['Match']} - {match_row['Date']}")
with st.expander("Dynamic events", expanded=False):
    st.dataframe(df_events)

# Filter out the passes
df_player_possessions = df_events[
    (df_events["event_type"] == "player_possession") & (df_events["end_type"] == "pass")
]

st.write("Select a pass:")
selected_event = st.dataframe(
    df_player_possessions.dropna(
        axis=1, how="all"
    ),  # Drop all columns that only contain NaN values
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    # Keyed on the match so switching fixture clears the previous row selection
    # instead of carrying a stale row index into the new pass list.
    key=f"pass_table_{team}_{match_id}",
)

selected_event = df_player_possessions.iloc[selected_event["selection"]["rows"]]
if len(selected_event) == 0:
    st.info("Select a pass to proceed with the analysis.")
    st.stop()
# Get the event_id of the selected event (match_id comes from the sidebar choice)
event_id = selected_event.event_id.values[0]

# Get the event itself
df_event = df_player_possessions[
    (df_player_possessions["event_id"] == event_id)
    & (df_player_possessions["match_id"] == match_id)
]
# Extract the associated events based on the event_id and match_id
# Only keep the events that are still applicable at the moment of the pass
df_associated_events = df_events[
    (df_events["associated_player_possession_event_id"] == event_id)
    & (df_events["match_id"] == match_id)
    & (df_events["frame_end"] >= selected_event.frame_end.values[0])
]


# Concatenate the two dataframes
df_event = pd.concat([df_event, df_associated_events], ignore_index=True)

st.write("Select the events to add to the plot:")
dynamic_events = st.dataframe(
    df_event,
    hide_index=True,
    on_select="rerun",
    selection_mode="multi-row",
    key=f"assoc_events_{team}_{match_id}_{event_id}",
)
# Extract the selected events
df_events_to_plot = df_event.iloc[dynamic_events["selection"]["rows"]]


# Get the freeze frames for the selected match
df_freeze_frames = get_freeze_frames(DATA_FOLDER, selected_match_ids)

# Get the freeze frame for the selected event. Here I take the end frame of the event
df_frame = df_freeze_frames[
    (df_freeze_frames["frame"] == selected_event.frame_end.values[0])
    & (df_freeze_frames["match_id"] == match_id)
]

# Plot the frame
# In SkillCorner the Pitch coordinates are in meters, so we need to know the pitch size
# Get the meta data for the match
pitch_length, pitch_width, df_players, home_team_id, away_team_id, GK_numbers = get_meta_data(
    DATA_FOLDER, match_id
)

# Add the player information to the frame
df_frame = df_frame.merge(
    df_players,
    left_on=["player_id"],
    right_on=["player_id"],
    how="left",
)

# Merge vx/vy from velocities into df_frame
df_velocities = get_velocities(DATA_FOLDER, match_id)
df_vel = df_velocities[df_velocities["frame"] == selected_event.frame_end.values[0]][["player_id", "vx", "vy", "speed"]]
df_frame = df_frame.merge(df_vel, on="player_id", how="left")

with st.expander("Frame data", expanded=False):
    st.dataframe(df_frame, hide_index=True)

only_detected = st.checkbox(
    "Show only detected players",
    value=False,
    key="only_detected",
    help="If checked, only the detected players will be shown.",
)
show_velocities = st.checkbox(
    "Show velocity vectors",
    value=True,
    key="show_velocities",
    help="Draw arrows showing each player's speed and direction of movement.",
)
show_pitch_control = st.checkbox(
    "Show pitch control",
    value=False,
    key="show_pitch_control",
    help="Overlay pitch control surface (red = attacking team, blue = defending team). Takes ~1-2 seconds.",
)

# Compute pitch control if requested
PPCFa = xgrid = ygrid = None
if show_pitch_control:
    ball_row = df_frame[df_frame["is_ball"] == True]
    ball_pos = np.array([ball_row["x"].values[0], ball_row["y"].values[0]]) \
        if len(ball_row) > 0 else np.array([np.nan, np.nan])
    attacking_team_id = selected_event["team_id"].values[0]
    df_players_only = df_frame[df_frame["is_ball"] == False].copy()
    params = PitchControl.default_model_params()
    with st.spinner("Computing pitch control..."):
        PPCFa, xgrid, ygrid = PitchControl.generate_pitch_control_for_frame(
            df_frame=df_players_only,
            home_team_id=home_team_id,
            attacking_team_id=attacking_team_id,
            ball_pos=ball_pos,
            params=params,
            GK_numbers=GK_numbers,
            field_dimen=(pitch_length, pitch_width),
        )

# Plot the pitch
fig, ax = plot_frame(
    df_frame,
    pitch_length,
    pitch_width,
    only_detected=only_detected,
    df_events=df_events_to_plot,
    show_velocities=show_velocities,
    PPCFa=PPCFa,
    xgrid=xgrid,
    ygrid=ygrid,
)
st.pyplot(fig)
fig.clear()
