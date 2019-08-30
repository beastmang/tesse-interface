import xml.etree.ElementTree as ET
import numpy as np
import copy

from scipy.spatial.transform import Rotation

from sensor_msgs.msg import CameraInfo, Imu
from nav_msgs.msg import Odometry
import tf.transformations

from tesse_ros_bridge import enu_T_unity, brh_T_blh, blh_T_brh, gravity_enu

def parse_metadata(data):
    """ Parse Unity agent metadata into a useful dictionary.

        Args:
            data: A decoded string representing the xml metadata from Unity.

        Returns:
            A dictionary with the following metadata members:
            'position': Agent position in world frame as a list.
            'quaternion': Agent rotation in world frame as a list.
            'velocity': Agent velocity in body frame as a list. # TODO verify
            'ang_vel': Agent angular velocity in body frame as a list. # TODO verify
            'acceleration': Agent linear acceleration in body frame as a list. # TODO verify
            'ang_accel': Agent angular acceleration in body frame as a list. # TODO verify
            'time': Unity simulator time of the metadata.
            'collision_status': Bool that is true if agent is collided with
                an object in the environment.
    """
    # TODO: find a nicer way to traverse the tree
    root = ET.fromstring(data)
    dict = {}

    dict['position'] = [float(root[0].attrib['x']),
                        float(root[0].attrib['y']),
                        float(root[0].attrib['z'])]
    dict['quaternion'] = [float(root[1].attrib['x']),
                          float(root[1].attrib['y']),
                          float(root[1].attrib['z']),
                          float(root[1].attrib['w'])]
    dict['velocity'] = [float(root[2].attrib['x_dot']),
                        float(root[2].attrib['y_dot']),
                        float(root[2].attrib['z_dot'])]
    dict['ang_vel'] = [(float(root[3].attrib['x_ang_dot'])),
                       (float(root[3].attrib['y_ang_dot'])),
                       (float(root[3].attrib['z_ang_dot']))]
    dict['acceleration'] = [float(root[4].attrib['x_ddot']),
                            float(root[4].attrib['y_ddot']),
                            float(root[4].attrib['z_ddot'])]
    dict['ang_accel'] = [(float(root[5].attrib['x_ang_ddot'])),
                         (float(root[5].attrib['y_ang_ddot'])),
                         (float(root[5].attrib['z_ang_ddot']))]
    dict['time'] = float(root[6].text)
    dict['collision_status'] = False if root[7].attrib['status'] == 'false' \
        else True

    return dict


def parse_cam_data(data):
    """ Parse CameraInformationRequest data into a useful dictionary

        Args:
            data: A decoded string representing the xml
                CameraInformationRequest metadata from Unity.

        Returns:
            A dictionary with the following metadata members:
                'name': A string representing The name of the camera.
                'id': An integer representing the camera ID in the simulator.
                'parameters': A dictionary of three floats, representing camera
                    width, height, and FOV.
                'position': A list of floats representing the camera's position
                    relative to the body frame of the agent.
                'quaternion': A list of floats representing the camera's
                    rotation relative to the body frame of the agent.
                'draw_distance': A dictionary with two elements:
                    'far': A float representing the simulator's 'far' draw
                        distance.
                    'near': A float representing the simulator's 'near' draw
                        distance.

    """
    # TODO: find a nicer way to traverse the tree that isn't dependent
    # on idices not changing over time.
    root = ET.fromstring(data)
    dict = {}

    dict['name'] = str(root[0][0].text)

    dict['id'] = int(root[0][1].text)

    dict['parameters'] = {'width':int(root[0][2].attrib['width']),
                          'height':int(root[0][2].attrib['height']),
                          'fov':float(root[0][2].attrib['fov'])}
    dict['position'] = [float(root[0][3].attrib['x']),
                        float(root[0][3].attrib['y']),
                        float(root[0][3].attrib['z'])]
    dict['quaternion'] = [float(root[0][4].attrib['x']),
                          float(root[0][4].attrib['y']),
                          float(root[0][4].attrib['z']),
                          float(root[0][4].attrib['w'])]
    dict['draw_distance'] = {'far':float(root[0][5].attrib['far']),
                             'near':float(root[0][5].attrib['near'])}

    return dict


