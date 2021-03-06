"""
PID Controller

components:
    follow attitude commands
    gps commands and yaw
    waypoint following
"""
import numpy as np
from frame_utils import euler2RM
from math import sin, cos, fmod
import math

DRONE_MASS_KG = 0.5
GRAVITY = -9.81
MOI = np.array([0.005, 0.005, 0.01])
MAX_THRUST = 10.0
MAX_TORQUE = 1.0

class NonlinearController(object):

    def __init__(self):
        """Initialize the controller object and control gains"""
        delta = 1.0
        self.z_k_p = 64.0
        self.z_k_d = np.sqrt(self.z_k_p)*2*delta
        self.z_k_i = 1.0
        self.x_k_p = 0.5*5
        self.x_k_d = np.sqrt(self.x_k_p)*2*delta
        self.y_k_p = 0.5*5
        self.y_k_d = np.sqrt(self.y_k_p)*2*delta
        self.k_p_roll = 0.02
        self.k_p_pitch = 0.02
        self.k_p_yaw = 2.5
        self.k_p_p = 0.1*5
        self.k_p_q = 0.1*5
        self.k_p_r = 0.04*5

        self.z_error_sum =0.0
        return    

    def trajectory_control(self, position_trajectory, yaw_trajectory, time_trajectory, current_time):
        """Generate a commanded position, velocity and yaw based on the trajectory
        
        Args:
            position_trajectory: list of 3-element numpy arrays, NED positions
            yaw_trajectory: list yaw commands in radians
            time_trajectory: list of times (in seconds) that correspond to the position and yaw commands
            current_time: float corresponding to the current time in seconds
            
        Returns: tuple (commanded position, commanded velocity, commanded yaw)
                
        """

        ind_min = np.argmin(np.abs(np.array(time_trajectory) - current_time))
        time_ref = time_trajectory[ind_min]
        
        
        if current_time < time_ref:
            position0 = position_trajectory[ind_min - 1]
            position1 = position_trajectory[ind_min]
            
            time0 = time_trajectory[ind_min - 1]
            time1 = time_trajectory[ind_min]
            yaw_cmd = yaw_trajectory[ind_min - 1]
            
        else:
            yaw_cmd = yaw_trajectory[ind_min]
            if ind_min >= len(position_trajectory) - 1:
                position0 = position_trajectory[ind_min]
                position1 = position_trajectory[ind_min]
                
                time0 = 0.0
                time1 = 1.0
            else:

                position0 = position_trajectory[ind_min]
                position1 = position_trajectory[ind_min + 1]
                time0 = time_trajectory[ind_min]
                time1 = time_trajectory[ind_min + 1]
            
        position_cmd = (position1 - position0) * \
                        (current_time - time0) / (time1 - time0) + position0
        velocity_cmd = (position1 - position0) / (time1 - time0)
        
        
        return (position_cmd, velocity_cmd, yaw_cmd)
    
    def lateral_position_control(self, local_position_cmd, local_velocity_cmd, local_position, local_velocity,
                               acceleration_ff = np.array([0.0, 0.0])):
        """Generate horizontal acceleration commands for the vehicle in the local frame

        Args:
            local_position_cmd: desired 2D position in local frame [north, east]
            local_velocity_cmd: desired 2D velocity in local frame [north_velocity, east_velocity]
            local_position: vehicle position in the local frame [north, east]
            local_velocity: vehicle velocity in the local frame [north_velocity, east_velocity]
            acceleration_cmd: feedforward acceleration command
            
        Returns: desired vehicle 2D acceleration in the local frame [north, east]
        """
        x_c_dot_dot = self.x_k_p * (local_position_cmd[0] - local_position[0]) + self.x_k_d * (
                    local_velocity_cmd[0] - local_velocity[0]) + acceleration_ff[0]
        y_c_dot_dot = self.y_k_p * (local_position_cmd[1] - local_position)[1] + self.y_k_d * (
                    local_velocity_cmd[1] - local_velocity[1]) + acceleration_ff[1]

        #print(x_c_dot_dot,y_c_dot_dot)
        #print(local_position_cmd[0], local_position[0], local_velocity_cmd[0], local_velocity[0])
        #print(local_position_cmd[1],local_position[1] , local_velocity_cmd[1],local_velocity[1])

        return np.array([x_c_dot_dot, y_c_dot_dot])
    
    def altitude_control(self, altitude_cmd, vertical_velocity_cmd, altitude, vertical_velocity, attitude, acceleration_ff=0.0):
        """Generate vertical acceleration (thrust) command

        Args:
            altitude_cmd: desired vertical position (+up)
            vertical_velocity_cmd: desired vertical velocity (+up)
            altitude: vehicle vertical position (+up)
            vertical_velocity: vehicle vertical velocity (+up)
            attitude: the vehicle's current attitude, 3 element numpy array (roll, pitch, yaw) in radians
            acceleration_ff: feedforward acceleration command (+up)
            
        Returns: thrust command for the vehicle (+up)
        """
        self.z_error_sum += (altitude_cmd - altitude)

        u_bar = self.z_k_p * (altitude_cmd - altitude) + self.z_k_d * (
                    vertical_velocity_cmd - vertical_velocity) + self.z_k_i * self.z_error_sum + acceleration_ff

        #print(self.z_error_sum *self.z_k_i, u_bar)


        rot_mat = self.R(attitude)
        thrust_cmd = (u_bar +  GRAVITY)/ rot_mat[2, 2]
        thrust_cmd = np.clip(thrust_cmd, 0.1, MAX_THRUST / DRONE_MASS_KG)
        print(thrust_cmd)

        return thrust_cmd
        
    
    def roll_pitch_controller(self, acceleration_cmd, attitude, thrust_cmd):
        """ Generate the rollrate and pitchrate commands in the body frame
        
        Args:
            target_acceleration: 2-element numpy array (north_acceleration_cmd,east_acceleration_cmd) in m/s^2
            attitude: 3-element numpy array (roll, pitch, yaw) in radians
            thrust_cmd: vehicle thruts command in Newton
            
        Returns: 2-element numpy array, desired rollrate (p) and pitchrate (q) commands in radians/s
        """
        #print(thrust_cmd)
        rot_mat = self.R(attitude)
        R11 = rot_mat[0,0]
        R12 = rot_mat[0,1]
        R21 = rot_mat[1,0]
        R22 = rot_mat[1,1]
        R13 = rot_mat[0,2]
        R23 = rot_mat[1,2]
        R33 = rot_mat[2,2]
        b_x_c_dot = self.k_p_roll * (acceleration_cmd[0] / thrust_cmd - R13)
        b_y_c_dot = self.k_p_pitch * (acceleration_cmd[1] / thrust_cmd - R23)
        p_c = (R21*b_x_c_dot - R11*b_y_c_dot)/R33
        q_c = (R22*b_x_c_dot - R12*b_y_c_dot)/R33
        #print(p_c,q_c, b_x_c_dot,b_y_c_dot,acceleration_cmd[0],acceleration_cmd[1])
        return np.array([0.0,0.0])
        #p_c = np.clip(p_c, -50,50)
        #q_c = np.clip(p_c, -50,50)
        return np.array([-p_c,-q_c])



    
    def body_rate_control(self, body_rate_cmd, body_rate):
        """ Generate the roll, pitch, yaw moment commands in the body frame
        
        Args:
            body_rate_cmd: 3-element numpy array (p_cmd,q_cmd,r_cmd) in radians/second^2
            body_rate: 3-element numpy array (p,q,r) in radians/second^2
            
        Returns: 3-element numpy array, desired roll moment, pitch moment, and yaw moment commands in Newtons*meters
        """

        error_pqr = np.array(body_rate_cmd) - np.array(body_rate)
        control_gain = np.array([self.k_p_p,self.k_p_q,self.k_p_r])
        u_bar_pqr = control_gain * error_pqr

        return u_bar_pqr
    
    def yaw_control(self, yaw_cmd, yaw):
        """ Generate the target yawrate
            yaw_cmd: desired vehicle yaw in radians
            yaw: vehicle yaw in radians
        
        Returns: target yawrate in radians/sec
        """
        return self.k_p_yaw * fmod(yaw_cmd-yaw,math.pi)

    def R(self, attitude):
        """get rotation matrix"""
        # attitude: the vehicle's current attitude, 3 element numpy array (roll, pitch, yaw) in radians
        # return rotation_matrix
        phi, theta, psi = attitude

        Rx = np.array([[1, 0, 0],
                       [0, cos(phi), -sin(phi)],
                       [0, sin(phi), cos(phi)]
                       ])
        Ry = np.array([[cos(theta), 0, sin(theta)],
                       [0, 1, 0],
                       [-sin(theta), 0, cos(theta)]
                       ])
        Rz = np.array([[cos(psi), -sin(psi), 0],
                       [sin(psi), cos(psi), 0],
                       [0, 0, 1]
                       ])

        #print(attitude)

        return Rz @ (Ry @ Rx)