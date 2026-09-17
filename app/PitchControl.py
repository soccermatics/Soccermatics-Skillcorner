#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pitch Control model adapted for SkillCorner long-format tracking data.

Pitch control (at a given location on the field) is the probability that a team
will gain possession if the ball is moved to that location.

Methodology: "Off the ball scoring opportunities" by William Spearman (2018)
http://www.sloansportsconference.com/wp-content/uploads/2018/02/2002.pdf

Original implementation: Laurie Shaw (@EightyFivePoint)
Adapted for SkillCorner long-format data (player_id, x, y, vx, vy per row).

Functions
----------
default_model_params()           - returns default model parameters
initialise_players()             - creates player objects from a long-format team DataFrame
generate_pitch_control_for_frame() - computes pitch control surface for a single frame
calculate_pitch_control_at_target() - pitch control probability at one grid point

Classes
-------
player - stores position, velocity, and pitch control contributions for one player
"""

import numpy as np


def initialise_players(df_team, teamname, params, GKid):
    """
    Create a list of player objects from a long-format team DataFrame.

    Parameters
    ----------
    df_team   : DataFrame filtered to one team for a single frame.
                Required columns: player_id, x, y, vx, vy, is_detected
    teamname  : 'Home' or 'Away'
    params    : model parameters dict (from default_model_params())
    GKid      : player_id of the goalkeeper for this team

    Returns
    -------
    team_players : list of player objects that are in-frame
    """
    team_players = []
    for _, row in df_team.iterrows():
        p = player(row, teamname, params, GKid)
        if p.inframe:
            team_players.append(p)
    return team_players

def check_offsides( attacking_players, defending_players, ball_position, GK_numbers, verbose=False, tol=0.2):
    """
    check_offsides( attacking_players, defending_players, ball_position, GK_numbers, verbose=False, tol=0.2):
    
    checks whetheer any of the attacking players are offside (allowing for a 'tol' margin of error). Offside players are removed from 
    the 'attacking_players' list and ignored in the pitch control calculation.
    
    Parameters
    -----------
        attacking_players: list of 'player' objects (see player class above) for the players on the attacking team (team in possession)
        defending_players: list of 'player' objects (see player class above) for the players on the defending team
        ball_position: Current position of the ball (start position for a pass). If set to NaN, function will assume that the ball is already at the target position.
        GK_numbers: tuple containing the player id of the goalkeepers for the (home team, away team)
        verbose: if True, print a message each time a player is found to be offside
        tol: A tolerance parameter that allows a player to be very marginally offside (up to 'tol' m) without being flagged offside. Default: 0.2m
            
    Returrns
    -----------
        attacking_players: list of 'player' objects for the players on the attacking team with offside players removed
    """    
    # find jersey number of defending goalkeeper (just to establish attack direction)
    defending_GK_id = GK_numbers[1] if attacking_players[0].teamname=='Home' else GK_numbers[0]
    # make sure defending goalkeeper is actually on the field!
    assert defending_GK_id in [p.id for p in defending_players], "Defending goalkeeper jersey number not found in defending players"
    # get goalkeeper player object
    defending_GK = [p for p in defending_players if p.id==defending_GK_id][0]  
    # use defending goalkeeper x position to figure out which half he is defending (-1: left goal, +1: right goal)
    defending_half = np.sign(defending_GK.position[0])
    # find the x-position of the second-deepest defeending player (including GK)
    second_deepest_defender_x = sorted( [defending_half*p.position[0] for p in defending_players], reverse=True )[1]
    # define offside line as being the maximum of second_deepest_defender_x, ball position and half-way line
    offside_line = max(second_deepest_defender_x,defending_half*ball_position[0],0.0)+tol
    # any attacking players with x-position greater than the offside line are offside
    if verbose:
        for p in attacking_players:
            if p.position[0]*defending_half>offside_line:
                print("player %s in %s team is offside" % (p.id, p.playername) )
    attacking_players = [p for p in attacking_players if p.position[0]*defending_half<=offside_line]
    return attacking_players

class player(object):
    """
    Stores position, velocity, time-to-intercept and pitch control contributions
    for a single player.

    Parameters
    ----------
    row      : pandas Series with columns player_id, x, y, vx, vy, is_detected
    teamname : 'Home' or 'Away'
    params   : model parameters dict
    GKid     : player_id of the goalkeeper for this team
    """
    def __init__(self, row, teamname, params, GKid):
        self.id = row['player_id']
        self.is_gk = self.id == GKid
        self.teamname = teamname
        self.vmax = params['max_player_speed']
        self.reaction_time = params['reaction_time']
        self.tti_sigma = params['tti_sigma']
        self.lambda_att = params['lambda_att']
        self.lambda_def = params['lambda_gk'] if self.is_gk else params['lambda_def']
        self.get_position(row)
        self.get_velocity(row)
        self.PPCF = 0.

    def get_position(self, row):
        self.position = np.array([row['x'], row['y']])
        self.inframe = bool(row.get('is_detected', True)) and not np.any(np.isnan(self.position))

    def get_velocity(self, row):
        vx = row.get('vx', 0.)
        vy = row.get('vy', 0.)
        self.velocity = np.array([vx if not np.isnan(vx) else 0.,
                                   vy if not np.isnan(vy) else 0.])
    
    def simple_time_to_intercept(self, r_final):
        self.PPCF = 0. # initialise this for later
        # Time to intercept assumes that the player continues moving at current velocity for 'reaction_time' seconds
        # and then runs at full speed to the target position.
        r_reaction = self.position + self.velocity*self.reaction_time
        self.time_to_intercept = self.reaction_time + np.linalg.norm(r_final-r_reaction)/self.vmax
        return self.time_to_intercept

    def probability_intercept_ball(self,T):
        # probability of a player arriving at target location at time 'T' given their expected time_to_intercept (time of arrival), as described in Spearman 2018
        f = 1/(1. + np.exp( -np.pi/np.sqrt(3.0)/self.tti_sigma * (T-self.time_to_intercept) ) )
        return f

""" Generate pitch control map """

def default_model_params(time_to_control_veto=3):
    """
    default_model_params()
    
    Returns the default parameters that define and evaluate the model. See Spearman 2018 for more details.
    
    Parameters
    -----------
    time_to_control_veto: If the probability that another team or player can get to the ball and control it is less than 10^-time_to_control_veto, ignore that player.
    
    
    Returns
    -----------
    
    params: dictionary of parameters required to determine and calculate the model
    
    """
    # key parameters for the model, as described in Spearman 2018
    params = {}
    # model parameters
    params['max_player_accel'] = 7. # maximum player acceleration m/s/s, not used in this implementation
    params['max_player_speed'] = 5. # maximum player speed m/s
    params['reaction_time'] = 0.7 # seconds, time taken for player to react and change trajectory. Roughly determined as vmax/amax
    params['tti_sigma'] = 0.45 # Standard deviation of sigmoid function in Spearman 2018 ('s') that determines uncertainty in player arrival time
    params['kappa_def'] =  1. # kappa parameter in Spearman 2018 (=1.72 in the paper) that gives the advantage defending players to control ball, I have set to 1 so that home & away players have same ball control probability
    params['lambda_att'] = 4.3 # ball control parameter for attacking team
    params['lambda_def'] = 4.3 * params['kappa_def'] # ball control parameter for defending team
    params['lambda_gk'] = params['lambda_def']*3.0 # make goal keepers must quicker to control ball (because they can catch it)
    params['average_ball_speed'] = 15. # average ball travel speed in m/s
    # numerical parameters for model evaluation
    params['int_dt'] = 0.04 # integration timestep (dt)
    params['max_int_time'] = 10 # upper limit on integral time
    params['model_converge_tol'] = 0.01 # assume convergence when PPCF>0.99 at a given location.
    # The following are 'short-cut' parameters. We do not need to calculated PPCF explicitly when a player has a sufficient head start. 
    # A sufficient head start is when the a player arrives at the target location at least 'time_to_control' seconds before the next player
    params['time_to_control_att'] = time_to_control_veto*np.log(10) * (np.sqrt(3)*params['tti_sigma']/np.pi + 1/params['lambda_att'])
    params['time_to_control_def'] = time_to_control_veto*np.log(10) * (np.sqrt(3)*params['tti_sigma']/np.pi + 1/params['lambda_def'])
    return params

def generate_pitch_control_for_frame(
    df_frame, home_team_id, attacking_team_id, ball_pos, params, GK_numbers,
    field_dimen=(106., 68.), n_grid_cells_x=50
):
    """
    Compute pitch control surface for a single frame using SkillCorner long-format data.

    Parameters
    ----------
    df_frame           : DataFrame for one frame (player rows only, no ball row).
                         Required columns: player_id, team_id, x, y, vx, vy, is_detected
    home_team_id       : team_id of the home team (used to assign 'Home'/'Away' labels)
    attacking_team_id  : team_id of the team currently in possession
    ball_pos           : np.array([x, y]) — current ball position
    params             : model parameters dict (from default_model_params())
    GK_numbers         : tuple (home_gk_player_id, away_gk_player_id)
    field_dimen        : (length, width) of the pitch in metres. Default (106, 68)
    n_grid_cells_x     : number of grid cells along the x-axis. Default 50.

    Returns
    -------
    PPCFa  : 2-D array (n_grid_cells_y × n_grid_cells_x) of attacking team pitch control
    xgrid  : 1-D array of x positions of grid cell centres
    ygrid  : 1-D array of y positions of grid cell centres
    """
    away_team_id = df_frame.loc[df_frame['team_id'] != home_team_id, 'team_id'].iloc[0] \
        if len(df_frame[df_frame['team_id'] != home_team_id]) > 0 else None

    df_home = df_frame[df_frame['team_id'] == home_team_id]
    df_away = df_frame[df_frame['team_id'] != home_team_id]

    # Build grid
    n_grid_cells_y = int(n_grid_cells_x * field_dimen[1] / field_dimen[0])
    dx = field_dimen[0] / n_grid_cells_x
    dy = field_dimen[1] / n_grid_cells_y
    xgrid = np.arange(n_grid_cells_x) * dx - field_dimen[0] / 2. + dx / 2.
    ygrid = np.arange(n_grid_cells_y) * dy - field_dimen[1] / 2. + dy / 2.

    PPCFa = np.zeros(shape=(len(ygrid), len(xgrid)))
    PPCFd = np.zeros(shape=(len(ygrid), len(xgrid)))

    # Initialise player objects
    if attacking_team_id == home_team_id:
        attacking_players = initialise_players(df_home, 'Home', params, GK_numbers[0])
        defending_players = initialise_players(df_away, 'Away', params, GK_numbers[1])
    else:
        attacking_players = initialise_players(df_away, 'Away', params, GK_numbers[1])
        defending_players = initialise_players(df_home, 'Home', params, GK_numbers[0])

    if len(attacking_players) == 0 or len(defending_players) == 0:
        return PPCFa, xgrid, ygrid

    # Compute pitch control at each grid cell
    for i in range(len(ygrid)):
        for j in range(len(xgrid)):
            target_position = np.array([xgrid[j], ygrid[i]])
            PPCFa[i, j], PPCFd[i, j] = calculate_pitch_control_at_target(
                target_position, attacking_players, defending_players, ball_pos, params
            )

    checksum = np.sum(PPCFa + PPCFd) / float(n_grid_cells_y * n_grid_cells_x)
    if 1 - checksum >= params['model_converge_tol']:
        print(f"Pitch control: convergence warning (checksum error = {1 - checksum:.3f})")
    return PPCFa, xgrid, ygrid

def calculate_pitch_control_at_target(target_position, attacking_players, defending_players, ball_start_pos, params):
    """ calculate_pitch_control_at_target
    
    Calculates the pitch control probability for the attacking and defending teams at a specified target position on the ball.
    
    Parameters
    -----------
        target_position: size 2 numpy array containing the (x,y) position of the position on the field to evaluate pitch control
        attacking_players: list of 'player' objects (see player class above) for the players on the attacking team (team in possession)
        defending_players: list of 'player' objects (see player class above) for the players on the defending team
        ball_start_pos: Current position of the ball (start position for a pass). If set to NaN, function will assume that the ball is already at the target position.
        params: Dictionary of model parameters (default model parameters can be generated using default_model_params() )
        
    Returrns
    -----------
        PPCFatt: Pitch control probability for the attacking team
        PPCFdef: Pitch control probability for the defending team ( 1-PPCFatt-PPCFdef <  params['model_converge_tol'] )

    """
    # calculate ball travel time from start position to end position.
    if ball_start_pos is None or any(np.isnan(ball_start_pos)): # assume that ball is already at location
        ball_travel_time = 0.0 
    else:
        # ball travel time is distance to target position from current ball position divided assumed average ball speed
        ball_travel_time = np.linalg.norm( target_position - ball_start_pos )/params['average_ball_speed']
    
    # first get arrival time of 'nearest' attacking player (nearest also dependent on current velocity)
    tau_min_att = np.nanmin( [p.simple_time_to_intercept(target_position) for p in attacking_players] )
    tau_min_def = np.nanmin( [p.simple_time_to_intercept(target_position ) for p in defending_players] )
    
    # check whether we actually need to solve equation 3
    if tau_min_att-max(ball_travel_time,tau_min_def) >= params['time_to_control_def']:
        # if defending team can arrive significantly before attacking team, no need to solve pitch control model
        return 0., 1.
    elif tau_min_def-max(ball_travel_time,tau_min_att) >= params['time_to_control_att']:
        # if attacking team can arrive significantly before defending team, no need to solve pitch control model
        return 1., 0.
    else: 
        # solve pitch control model by integrating equation 3 in Spearman et al.
        # first remove any player that is far (in time) from the target location
        attacking_players = [p for p in attacking_players if p.time_to_intercept-tau_min_att < params['time_to_control_att'] ]
        defending_players = [p for p in defending_players if p.time_to_intercept-tau_min_def < params['time_to_control_def'] ]
        # set up integration arrays
        dT_array = np.arange(ball_travel_time-params['int_dt'],ball_travel_time+params['max_int_time'],params['int_dt']) 
        PPCFatt = np.zeros_like( dT_array )
        PPCFdef = np.zeros_like( dT_array )
        # integration equation 3 of Spearman 2018 until convergence or tolerance limit hit (see 'params')
        ptot = 0.0
        i = 1
        while 1-ptot>params['model_converge_tol'] and i<dT_array.size: 
            T = dT_array[i]
            for player in attacking_players:
                # calculate ball control probablity for 'player' in time interval T+dt
                dPPCFdT = (1-PPCFatt[i-1]-PPCFdef[i-1])*player.probability_intercept_ball( T ) * player.lambda_att
                # make sure it's greater than zero
                assert dPPCFdT>=0, 'Invalid attacking player probability (calculate_pitch_control_at_target)'
                player.PPCF += dPPCFdT*params['int_dt'] # total contribution from individual player
                PPCFatt[i] += player.PPCF # add to sum over players in the attacking team (remembering array element is zero at the start of each integration iteration)
            for player in defending_players:
                # calculate ball control probablity for 'player' in time interval T+dt
                dPPCFdT = (1-PPCFatt[i-1]-PPCFdef[i-1])*player.probability_intercept_ball( T ) * player.lambda_def
                # make sure it's greater than zero
                assert dPPCFdT>=0, 'Invalid defending player probability (calculate_pitch_control_at_target)'
                player.PPCF += dPPCFdT*params['int_dt'] # total contribution from individual player
                PPCFdef[i] += player.PPCF # add to sum over players in the defending team
            ptot = PPCFdef[i]+PPCFatt[i] # total pitch control probability 
            i += 1
        if i>=dT_array.size:
            print("Integration failed to converge: %1.3f" % (ptot) )
        return PPCFatt[i-1], PPCFdef[i-1]



    