def metadata_to_odom(metadata, timestamp, frame_id, child_frame_id):
    """ Converts a metadata dictionary to a ROS odometry message.

        Args:
            metadata: A dictionary containing agent metadata parsed from Unity
                AND pre-processed to be converted to the correct frame.
            timestamp: A rospy.Time instance for the ROS Odom message instance.
            frame_id: A string representing the reference frame (world frame).

        Returns:
            An Odom ROS message instance that can immediately be published.
    """
    odom = Odometry()
    odom.header.stamp = timestamp
    odom.header.frame_id = frame_id
    odom.child_frame_id = child_frame_id

    # Pose is in the ENU world frame.
    odom.pose.pose.position.x =  metadata['position'][0]
    odom.pose.pose.position.y =  metadata['position'][1]
    odom.pose.pose.position.z =  metadata['position'][2]

    odom.pose.pose.orientation.x = metadata['quaternion'][0]
    odom.pose.pose.orientation.y = metadata['quaternion'][1]
    odom.pose.pose.orientation.z = metadata['quaternion'][2]
    odom.pose.pose.orientation.w = metadata['quaternion'][3]

    # Twist is in the body frame (camera/imu).
    odom.twist.twist.linear.x = metadata['velocity'][0]
    odom.twist.twist.linear.y = metadata['velocity'][1]
    odom.twist.twist.linear.z = metadata['velocity'][2]

    odom.twist.twist.angular.x = metadata['ang_vel'][0]
    odom.twist.twist.angular.y = metadata['ang_vel'][1]
    odom.twist.twist.angular.z = metadata['ang_vel'][2]

    return odom


def metadata_to_imu(processed_metadata, timestamp, frame_id):
    """ Transforms a metadata dictionary to a ROS imu message.

        Converts the metadata to the agent body frame (a right-handed-frame),
        adds a constant gravity value to the linear acceleration fields of the
        provided metadata, and then builds a ROS Imu message instance.

        Args:
            metadata: A dictionary containing agent metadata parsed from Unity
                AND pre-processed to be converted to the correct frame.
            timestamp: A rospy.Time instance for the ROS Imu message instance.
            frame_id: A string representing the reference frame (body frame).

        Returns:
            An Imu ROS message instance that can immediately be published.
    """
    imu = Imu()
    imu.header.stamp = timestamp
    imu.header.frame_id = frame_id

    # All fields are in the agent body frame
    imu.angular_velocity.x = processed_metadata['ang_vel'][0]
    imu.angular_velocity.y = processed_metadata['ang_vel'][1]
    imu.angular_velocity.z = processed_metadata['ang_vel'][2]

    enu_R_brh = processed_metadata['transform'][:3,:3]
    g_brh = np.transpose(enu_R_brh).dot(gravity_enu)

    imu.linear_acceleration.x = processed_metadata['acceleration'][0] - g_brh[0]
    imu.linear_acceleration.y = processed_metadata['acceleration'][1] - g_brh[1]
    imu.linear_acceleration.z = processed_metadata['acceleration'][2] - g_brh[2]

    return imu


def generate_camera_info(left_cam_data, right_cam_data):
    """ Generates CameraInfo messages for left-cam and right-cam.

        Using provided camera intrinsics, first parses CameraInformationRequest
        objects into useful dictionaries and then builds CameraInfo ROS
        messages for both the left camera and the right camera independently.

        Args:
            left_cam_data: A dictionary containing parsed data for left cam.
            right_cam_data: A dictionary containing parsed data for right cam.
            camera_fov: A float representing the camera's desired field-of-view.
            camera_width: A float representing the image width, in pixels.
            camera_height: A float representing the image height, in pixels.

        Returns:
            A tuple containing the left camera's CameraInfo message and the
            right camera's CameraInfo message, in that order.
    """
    # Parameters must be the same for left and right cameras:
    width_left         = left_cam_data['parameters']['width']
    height_left        = left_cam_data['parameters']['height']
    fov_vertical_left  = left_cam_data['parameters']['fov']

    width_right        = right_cam_data['parameters']['width']
    height_right       = right_cam_data['parameters']['height']
    fov_vertical_right = right_cam_data['parameters']['fov']

    assert(width_left == width_right)
    assert(height_left == height_right)
    assert(fov_vertical_left == fov_vertical_right)

    # Required for Unity FOV scaling:
    assert(height_left > 0)
    assert(width_left > 0)

    # TODO(Toni): do unit tests for these conversions!!
    # ACCORDING TO UNITY (and this is the param we are actually changing)
    # """ The field of view of the camera in degrees.
    # This is the vertical field of view; horizontal Field of view varies depending on the viewport's aspect ratio.
    # """ Unity docs:  https://docs.unity3d.com/ScriptReference/Camera-fieldOfView.html
    # Also: according to Unity, the fov starts at 60:
    # //Start the Camera field of view at 60
    #  m_FieldOfView = 60.0f;
    # And they provide an OnGUI function to change that with a slider it seems.
    # TODO(Toni): Unity modifies horizontal accordingly! CHECK THAT THE FORMULAS MATCH!!
    # If we do not guess Unity's fov_horizontal correctly it will definitely break the VIO
    fov_horizontal_left = np.rad2deg(2.0 * np.arctan(np.tan(np.deg2rad(fov_vertical_left) / 2.0) * width_left / height_left))
    fx = (width_left  / 2.0) / np.tan(np.deg2rad(fov_horizontal_left) / 2.0)
    fy = (height_left / 2.0) / np.tan(np.deg2rad(fov_vertical_left)   / 2.0)

    print("FX:", fx)
    print("FY:", fy)

    # We only want to work with square pixels
    assert(fx == fy)

    # ** // is doing Floor division **: Divides and returns the integer value of the quotient.
    #  It dumps the digits after the decimal.
    cx = width_left  / 2  # pixels
    cy = height_left / 2 # pixels
    assert(cx == width_left  // 2)
    assert(cy == height_left // 2)

    print("CX:", cx)
    print("CY:", cy)

    # TODO(Toni): not necessarily! This is hardcoded!!
    baseline = np.abs(left_cam_data['position'][0] - right_cam_data['position'][0])

    print("Baseline: ", baseline)

    # assert(baseline == self.stereo_baseline)  # TODO(marcus): put somewhere
    # TODO(Toni): unit-test that!
    Tx = 0
    Ty = 0
    Tx_right = -fx * baseline

    cam_info_msg_left = make_camera_info_msg("left_cam",
                                             width_left,
                                             height_left,
                                             fx, fy, cx, cy, Tx, Ty)
    cam_info_msg_right = make_camera_info_msg("right_cam",
                                             width_left,
                                             height_left,
                                             fx, fy, cx, cy, Tx_right, Ty)

    return (cam_info_msg_left, cam_info_msg_right)


# TODO(Toni): unit-test this!
def make_camera_info_msg(frame_id, width, height, fx, fy, cx, cy, Tx, Ty):
    """ Create a CameraInfo ROS message from parameters.
        Following convention in: 
            http://docs.ros.org/melodic/api/sensor_msgs/html/msg/CameraInfo.html

        Header header    # Header timestamp should be acquisition time of image
                        # Header frame_id should be optical frame of camera
                        # origin of frame should be optical center of camera
                        # +x should point to the right in the image
                        # +y should point down in the image
                        # +z should point into the plane of the image


        Args:
            frame_id: A string representing the reference frame of the
                CameraInfo message, which should be the body frame.
            width: A float representing the image width of the camera.
            height: A float representing the image height of the camera.
            fx: A float representing horizontal focal length.
            fy: A float representing vertical focal length.
            cx: An integer representing the principle point x-coordinate.
            cy: An integer representing the principle point y-coordinate.
            Tx: TODO document
            Ty: TODO document

        Returns:
            A Ros CameraInfo message instance.

    """
    camera_info_msg                 = CameraInfo()
    camera_info_msg.header.frame_id = frame_id
    camera_info_msg.width           = width
    camera_info_msg.height          = height
    camera_info_msg.K = [fx, 0, cx,
                         0, fy, cy,
                         0, 0, 1]
    # No rectification
    camera_info_msg.R = [1, 0, 0,
                         0, 1, 0,
                         0, 0, 1]
    # No distortion
    camera_info_msg.distortion_model = "plumb_bob"
    camera_info_msg.D = [0, 0, 0, 0]

    # Ty = 0 and Tx = -fx' * B, where B is the baseline between the cameras.
    camera_info_msg.P = [fx, 0, cx, Tx,
                         0, fy, cy, Ty,
                         0, 0, 1, 0]
    return camera_info_msg

def process_metadata(metadata, prev_time, prev_vel_brh, prev_enu_R_brh):
    """ Convert metadata from the Unity simulator's left-handed frame to
        a right-handed frame.

        Position and quaternion are converted first to ENU and then to
        the right handed frame. These remain in a global reference frame,
        but one which ROS can better handle.
        The velocities and accelerations (linear and angular) are all in
        the body frame. Velocity and angular velocity are simply converted
        to the right-handed frame. Acceleration and angular acceleration
        are calculated via finite-difference of respective velocities, also
        in the right-handed body frame.

        Args:
            metadata: A dictionary containing metadata from the Unity
                simulator.
            prev_time: A float representing the time of the last metadata
                update received before this one.
            prev_vel_brh: A 3-vector representing the linear velocity of the
                agent in the right-handed body frame at teh previous metadata
                update.
            prev_anv_vel_brh: A 3-vector representing the angular velocity of
                the agent in the right-handd body frame at the previous
                metadata update. Default to None because we currently do not
                use it to determine angular acceleration.

        Returns:
            A dictionary containing processed metadata. Position and
            quaternion are both in the global right-handed frame.
            Velocities and accelerations are in the right-handed body frame.
            Time and collision status are preserved identically.
            Additionally, the 4x4 numpy matrix transform between the Unity
            world frame and the ENU right-handed frame is included.
    """
    enu_T_brh = convert_coordinate_frame(metadata)

    # Calculate position and orientation in the right-hand body frame from enu.
    enu_t_brh = get_translation_part(enu_T_brh)
    enu_R_brh = get_rotation_mat(enu_T_brh)
    enu_q_brh = get_quaternion(enu_T_brh)

    vel_brh = get_vel_brh(metadata)
    ang_vel_brh = get_ang_vel_brh(metadata)

    dt = metadata['time'] - prev_time
    acc_brh = get_acc_brh(enu_R_brh, vel_brh, prev_vel_brh, prev_enu_R_brh, dt)
    # ang_acc_brh = get_ang_acc_brh()

    # Construct dictionary of transformed metadata.
    processed_dict = {}
    processed_dict['position'] = enu_t_brh
    processed_dict['quaternion'] = enu_q_brh
    processed_dict['velocity'] = vel_brh
    processed_dict['ang_vel'] = ang_vel_brh
    processed_dict['acceleration'] = acc_brh
    # processed_dict['ang_accel'] = ang_acc_brh
    processed_dict['time'] = metadata['time']
    processed_dict['collision_status'] = metadata['collision_status']
    processed_dict['transform'] = enu_T_brh

    return processed_dict

def convert_coordinate_frame(metadata):
    """ Convert position and quaternion from the Unity simulator's left-handed
        frame to a right-handed frame.

        Position and quaternion are converted first to ENU and then to
        the right handed frame. These remain in a global reference frame,
        but one which ROS can better handle.

        Args:
            metadata: A dictionary containing metadata from the Unity
                simulator.

        Returns:
            A 4x4 numpy array representing the homogeneous transformation
            from the ENU world frame to the right-handed body frame of the
            agent, based on the input metadata.
    """
    # Build a 4x4 transformation matrix from the Unity metadata.
    unity_T_blh = tf.transformations.quaternion_matrix(metadata['quaternion'])
    unity_T_blh[:,3] = np.array(metadata['position'] + [1]) # Homogeneous coords

    # Convert the left-handed Unity frame to the right-handed ENU frame.
    enu_T_blh = enu_T_unity.dot(unity_T_blh)
    enu_T_brh = enu_T_blh.dot(blh_T_brh)

    return enu_T_brh

def get_vel_brh(metadata):
    """ Get velocity in the body right-handed frame from raw metadata.

        Metadata comes in as left-handed body-frame data, so we premultiply
        by the transformation from left-handed to right-handed frames.

        Args:
            metadata: A dictionary containing metadata from the Unity
                simulator.

        Returns:
            A 1x3 numpy array containing linear velocity of the agent
            in the body-right-handed frame as [vx,vy,vz].
    """
    return brh_T_blh[:3,:3].dot(metadata['velocity'])

def get_ang_vel_brh(metadata):
    """ Get angular velocity in the body right-handed frame from raw metadata.

        Metadata comes in as left-handed body-frame data, so we premultiply
        by the transformation from left-handed to right-handed frames.

        Args:
            metadata: A dictionary containing metadata from the Unity
                simulator.

        Returns:
            A 1x3 numpy array containing angular velocity of the agent
            in the body-right-handed frame as [wx,wy,wz].
    """
    # TODO(marcus): simulator must change to give ang_vel in body coords
    return brh_T_blh[:3,:3].dot(metadata['ang_vel'])
    # OTW, use this:
    # return unity_T_blh[:3,:3].dot(metadata['ang_vel'])

def get_acc_brh(enu_R_brh, vel_brh, prev_vel_brh, prev_enu_R_brh, dt):
    """ Get linear acceleration in the body right-handed frame via a finite
        difference of velocities.

        Velocities in the ENU frame are used for the finite difference as
        the global coordinates will ensure no error from the relative
        difference between body frames at two timestamps.

        Args:
            enu_R_brh: A 4x4 numpy matrix containing the homogeneous transform
                from body-right-handed to ENU at the current time.
            vel_brh: A 1x3 numpy array containing linear velocity in the
                body-right-handed frame at the current time.
            prev_vel_brh: A 1x3 numpy array containing linear velocity in the
                body-right-handed frame at the previous time.
            prev_enu_R_brh: A 4x4 numpy matrix containing the homogeneous
                transform from body-right-handed to ENU at the previous time.
            dt: A floating-point number representing the elapsed time from
                the previous time to the current one.

        Returns:
            A 1x3 numpy array containing the linear accelerations of the agent
            in [ax,ay,az] format.
    """
    assert(dt >= 0.0)

    vel_enu = enu_R_brh.dot(vel_brh)
    prev_vel_enu = prev_enu_R_brh.dot(prev_vel_brh)

    # Calculate the body acceleration via finite difference method
    accel_enu = (vel_enu - prev_vel_enu) / dt
    return np.transpose(enu_R_brh).dot(accel_enu)

def get_ang_acc_brh():
    # ang_acc_brh = (ang_vel_brh - prev_ang_vel_brh) / dt
    pass

def get_translation_part(transform):
    """ Get the 3-vector representing translation from a transformation matrix.

        Args:
            transform: A 4x4 numpy array representing a transformation.

        Returns:
            A 1x3 numpy array containin the translation part of the transform,
            in the [x,y,z] order.
    """
    return transform[:3,3]

def get_rotation_mat(transform):
    """ Get the 4x4 rotation matrix associated with a transformation matrix.

        Args:
            transform: A 4x4 numpy array representing a transformation.

        Returns:
            A 3x3 numpy array containin the rotation matrix of the transform.
    """
    R = copy.deepcopy(transform)
    return R[:3,:3]

def get_quaternion(transform):
    """ Get the 1x4 quaternion vector associated with a transformation matrix.

        Args:
            transform: A 4x4 numpy array representing a transformation.

        Returns:
            A 1x4 numpy array containin the quaternion representation of the
            rotation part of the transformation matrix.
    """
    R = copy.deepcopy(transform)
    R[:,3] = np.array([0,0,0,1])
    return tf.transformations.quaternion_from_matrix(R)
