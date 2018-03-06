"""
Created on Mon Jan 18 19:24:05 2016

@author: Jozef

MODULE DESCRIPTION
------------------

This module contains the commands and methods to ope_rate with the mount like
slew on/off, track on/off, stop

Mount is always defined as follows: address = '194.94.209.214'
                                    port    = 3490
"""

import socket
import serial
import time
import numpy as np
from MountTEST.core.mountcom import MountCom
from threading import Thread
from MountTEST.core.Driver import Chooser
from .coordinate_correction import CoordinateCorrection
from comtypes.client import CreateObject
try:
    from comtypes import COMError
except ImportError:
    COMError = AttributeError
from datetime import datetime


def convert_to_deg_min_sec(dec):
        dec_deg = int(dec)
        dec_min = abs(dec-dec_deg)
        dec_min *= 60
        dec_sec = dec_min-int(dec_min)
        dec_sec *= 60
        dec_min = int(dec_min)
        return dec_deg, dec_min, dec_sec


def convert_to_hour_min_sec(ra):
        ra_hour = int(ra)
        ra_min = ra-ra_hour
        ra_min *= 60
        ra_sec = ra_min-int(ra_min)
        ra_sec *= 60
        ra_min = int(ra_min)
        return ra_hour, ra_min, ra_sec


class Mount(MountCom):
    """
    Main class to communicate with the mount.
    """
    def __init__(self, telescope_driver='', debug=None):
        MountCom.__init__(self, debug)
        self.mount = get_telescope_driver(telescope_driver)
        self.debug = debug
        self.add_debug('Mount ini')

        self.ser_light = None
        self.mount_address = ''
        self.client = None
        self.serialDome = None
        self.ok = False
        self.outside_command_wait = False
        
        self.connect()
        self.last_send = time.time()
        self.position_ra = '00:00:00.0'
        self.position_dec = '+00:00:00.0'
        self.target_ra = '00:00:00.0'
        self.target_dec = '+00:00:00.0'
        self.status = '0#'
        self.set_time_to_mount()
        time.sleep(1)
        self.correction = CoordinateCorrection()
        self.coordinate_correction = False

        self.start()

    def get_status(self):
        if not self.is_connected():
            return 'disconnect'
        else:
            if self.is_parked():
                return 'parked'
            elif self.is_slewing():
                return 'slewing'
            elif self.is_tracking():
                return 'tracking'
            else:
                return 'unkown'

    def connect(self):
        """
        Try to connect to mount
        
        :returns:  True is there is a connection now, else False
        """
        self.add_debug('Connect to mount')
        try:
            self.mount_address = ('194.94.209.214', 3490)
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.settimeout(3)
            self.client.connect(self.mount_address)
            self.ok = True
            self.add_debug('Connection successful')
            self.serialDome = SerialDome(self.debug)
        except socket.error:
            self.ok = False
            self.add_debug('No connection to mount')
        self.mount.Connected = True
        return self.ok

    def is_connected(self):
        """
        Is a connection to mount 
        
        :returns:  True if there is a connection, else False
        """
        self.add_debug('is_connected')
        return self.mount.Connected

    def close_connection(self):
        """
        Close connection to mount
        
        :returns:  True if the connection is closed, else False
        """
        self.add_debug('close_connection')
        self.mount.Connected = False
        try:
            self.active = False
            self.client.close()
            self.add_debug('close_connection successful')
            return True
        except socket.error:
            self.add_debug('can\'t close connection to mount')
            return False

    def is_tracking(self):
        return self.mount.Tracking
    
    def send_command_status(self):
        """
        Update status and position of the telescope
        """
        self.add_debug('mount send_command_status')
        if time.time()-self.last_send > 0.1 and self.ok:
            time.sleep(0.1)
            self.status = self.client.send(':Gstat#')
            time.sleep(0.1)
            self.position_ra = self.send_command(':U2#:GR#')
            time.sleep(0.1)
            self.position_dec = self.send_command(':U2#:GD#')
        time.sleep(0.1)

    def send_command_to_mount(self, command):
        """
        Method sends the command to the mount defined by the address and port via
        TCP/IP. Returns the received data (if any).
        
        :param command:
            The command which will send
        :type command: str
        """
        self.add_debug('command ' + command)
        if not self.ok:
            if command == ':SDS1#':
                self.shutter_status = 1
            elif command == ':GDS#':
                return '{}#'.format(self.shutter_status)
            elif command == ':SDS2#':
                
                self.shutter_status = 2
        if self.ok:
            try:
                self.client.send(command)
                data = self.client.recv(1024)
                self.last_send = time.time()
                return data

            except socket.error:
                pass

    def update_telescope_pos(self):
        try:
            ra = self.mount.RightAscension
            dec = self.mount.Declination
            
            ra_hour, ra_min, ra_sec = convert_to_hour_min_sec(ra)
            
            dec_deg, dec_min, dec_sec = convert_to_deg_min_sec(dec)
            self.telescope_ra = [ra_hour, ra_min, round(ra_sec, 2)]
            self.telescope_dec = [dec_deg, dec_min, round(dec_sec, 2)]
        except AttributeError:
            self.telescope_ra = [0, 0, 0.00]
            self.telescope_dec = [0, 0, 0.00]

    def update_mount_status(self):
        """
        Updates the mount status if there is a connection to the mount.
        If not it will set the default value '-1' which mean_s that there is no connection.
        """
        if self.mount.Tracking:
            return '0#'
        else:
            if self.mount.AtPark:
                return '5#'
            else:
                return '7#'

    def update_target_pos(self):
        """
        Updates the target position which is stored in the mount if there is a connection to the mount.
        If not it will set the default values to the target position.
        """
        err_str = ''
        try:
            if self.coordinate_correction:
                ra = self.mount.TargetRightAscension - self.correction.delta_ra
                dec = self.mount.Target_declination - self.correction.delta_dec
            else:
                err_str += 'read target-pos ra from ascom\n'
                ra = self.mount.TargetRightAscension
                err_str += 'read target-pos dec from ascom\n'
                dec = self.mount.Target_declination
            err_str += 'convert ra\n'
            ra_hour, ra_min, ra_sec = convert_to_hour_min_sec(ra)
            err_str += 'convert dec\n'
            dec_deg, dec_min, dec_sec = convert_to_deg_min_sec(dec)
            err_str += 'set ra\n'
            self.target_ra = [ra_hour, ra_min, round(ra_sec, 2)]
            err_str += 'set dec'
            self.target_dec = [dec_deg, dec_min, round(dec_sec, 2)]
        except COMError:
            f = open('./error-pos.txt', 'a')
            f.write(err_str)
            f.close()
            self.target_ra = [0, 0, 0.0]
            self.target_dec = [0, 0, 0.0]

    def send_command(self, command):
        """
        Method sends the command to the mount defined by the address and port via 
        TCP/IP. Returns the received data (if any).
        
        :param command:
            The command which will send
        :type command: str
        
        :returns:  The return value of mount if there is one, else None
        """

        self.add_debug('mount send_command {}'.format(command))
        self.outside_command_wait = True
        output = self.set_command(command)
        return output

    def shutdown(self):
        """
        Switches off the mount.
        """
        self.add_debug('mount shutdown ')

        self.send_command(':shutdown#')

    # ******************************************************************************
    # ******************************************************************************
    #                           MOVEMENT COMMANDS
    # ******************************************************************************
    # ******************************************************************************
    def slew_alt_az(self, alt_deg, alt_min, alt_sec, az_deg, az_min, az_sec):
        """
        Slew to target altitude and azimuth.
        
        :param alt_deg:
            Degrees
        :type alt_deg: int
        :param alt_min:
            minute
        :type alt_min: int
        :param alt_sec:
            seconds
        :type alt_sec: float
        :param az_deg:
            Degree
        :type az_deg: int
        :param az_min:
            minutes
        :type az_min: int
        :param az_sec:
            seconds
        :type az_sec: float
        
       :returns:  0 no error
            if the target is below the lower limit: the string
            1Object Below Horizon        #
            if the target is above the high limit: the string
            2Object Below Higher         #
            if the slew cannot be performed due to another cause: the string
            3Cannot Perform Slew         # 
            if the mount is parked: the string
            4Mount Parked                #
            if the mount is restricted to one side of the meridian and the object 
            is on the other side: the string
            5Object on the  other side   #
        Notes:
            The :MA# command will slew to the alt-azimuth coordinates defined
            by the commands :Sa (Set target altitude) and :Sz (Set target azimuth). 
            After slewing to the target position, the mount will not track the object.
        """
        alt_deg = int(alt_deg)
        alt_min = int(alt_min)
        alt_sec = float(alt_sec)
        az_deg = int(az_deg)
        az_min = int(az_min)
        az_sec = float(az_sec)
        alt_deg += float(alt_min)/60+float(alt_sec)/360
        az_deg += float(az_min)/60+float(az_sec)/360
        self.unpark()
        if self.mount.Tracking:
            self.mount.Tracking = False
        self.mount.SlewToAltAzAsync(az_deg, alt_deg)

    def __slewAltAz__(self, alt_deg, alt_min, alt_sec, az_deg, az_min, az_sec):
        """
        Slew to target altitude and azimuth.

        :param alt_deg:
            Degrees
        :type alt_deg: int
        :param alt_min:
            minute
        :type alt_min: int
        :param alt_sec:
            seconds
        :type alt_sec: float
        :param az_deg:
            Degree
        :type az_deg: int
        :param az_min:
            minutes
        :type az_min: int
        :param az_sec:
            seconds
        :type az_sec: float
        
       :returns:  0 no error
            if the target is below the lower limit: the string
            1Object Below Horizon        #
            if the target is above the high limit: the string
            2Object Below Higher         #
            if the slew cannot be performed due to another cause: the string
            3Cannot Perform Slew         # 
            if the mount is parked: the string
            4Mount Parked                #
            if the mount is restricted to one side of the meridian and the object 
            is on the other side: the string
            5Object on the  other side   #
        Notes:
            The :MA# command will slew to the alt-azimuth coordinates defined
            by the commands :Sa (Set target altitude) and :Sz (Set target azimuth). 
            After slewing to the target position, the mount will not track the object.
        """
        self.add_debug('mount slewALTAZ {}:{}:{} {}:{}:{}'.format(alt_deg, alt_min, alt_sec,
                                                                  az_deg, az_min, az_sec))
        alt_ok = self.set_alt(alt_deg, alt_min, alt_sec)
        time.sleep(0.1)
        az_ok = self.set_az(az_deg, az_min, az_sec)
        time.sleep(0.1)
        if alt_ok == '1' and az_ok == '1':
            self.serialDome.lights_on()
            slew = self.send_command(':MA#')
            time.sleep(0.1)
            if slew == '0':
                stat = self.status
                counter = 0
                while stat == '6#':
                    stat = self.status
                    self.send_command_status()
                    time.sleep(0.1)
                    counter += 1
                else:
                    self.serialDome.lights_off()

                return slew

    def time_sycro(self):
        """
        Sets the current utc time of the computer to the mount
        :return:
        """
        now_utc = datetime.utcnow()
        date = datetime(now_utc.year, now_utc.month, now_utc.day, now_utc.hour, now_utc.minute, now_utc.second,
                        now_utc.microsecond)
        self.mount.UTCDate = date

    def is_slewing(self):
        return bool(self.mount.Slewing)

    def slew_ra_dec(self, ra_hour, ra_min, ra_sec, dec_deg, dec_min, dec_sec):
        ra_hour += float(ra_min)/60+float(ra_sec)/3600
        dec_deg += float(dec_min)/60+float(dec_sec)/3600

        self.slew_ra_dec_degree(ra_hour, dec_deg)

    def slew_ra_dec_degree(self, ra, dec):
        self.unpark()
        if not self.mount.Tracking:
            self.mount.Tracking = True
        if self.coordinate_correction:
            delta_ra, delta_dec = self.correction.get_correction(ra, dec)
            ra += delta_ra
            dec += delta_dec

        self.mount.TargetRightAscension = ra
        self.mount.Target_declination = dec
        self.mount.SlewToCoordinatesAsync(ra, dec)

    def switch_correction(self):
        """
        Activates or deactivates the usage of the correction model

        :return: The new status of the usage, true if the model will be used, else false
        :rtype: bool
        """
        self.coordinate_correction = not self.coordinate_correction
        self.slew_ra_dec_degree(self.mount.TargetRightAscension,
                                self.mount.Target_declination)
        return self.coordinate_correction

    def __slew_ra_dec__(self, ra_hour, ra_min, ra_sec, dec_deg, dec_min, dec_sec):
        """
        Slew to target object.
        :returns:  0 no error
            if the target is below the lower limit: the string
            1Object Below Horizon        #
            if the target is above the high limit: the string
            2Object Below Higher         #
            if the slew cannot be performed due to another cause: the string
            3Cannot Perform Slew         # 
            if the mount is parked: the string
            4Mount Parked                #
            if the mount is restricted to one side of the meridian and the object 
            is on the other side: the string
            5Object on the  other side   #
        Notes
            The :MS# command will slew to the equatorial coordinates defined 
            by the commands :Sr (Set target right ascension) and :Sd (Set target 
            declination). It is assumed that the coordinates are apparent, 
            topo-centric and NOT corrected for refraction. After slewing to the
            target position, the mount will track the object.
        """
        self.add_debug('mount slew_rADEC {}:{}:{} {}:{}:{}'.format(ra_hour, ra_min, ra_sec,
                                                                   dec_deg, dec_min, dec_sec))

        ra_ok = self.set_ra(int(ra_hour), int(ra_min), float(ra_sec))
        dec_ok = self.set_dec(int(dec_deg), int(dec_min), float(dec_sec))

        if ra_ok == '1' and dec_ok == '1':
            self.serialDome.lights_on()
            slew = self.send_command(':MS#')
            if slew == '0':
                time.sleep(0.5)
                stat = self.status

                while stat == '6#':
                    stat_loop = self.status
                    if len(stat_loop.split(':')) == 1:
                        stat = stat_loop
                    time.sleep(0.1)
                else:
                    self.serialDome.lights_off()

                return slew

    def move_east(self):
        """
        Move east (for equatorial mounts) or left (for alt-azimuth mounts) at
        current rate.
        If this command is given while moving at the guide rate, and the ultra 
        precision mode is not active, turning off the mount while this command 
        is in effect will make the mount to stay parked when turned on again.
        
        :returns: nothing
        """
        self.add_debug('mount move_east')
        east = self.send_command(':Me#')

        return east

    def move_north(self):
        """
        Move north (for equatorial mounts) or up (for alt-azimuth mounts) at
        current rate.
        
        :returns: nothing
        """
        self.add_debug('mount move_north ')
        north = self.send_command(':Mn#')

        return north

    def move_south(self):
        """
        Move south (for equatorial mounts) or down (for alt-azimuth mounts) at
        current rate.
        
        :returns: nothing
        """
        self.add_debug('mount move_south ')

        south = self.send_command(':Ms#')

        return south

    def move_west(self):
        """
        Move west (for equatorial mounts) or right (for alt-azimuth mounts) at
        current rate.
        
        :returns: nothing
        """
        self.add_debug('mount move_west ')

        west = self.send_command(':Mw#')

        return west

    def move_corr_east(self, step):
        """
        Corrects the position of the mount to the east (for equatorial mounts) or 
        left (for alt-azimuth mounts) by an amount equivalent to a motion of XXX
        milliseconds at the current auto-guide speed. The maximum length of the
        correction is 1000 milliseconds up to firmware revision 2.9.20. From 
        firmware revision 2.10, the maximum length of the correction is 9999 milliseconds.
        """
        self.add_debug('mount move_corr_east ')

        corr = self.send_command(':Me{}#'.format(step))

        return corr

    def move_corr_north(self, step):
        """
        Corrects the position of the mount to the north (for equatorial mounts) or 
        up (for alt-azimuth mounts) by an amount equivalent to a motion of XXX
        milliseconds at the current auto-guide speed. The maximum length of the
        correction is 1000 milliseconds up to firmware revision 2.9.20. From 
        firmware revision 2.10, the maximum length of the correction is 9999 milliseconds.
        """
        self.add_debug('mount move_corr_north ')

        corr = self.send_command(':Mn{}#'.format(step))

        return corr

    def move_corr_south(self, step):
        """
        Corrects the position of the mount to the south (for equatorial mounts) or 
        down (for alt-azimuth mounts) by an amount equivalent to a motion of XXX
        milliseconds at the current auto-guide speed. The maximum length of the
        correction is 1000 milliseconds up to firmware revision 2.9.20. From 
        firmware revision 2.10, the maximum length of the correction is 9999 milliseconds.
        """
        self.add_debug('mount  oveCorrSouth ')

        corr = self.send_command(':Ms{}#'.format(step))

        return corr

    def move_corr_west(self, step):
        """
        Corrects the position of the mount to the west (for equatorial mounts) or 
        right (for alt-azimuth mounts) by an amount equivalent to a motion of XXX
        milliseconds at the current auto-guide speed. The maximum length of the
        correction is 1000 milliseconds up to firmware revision 2.9.20. From 
        firmware revision 2.10, the maximum length of the correction is 9999 milliseconds.
        """
        self.add_debug('mount move_corr_west ')

        corr = self.send_command(':Mw{}#'.format(step))

        return corr

    def slew_spec_side(self, n):
        """
        Slew to target object on the specified side, where n is 2 for west and 3 for east.
        
        :returns:  0 no error
            if the target is below the lower limit: the string
            1Object Below Horizon        #
            if the target is above the high limit: the string
            2Object Below Higher         #
            if the slew cannot be performed due to another cause: the string
            3Cannot Perform Slew         # 
            if the mount is parked: the string
            4Mount Parked                #
            if the mount is restricted to one side of the meridian and the object 
            is on the other side: the string
            5Object on the  other side   #
            
        Notes:
            Use the :MSfs command in conjunction with the :GTsid command in order 
            to check the destination side before slewing to an object. Using :GTsid 
            followed by :MS would permit get_ting a side and then slewing 
            successfully to the other side if between the two commands the
            position of the object in the sky changes too much. Note that the 
            behaviour obtained by using :GTsid for DestinationSideOfPier and :MS 
            for slewing to the target (i.e. the possibility that the slew goes to 
            the other side) is currently expected to happen within the ASCOM 
            specification.
        """
        self.add_debug('mount slew_spec_side ')

        slew = self.send_command(':MSfs{}#'.format(n))

        return slew

    def swap_ew(self):
        """
        Swaps east - west direction.
        
        :returns:  nothing
        """
        self.add_debug('mount swap_ew ')
        swap = self.send_command(':EW#')

        return swap

    def swap_ns(self):
        """
        Swaps north-south direction.
        
        :returns:  nothing
        """
        self.add_debug('mount swap_ns ')
        swap = self.send_command(':NS#')

        return swap

    def stop_slew(self):
        """
        Halt all current slewing.
        """
        self.mount.AbortSlew()

    def __stopSlew__(self):
        """
        Halt all current slewing.\n
        Don't call this method. Use instate stop_slew to avoid crashes.
        """
        self.add_debug('mount stop_slew ')

        stop = self.send_command(':Q#')

        return stop

    def stop_east(self):
        """
        Halt eastward (for equatorial mounts) or leftward (for alt-azimuth mounts)
        movements.
        """
        self.add_debug('mount stop_east ')

        stop = self.send_command(':Qe#')

        return stop

    def stop_west(self):
        """
        Halt westward (for equatorial mounts) or rightward (for alt-azimuth mounts)
        movements.
        """
        self.add_debug('mount stop_west ')

        stop = self.send_command(':Qw#')

        return stop

    def stop_north(self):
        """
        Halt northward (for equatorial mounts) or upward (for alt-azimuth mounts)
        movements.
        """
        self.add_debug('mount stop_north ')

        stop = self.send_command(':Qn#')

        return stop

    def stop_south(self):
        """
        Halt southward (for equatorial mounts) or downward (for alt-azimuth mounts)
        movements.
        """
        self.add_debug('mount stop_south ')

        stop = self.send_command(':Qs#')

        return stop

    def flip(self):
        """
        This command acts in different ways on the AZ2000 and german equatorial 
        (GM1000 - GM4000) mounts.
        
        On an AZ2000 mount:
            When observing an object near the lowest culmination, requests to make 
            a 360 deg turn of the azimuth axis and point the object again.
            
        On a german equatorial mount:
            When observing an object near the meridian, requests to make a 180 deg 
            turn of the RA axis and move the declination axis in order to point 
            the object with the telescope on the other side of the mount.
            
        :returns:  1 if successful
            0 if the movement cannot be done
        """
        self.add_debug('mount flip ')

        flip = self.send_command(':FLIP#')

        return flip

    def slew_progress(self):
        """
        Requests a string indicating the progress of the current slew ope_ration.
        
        :returns:  the string , where the block character has ascii code 127 (0x7F), 
            if a slew is in progress or a slew has ended from less than the settle 
            time set in command :Sstm. the string # if a slew has been completed 
            or no slew is underway.
            
        Notes
            If a dome is connected, check the :GDW# command, since it may be more 
            appropriate for you.
        """
        self.add_debug('mount slew_progress ')
        progress = self.send_command(':D#')

        return progress

    # ******************************************************************************
    # ******************************************************************************
    #                           RATE COMMANDS
    # ******************************************************************************
    # ******************************************************************************

    def slew_rate(self, n):
        """
        Sets the centering rate according to the value of n:
        0   16x (0.067 deg/s)  Guiding rate
        1   64x (0.27 deg/s)   Centering rate
        2   600x (2.5 deg/s)   Find rate
        3   1200x (5 deg/s)    max rate
        If the selected rate is greater than the current slew rate, the centering rate is made equal
        to the slew rate. For example, if the slew rate is set to 900x (3.75 deg/s), the command
        :RC3# will set the centering rate to 900x (3.75 deg/s).
        
        :returns:  nothing
        """
        self.add_debug('mount slew_rate {}'.format(n))

        command = ':RC{}#'.format(n)
        rate = self.send_command(command)

        return rate

    def guide_rate(self, n):
        """
        Sets the guiding rate according to the value of n:
        0   0.25x (3.75/s)
        1   0.5x (7.5/s)
        2   1.0x (15/s)
        
        :returns:  nothing
        """
        self.add_debug('mount guide_rate {}'.format(n))
        if n > 2 or n < 0:
            err = "Invalid value for n. Allowed values for n are 0, 1, 2. "
            return err
        else:
            command = ':RG{}#'.format(n)
            rate = self.send_command(command)
            return rate

    def slew_rate_ra(self, ddd):
        """
        Set RA/azimuth slew rate to DD.D degrees per second
        (up to seven decimal places allowed).
        
        :param ddd: Thew new slew rate
        :type ddd: float
        
        :returns:  nothing
        """
        self.add_debug('mount slew_rate_ra {}'.format(ddd))
        if ddd > 100:
            err = "Rate cannot be higher than 99.9999999. Decrease the value and use \
            the right format DD.DDDDDDD (up to 7 decimal places)."
            return err
        elif ddd < 0:
            err = "Rate cannot be negative number."
            return err
        else:
            command = ":RA{:0.7f}#".format(ddd)
            return command

    def slew_rate_dec(self, ddd):
        """
        Set DEC/altitude slew rate to DD.D degrees per second
        (up to seven decimal places allowed).
        :param ddd: Thew new slew rate
        :type ddd: float
        
        :returns:  nothing
        """
        self.add_debug('mount slew_rate_dec {}'.format(ddd))
        if ddd > 100:
            err = "Rate cannot be higher than 99.9999999. Decrease the value and use \
            the right format DD.DDDDDDD (up to 7 decimal places)."
            return err
        elif ddd < 0:
            err = "Rate cannot be negative number."
            return err
        else:
            command = ":RE{:0.7f}#".format(ddd)
            return command

    def get_current_slew_rate(self):
        """
        Get the current slew rate in degrees/s.
        
        :returns:  XX# in degrees/s.
        """

        self.add_debug('mount get_current_slew_rate ')
        rate = self.send_command(':GMs#')
        return rate

    def get_min_slew_rate(self):
        """
        Get the minimum slew rate that can be set in the mount in degrees/s.
        
        :returns:  XX# in degrees/s.
        """
        self.add_debug('mount get_min_slew_rate ')

        rate = self.send_command(':GMsa#')
        return rate

    def get_max_slew_rate(self):
        """
        Get the maximum slew rate that can be set in the mount in degrees/s.
        
        :returns:  XX# in degrees/s.
        """
        self.add_debug('mount get_max_slew_rate ')

        rate = self.send_command(':GMsb#')
        return rate

    def get_current_guide_rate(self):
        """
        Get current guide rate.
        
        :returns:  S.SS# (arc-seconds/s)
        """
        self.add_debug('mount get_current_guide_rate ')

        rate = self.send_command(':Ggui#')
        return rate

    # ******************************************************************************
    # ******************************************************************************
    #                           GET COMMANDS
    # ******************************************************************************
    # ******************************************************************************
    def get_telescope_altitude(self):
        """
        Get telescope altitude.
        
        :returns: 
            sDD:MM:SS.S# (degrees, arc-minutes, arc-seconds and tenths of arcsecond)
        """
        self.add_debug('mount get_telescope_altitude ')
        alt = self.send_command(':U2#:GA#')

        return alt

    def get_target_altitude(self):
        """
        Get current target altitude.
        
        :returns: 
            sDD:MM:SS.S# (degrees, arc-minutes, arc-seconds and tenths of arcsecond)
            
        Note:
            If the target position has been set using the :Sr and :Sd commands, 
            the return value is the altitude of the target computed from its 
            equatorial coordinates at the time the :Ga command is received. 
            Otherwise, it is the value set using the :Sa command. If neither 
            an equatorial target position nor a target altitude has been set, 
            the return value is undefined.
        """
        self.add_debug('mount get_target_altitude ')
        alt = self.send_command(':U2#:Ga#')

        return alt

    def get_telescope_dec(self, as_str=False):
        """
        Get the current declination of the telescope.
        
        :returns: 
            sDD:MM:SS.S# (degrees, arcminutes, arcseconds and tenths of arcsecond)
        """
        self.add_debug('mount get_telescope_dec ')

        if as_str:
            dec = self.telescope_dec
            
            if type(dec[0]) == int:
                for i in range(len(dec)):
                    dec[i] = str(dec[i])
            return dec
        return self.telescope_dec

    def get_target_dec(self):
        """
        Get the current target declination.
        
        :returns: 
            sDD:MM:SS.S# (degrees, arcminutes, arcseconds and tenths of arcsecond)
        """
        self.add_debug('mount get_target_dec ')

        return self.target_dec

    def split_coord_ra(self, coord):
        self.add_debug('mount split_coord_ra {}'.format(coord))
        try:
            ra_hour = coord[0:2]
            ra_min = coord[3:5]
            ra_sec = coord[6:10]
        except TypeError:
            ra_hour = '00'
            ra_min = '00'
            ra_sec = '00.0'
        return ra_hour, ra_min, ra_sec

    def split_coord_dec(self, coord):
        """
        Split the DEC coordinate from the mount to dd:mm:ss.s

        :param coord: The coordinate string from the mount
        :type coord: str

        :returns: Three string with dd, mm, and ss.s
        :rtype: list
        """
        self.add_debug('mount split_coord_dec {}'.format(coord))
        try:
            dec_deg = coord[0:3]
            dec_min = coord[4:6]
            dec_sec = coord[7:11]
        except TypeError:
            dec_deg = '+00'
            dec_min = '00'
            dec_sec = '00.0'
        return dec_deg, dec_min, dec_sec

    def get_date(self):
        """
        Get current date.
        
        :returns: 
            YYYY-MM-DD# (year, month, day)
        """
        self.add_debug('mount get_date ')
        date = self.send_command(':U2#:GC#')

        return date

    def get_elevation(self):
        """
        Get the current site elevation.
        
        :returns:  
            sXXXX.X# 
            The current site elevation expressed in metres.
        """

        self.add_debug('mount get_elevation ')
        elevation = self.send_command(':Gev#')

        return elevation

    def get_utc_offset(self):
        """
        Get the UTC offset time. Returns the number of hours to add to local time 
        to convert it to UTC. The daylight savings setting in effect is factored 
        into the returned value.
        
        :returns: 
            sHH:MM:SS.S# (sign, hours, minutes, seconds and tenths of second)
        """

        self.add_debug('mount get_utc_offset ')
        offset = self.send_command(':U2#:GG#')

        return offset

    def get_longitude(self):
        """
        Get current site longitude. Note: East Longitudes are expressed as 
        negative.
        
        :returns: 
            sDDD:MM:SS.S# (sign, degrees, arcminutes, arcseconds, tenths of arcsecond)
        """
        self.add_debug('mount get_longitude ')

        longitude = self.send_command(':U2#:Gg#')

        return longitude

    def get_high_alt_limit(self):
        """
        Get high limit. Returns the highest altitude above the horizon that the 
        mount will be allowed to slew to without reporting an error message.
        
        :returns: 
            sDD# (sign, degrees)
        """

        self.add_debug('mount get_high_alt_limit ')
        limit = self.send_command(':U2#:Gh#')

        return limit

    def get_connection_type(self):
        """
        Get the type of connection.
        
        :returns: 
            0# if the connection is over a serial RS-232 port
            1# if the connection is over a GPS or GPS/RS-232 port
            2# if the connection is over a cabled LAN port
            3# if the connection is over a wireless LAN
        """

        self.add_debug('mount get_connection_type ')
        connection = self.send_command(':GINQ#')

        return connection

    def get_ip(self):
        """
        Get the IP address of the mount.
        
        :returns:  
            nnn.nnn.nnn.nnn,mmm.mmm.mmm.mmm,ggg.ggg.ggg.ggg,c#
        
        A string containing the IP address (nnn.nnn.nnn.nnn), the subnet mask 
        (mmm.mmm.mmm.mmm), the gateway (ggg.ggg.ggg.ggg) and a character (c) that 
        is set to "D" if the address is obtained from a DHCP server, or "M" if 
        the address is configured manually.
        """

        self.add_debug('mount get_ip ')
        ip = self.send_command(':GIP#')

        return ip

    def get_jd(self):
        """
        Get the current Julian Date.
        
        :returns:  
            JJJJJJJ.JJJJJ#
            
        The current Julian Date for the mount.
        Note: the Julian Date is computed from the UTC time. During leap seconds, 
        the value of the Julian Date should be considered invalid.
        """

        self.add_debug('mount get_jd ')
        jd = self.send_command(':GJD#')

        return jd

    def get_jd1(self):
        """
        Get the current Julian Date with extended precision.
        
        :returns:  
            JJJJJJJ.JJJJJJJJ#
            
        The current Julian Date for the mount in extended precision 
        (8 decimal places). 
        Note: the Julian Date is computed from the UTC time. During leap seconds, 
        the value of the Julian Date should be considered invalid.
        """

        self.add_debug('mount get_jd1 ')
        jd1 = self.send_command(':GJD1#')

        return jd1

    def get_jd2(self):
        """
        Get the current Julian Date with extended precision and leap second flag.
        
        :returns:  
            JJJJJJJ.JJJJJJJJ# or JJJJJJJ.JJJJJJJJL#
            
        The current Julian Date for the mount in extended precision (8 decimal 
        places), with an optional "L" appended at the end to signal that we are 
        in a leap second.
        Note: the Julian Date is computed from the UTC time. During leap seconds, 
        the value of the Julian Date continues to increase, with the "L" flag set. 
        So, for example, you will have, around the time of the leap second of 
        
        2015 June 30:
            Date Time (UTC) Result of GJD2#
            2015-06-30 23:59:59.0 2457204.49998843#
            2015-06-30 23:59:59.5 2457204.49999421#
            2015-06-30 23:59:60.0 2457204.50000000L#
            2015-06-30 23:59:60.5 2457204.50000579L#
            2015-07-01 00:00:00.0 2457204.50000000#
            2015-07-01 00:00:00.5 2457204.50000579#
        """
        self.add_debug('mount get_jd2 ')

        jd2 = self.send_command(':GJD2#')

        return jd2

    def get_local_time(self):
        """
        Get local time. Returns the local time in 24-hour format.
        
        :returns: 
            HH:MM:SS.SS# (hours, minutes, seconds, hundredths of second)
        """
        self.add_debug('mount get_local_time ')

        t = self.send_command(':U2#:GL#')

        return t

    def get_local_time_date(self):
        """
        Get local date and time. 
        
        :returns: 
            YYYY-MM-DD,HH:MM:SS.SS# (<date>,<time>#)
        """
        self.add_debug('mount get_local_time_date ')

        local = self.send_command(':U2#:GLDT#')

        return local

    def get_utc_time_date(self):
        """
        Get UTC date and time. 
        
        :returns:  
            YYYY-MM-DD,HH:MM:SS.SS# (<date>,<time>#)
        """
        self.add_debug('mount get_utc_time_date ')

        utc = self.send_command(':U2#:GUDT#')

        return utc

    def get_leap_sec_date(self):
        """
        Gets the date of the next leap second that will be accounted for.
        
        :returns: 
            XXXX-XX-XX# the date of the next leap second, if available;
            E# if no leap second is due according to the data loaded 
            in the mount.
        """
        self.add_debug('mount get_leap_sec_date ')

        leap = self.send_command(':GULEAP#')

        return leap

    def get_meridian_side(self):
        """
        Get meridian side.
        
        :returns:  
            1# both sides of the meridian allowed;
            2# only objects west of the meridian allowed;
            3# only objects east of the meridian allowed.
        """
        self.add_debug('mount get_meridian_side ')

        meridian = self.send_command(':GMF#')

        return meridian

    def get_low_alt_limit(self):
        """
        Get lower limit. Returns the lowest altitude above the horizon that the 
        mount will be allowed to slew to without reporting an error message.
        
        :returns: 
            sDD# (sign, degrees)
        """
        self.add_debug('mount get_low_alt_limit ')

        limit = self.send_command(':U2#:Go#')

        return limit

    def get_guiding_status(self):
        """
        Get guiding status.
        
        :returns:  
            0# the mount is not guiding;
            1# the mount is guiding in right ascension / azimuth;
            2# the mount is guiding in declination / altitude;
            3# the mount is guiding in both axes.
        """
        self.add_debug('mount get_guiding_status ')

        status = self.send_command(':Gpgc#')

        return status

    def get_telescope_ra(self, as_str=False):
        """
        Get telescope right ascension.
        
        :returns: 
            HH:MM:SS.SS#  (hours, minutes, seconds and hundredths of seconds)
        """
        self.add_debug('mount get_telescope_ra ')

        if as_str:
            ra = self.telescope_ra
            
            if type(ra[0]) == int:
                for i in range(len(ra)):
                    ra[i] = str(ra[i])
            return ra
        return self.telescope_ra

    def get_target_ra(self):
        """
        Get current target RA.
        
        :returns: 
            HH:MM:SS.SS#  (hours, minutes, seconds and hundredths of seconds)
        """
        self.add_debug('mount get_target_ra ')
        
        return self.target_ra

    def get_pressure_in_model(self):
        """
        Get the atmospheric pressure used in the refraction model. Note that this 
        is the pressure at the location of the telescope, and not the pressure 
        at sea level.
        
        :returns:  
            PPPP.P# 
            The required pressure in hPa.
        """
        self.add_debug('mount getPressureModel ')

        p = self.send_command(':GRPRS#')

        return p

    def get_temp_in_model(self):
        """
         Get the temperature used in the refraction model
         
         :returns:  
             +TTT.T#
             The required temperature in degrees Celsius ( degC).
        """
        self.add_debug('mount get_temp_in_model ')

        temperature = self.send_command(':GRTMP#')

        return temperature

    def get_sidereal_time(self):
        """
        Get the sidereal time.
        
        :returns: 
            HH:MM:SS.SS#  (hours, minutes, seconds and hundredths of seconds)
        """
        self.add_debug('mount get_sidereal_time ')

        sidereal = self.send_command(':U2#:GS#')

        return sidereal

    def get_refraction_status(self):
        """
        Gets the current status of the refraction correction.
        
        :returns: 
            0 Refraction correction inactive
            1 Refraction correction active
        """
        self.add_debug('mount get_refraction_status ')

        status = self.send_command(':GREF#')

        return status

    def get_speed_correction_flag(self):
        """
        Gets the current status of the speed correction flag
        
        :returns: 
            0 Speed correction inactive
            1 Speed correction active
            
        When  the speed correction is active, the speed of any movement in the 
        RA/azimuth axis is multiplied by cos (dec) -1 or cos (altitude) -1. 
        In this way the angular speed on the sky is always constant. This is 
        useful when autoguiding, since the relation between the duration of the 
        correction pulses and the offsets in the focal plane of the telescope 
        becomes independent from the declination (or altitude) of the mount.
        """
        self.add_debug('mount get_speed_correction_flag ')

        flag = self.send_command(':GSC#')

        return flag

    def get_telescope_status(self):
        """
        Gets the status of the mount.
        
        :returns:  
            0# The mount is tracking.
            1# The mount is stopped after the pressing of the STOP key, receiving 
            the :STOP# command or completing an homing sequence. 
            2# The mount is slewing to the park position.
            3# The mount is unparking.
            4# The mount is slewing to the home position.
            5# The mount is parked.
            6# The mount is slewing, or the mount is going to stop (but still 
            moving) after the STOP key has been pressed or the :STOP# 
            command has been received.
            7# Tracking is off and the mount is not moving.
            8# The motors are inhibited because of low temperature (only for
            special-purpose mounts with temperature sensors) .
            9# Tracking is on but the mount is outside tracking limits.
            10# The mount is following a precalulated satellite trajectory.
            11# The mount needs an user intervention to authorize movement, due 
            to a suspected inconsistency in data (see :USEROK# command); 
            if this occurs, DO NOT assume anything about the correctness of 
            the mount position or alignment data.
            98# Unknown status.
            99# Error.
        """
        self.add_debug('mount get_telescope_status ')

        status = self.status

        return status

    def get_slew_settle_time(self):
        """
        Returns the slew settle time. After a slew has been completed, the :D# 
        and :GDW# commands will return a slewing status for the time duration 
        set in this command. 
        Note: the :Gstat# command is not affected by this setting.
        
        :returns:  
            NNNNN.NNN#
            The mount settle time in seconds.
        """
        self.add_debug('mount get_slew_settle_time ')

        settle = self.send_command(':Gstm#')

        return settle

    def get_dome_settle_time(self):
        """
        Returns the dome settle time. After a slew has been completed, the :GDW# 
        and :GDw# commands will return a slewing status for the time duration 
        set in this command.
        
        :returns:  
            NNNNN.NNN#
            The dome settle time in seconds.
        """
        self.add_debug('mount get_dome_settle_time ')

        settle = self.send_command(':GDstm#')

        return settle

    def get_meridian_tracking_limit(self):
        """
        Returns the meridian limit for tracking in degrees.
        
        :returns:  
            NN#
            The meridian limit for tracking in degrees.
        """
        self.add_debug('mount get_meridian_tracking_limit ')

        limit = self.send_command(':Glmt#')

        return limit

    def get_meridian_slew_limit(self):
        """
        Returns the meridian limit for slews in degrees.
        
        :returns:  
            NN#
            The meridian limit for slews in degrees.
        """
        self.add_debug('mount get_meridian_slew_limit ')

        limit = self.send_command(':Glms#')

        return limit

    def get_estimate_tracking_time(self):
        """
        Returns the estimated time to tracking end due to horizon / flip limits 
        reached.
        
        :returns:  
            NNNN#
            The estimated time to tracking end in minutes of time.
        """
        self.add_debug('mount get_estimate_tracking_time ')

        return self.tracking_time

    def get_flip_setting(self):
        """
        Returns the unattended flip setting.
        
        :returns: 
            0 disabled
            1 enabled
        """
        self.add_debug('mount get_flip_setting ')

        flip = self.send_command(':Guaf#')

        return flip

    def get_tracking_rate(self):
        """
        Get tracking rate.
        
        :returns:  
            TT.T#
            
        This value is computed in order to emulate the corresponding LX200 
        command. This corresponds to the equivalent frequency expressed 
        in hertz assuming a synchronous motor design where a 60.0 Hz motor
        clock would produce 1 revolution of the mount in 24 hours. So, in order 
        to obtain the tracking rate in arcseconds per second of time, this 
        value should be divided by four.
        """
        self.add_debug('mount get_tracking_rate ')

        rate = self.send_command(':GT#')

        return rate

    def get_latitude(self):
        """
        Get current site latitude.
        
        :returns: 
            sDD:MM:SS.S#  (sign, degrees, arcminutes, arcseconds, tenths of 
            arcsecond)
        """

        latitude = self.send_command(':Gt#')

        return latitude

    def get_temperature(self, n):
        """
        Get the temperature of element n, where n is an ASCII digit (1...9) 
        
        :param n:
            1 Right Ascension/Azimuth motor driver
            2 Declination/Altitude motor driver
            7 Right Ascension/Azimuth motor
            8 Declination/Altitude motor
            9 Electronics box temperature sensor
            11 Keypad (v2) display sensor
            12 Keypad (v2) PCB sensor
            13 Keypad (v2) controller sensor
        :type n: int
        
        :returns:  
            +TTT.T#
            
        The required temperature in degrees Celsius ( degC).
        If the required temperature cannot be read, the string Unavailable# is
        returned.
        If the electronics box temperature sensor is available, its readout can be
        used to monitor the electronics temperature to avoid overheating. The
        electronics box temperature should never go above +65 degC. If the temperature
        goes above +65 degC, immediate action should be taken in order to preserve the 
        electronics - either cooling it or shutting it off. Higher temperatures
        would damage the electronics and the power supplies will automatically shut
        down at +70 degC.7, 8, 9 are available only for special-purpose mounts with 
        temperature sensors. 11, 12, 13 are available only if a physical keypad
        version 2 is connected to the mount.
        """
        self.add_debug('mount get_temperature {}'.format(n))

        temperature = self.send_command(':GTMPn#')

        return temperature

    def get_tracking_status(self):
        """
        Get the current tracking status of the mount
        
        :returns: False if the mount is not tracking and True  the mount is tracking
        """
        self.add_debug('mount get_tracking_status ')

        return self.mount.Tracking

    def get_park_status(self):
        """
        Returns the current park status

        :return: True if the mount is parked, else False
        :rtype: bool
        """
        try:
            return self.mount.AtPark
        except AttributeError:
            return True

    def get_obj_tracking_status(self):
        """
        Get the tracking status of the target object
        
        :returns: 
            0 the target object is located in a position where tracking is not 
            allowed (i.e. below the horizon, or above +89 deg if using an alt-azimuth mount)
            1 the target object is located in a position where tracking is allowed
        """
        self.add_debug('mount get_obj_tracking_status ')

        status = self.send_command(':GTTRK#')

        return status

    def get_destination_side(self):
        """
        Get the destination side of the target object
        
        :returns: 
            0 no target defined, or the target object is located in a position 
            where it is not possible to go
            2 the target is located in a position where the mount would slew 
            to the west side
            3 the target is located in a position where the mount would slew 
            to the east side
            
        Notes
            See the :MSfs command.
        """
        self.add_debug('mount get_destination_side ')

        side = self.send_command(':GTsid#')

        return side

    def get_firmware_date(self):
        """
        Get firmware date.
        
        :returns:
            mmm dd yyyy# (month as a three-letter string among "Jan", "Feb",
            "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"; day; year)
        """
        self.add_debug('mount get_firmware_date ')

        firm = self.send_command(':GVD#')

        return firm

    def get_firmware_num(self):
        """
        Get firmware number.
        
        :returns: A string containing the firmware revision.
        """
        self.add_debug('mount get_firmware_num ')

        firm = self.send_command(':GVN#')

        return firm

    def get_product_name(self):
        """
        Get product name.
        
        :returns:
            "10micron GM1000HPS#" for a GM1000HPS mount,
            "10micron GM2000QCI#" for a GM2000QCI mount,
            "10micron GM2000HPS#" for a GM2000HPS mount,
            "10micron GM3000HPS#" for a GM3000HPS mount,
            "10micron GM4000QCI#" for a GM4000QCI mount,
            "10micron GM4000QCI 48V#" for a special GM4000QCI mount with 48V supply,
            "10micron GM4000HPS#" for a GM4000HPS mount,
            "10micron AZ2000#" for an alt-azimuth AZ2000 mount
        """
        self.add_debug('mount get_product_name ')

        name = self.send_command(':GVP#')

        return name

    def get_firmware_time(self):
        """
        Get firmware time.
        
        :returns: HH:MM:SS# (hours, minutes, seconds)
        """

        self.add_debug('mount get_firmware_time ')
        firmware_time = self.send_command(':GVT#')

        return firmware_time

    def get_control_box_version(self):
        """
        Get control box hardware version.
        
        :returns:
            "Q-TYPE2012#" identifies a Q-TYPE 2012 control box,
            "PRE2012#" identifies a pre-2012 control box,
            "UNKNOWN#" identifies an unknown control box version
        """
        self.add_debug('mount get_control_box_version ')

        version = self.send_command(':GVZ#')

        return version

    def get_telescope_azimuth(self):
        """
        Get the telescope azimuth.
        
        :returns: DDD:MM:SS.S# (degrees, arcminutes, arcseconds and tenths of arcsecond)
        """
        self.add_debug('mount get_telescope_azimuth ')

        azimuth = self.send_command(':U2#:GZ#')

        return azimuth

    def get_target_azimuth(self):
        """
        Get the target azimuth.
        
        :returns: 
            DDD:MM:SS.S# (degrees, arcminutes, arcseconds and tenths of arcsecond)
            
        Note:
            If the target position has been set using the :Sr and :Sd commands, 
            the return value is the azimuth of the target computed from its 
            equatorial coordinates at the time the :Gz command is received. 
            Otherwise, it is the value set using the :Sz command. If neither 
            an equatorial target position nor a target azimuth has been set, 
            the return value is undefined.
            From version 2.12.14 onwards, when the mount is commanded to slew 
            to a target from the keypad / virtual keypad interface, the target 
            azimuth is updated with the azimuth of the target set by the 
            keypad / virtual keypad interface.
        """
        self.add_debug('mount get_target_azimuth ')

        azimuth = self.send_command(':U2#:Gz#')

        return azimuth

    def get_pier_side(self):
        """
        Get the side of the pier on which the telescope is currently positioned.
        
        :returns:  
            the string "East# or the string "West#".
        """
        self.add_debug('mount getPirSide ')

        pier = self.send_command(':pS#')

        return pier

    # ******************************************************************************
    # ******************************************************************************
    #                           PARK COMMANDS
    # ******************************************************************************
    # ******************************************************************************
    def park(self):
        th = Thread(target=self.__park__)
        th.start()

    def __park__(self):
        """
        Park the mount and stops tracking.
        """
        self.add_debug('mount park ')

        if self.is_parked():
            pass
        else:
            self.send_command(':hP#')
            self.mount.Park()
    
    def unpark(self):
        th = Thread(target=self.__unpark__)
        th.start()
        
    def __unpark__(self):
        """
        Unpark the mount and starts tracking.
        
        :returns: 0 if the mount is unparked now, 1 if the mount is parked and -1 else
        """
        try:
            self.add_debug('mount unpark ')
            if self.is_parked():
                self.mount.Unpark()
                return 0
            else:
                return 1
        except ValueError:
            pass
        return -1

    def is_parked(self):
        return self.mount.AtPark

    # ******************************************************************************
    # ******************************************************************************
    #                           SET COMMANDS
    # ******************************************************************************
    # ******************************************************************************
    def set_alt(self, alt_deg, alt_min, alt_sec):
        """
        Set target object altitude to sDD*MM:SS.S (sign, degrees, arcminutes, 
        arcseconds, tenths of arcsecond)

        :param alt_deg: Degrees of altitude
        :type alt_deg: int
        :param alt_min: Minutes of altitude
        :type alt_min: int
        :param alt_sec: Seconds of altitude
        :type alt_sec: float
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_alt {}:{}:{}'.format(alt_deg, alt_min, alt_sec))
        # =======================================================
        #   Creating the correct format for Alt

        # final command for Alt
        alt = ':Sa{:+03d}*{:02d}:{:04.1f}#'.format(alt_deg, alt_min, alt_sec)
        alt_ok = self.send_command(alt)
        if alt_ok is not None:
            return 0
        return alt_ok

    def set_az(self, az_deg, az_min, az_sec):
        """
        Sets the target azimuth to or DDD*MM:SS.S (degrees, arcminutes, arcseconds and 
        tenths of arcsecond).
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        
        self.add_debug('mount set_az {}:{}:{}'.format(az_deg, az_min, az_sec))

        # final command for Az
        az = ':Sz{:03d}*{:02d}:{:02d}#'.format(az_deg, az_min, az_sec)
        az_ok = self.send_command(az)

        if az_ok is not None:
            return 0
        return az_ok

    def set_ra(self, ra_hour, ra_min, ra_sec):
        """
        Set target object RA to HH:MM:SS.SS (hours, minutes, seconds and hundredths 
        of second).
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_ra {}:{}:{}'.format(ra_hour, ra_min, ra_sec))
        # =======================================================
        #   Creating the correct format for RA

        # final command for RA
        ra = ':Sr{:02d}:{:02d}:{:05.2f}#'.format(ra_hour, ra_min, ra_sec)
        ra_ok = self.send_command(ra)

        return ra_ok

    def set_dec(self, dec_deg, dec_min, dec_sec):
        """
        Set target object declination to sDD*MM:SS.S (sign, degrees, arcminutes, 
        arcseconds and tenths of arcsecond)
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_dec {}:{}:{}'.format(dec_deg, dec_min, dec_sec))
        # =======================================================
        #   Creating the correct format for DEC

        # final command for DEC
        dec = ':Sd{:02d}:{:02d}:{:05.2f}#'.format(dec_deg, dec_min, dec_sec)
        dec_ok = self.send_command(dec)

        return dec_ok

    def set_date(self, yyyy, mm, dd):
        """
        Set the date to YYYY-MM-DD (year, month, day). The date is
        expressed in local time.
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        
        self.add_debug('mount set_date {}-{}-{}'.format(yyyy, mm, dd))

        command = ':SC{:04d}-{:02d}-{:02d}#'.format(yyyy, mm, dd)
        date = self.send_command(command)

        return date

    def set_elev(self, xxxxx):
        """
        Set current site's elevation to sXXXX.X (sign, metres) in the range -1000.0 to 9999.9.
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """

        self.add_debug('mount set_elev {}'.format(xxxxx))
        if xxxxx < -1000 or xxxxx > 9999.9:
            err = "Value for elevation is invalid. This number has to be \
            in the range of -1000.0 and 9999.9"
            print('set_elev', err)
        else:
            integ = np.fix(xxxxx)
            dec = xxxxx - np.fix(xxxxx)
            elev = abs(integ) + abs(dec)

            command = self.send_command(':Sev{:+07.1f}#'.format(elev))

            return command

    def set_long(self, dd, mm, ss):
        """
        Set current site's longitude to sDDD*MM:SS.S (sign, degrees, arcminutes,
        arcseconds and tenths of arcsecond). Note: East Longitudes are expressed as
        negative.
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """

        self.add_debug('mount set_long {}:{}:{}'.format(dd, mm, ss))

        long = self.send_command(':Sg{:+04d}*{:02d}:{:04.1f}#'.format(dd, mm, ss))

        return long

    def set_local_offset(self, hh):
        """
        Set the number of hours added to local time to yield UTC (sign, hours and tenths of
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """

        self.add_debug('mount set_local_offset {}'.format(hh))

        offset = self.send_command(':SG{:+4.1f}#'.format(hh))

        return offset

    def set_high_alt_limit(self, dd):
        """
        Set the highest altitude to which the telescope will slew to sDD degrees.
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """

        self.add_debug('mount set_high_alt_limit {}'.format(dd))

        alt = self.send_command(':Sh{:+03d}#'.format(dd))

        return alt

    def set_jd(self, jd):
        """
        Set the Julian Date to the given value (up to eight decimal places).
        JJJJJJJ.JJJJJJJJ
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        
        Note: the Julian Date is computed from the UTC time. During leap
        seconds, there is no valid value for the Julian Date, so you cannot
        use this command to set time during leap seconds.
        """
        self.add_debug('mount setJd {}'.format(jd))

        if jd < 1000000:
            err = "Type the julian date in format jjjjjjj.jjjjjjjj"
            print('SetJD', err)
        else:
            date = self.send_command(':SJD{}'.format(jd))
            return date

    def set_time_to_mount(self):
        """
        Uses the local time on the computer the set a new local time to
        the mount.
        """
        date = datetime.now()
        date = date.strftime("%Y,%m,%d,%H,%M,%S,%f")
        date = date.split(',')
        seconds = int(date[-2])+float(date[-1])/1000000
        seconds = round(seconds, 2)
        self.set_local_time(int(date[3]), int(date[4]), seconds)

    def set_local_time(self, hh, mm, ss):
        """
        Set the local Time to HH:MM:SS.SS (hours, minutes, seconds and
        hundredths of second).
        
        :param hh: Hour
        :type hh: int
        :param mm: minute
        :type mm: int
        :param ss: seconds
        :type ss: float
        
        :returns: 0 if the input is invalid or 1 if the input is valid

        BEWARE of the leap seconds.
        """
        self.add_debug('mount set_local_time {}:{}:{}'.format(hh, mm, ss))

        self.send_command(':SL{:02d}:{:02d}:{:05.2f}#'.format(hh, mm, ss))

    def set_local_date_time(self, yyyy, mm, dd, hh, m, ss):
        """
        Set together the local date and time to YYYY-MM-DD,HH:MM:SS.SS
        
        :param yyyy: year
        :type yyyy: int
        :param mm: month
        :type mm: int
        :param dd: day
        :type dd: int
        :param hh: Hour
        :type hh: int
        :param m: minute
        :type m: int
        :param ss: seconds
        :type ss: float
        
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        
        BEWARE of the leap second.
        """
        self.add_debug('mount set_local_date_time {}-{}-{} {}:{}:{}'.format(yyyy, mm, dd,
                                                                            hh, m, ss))

        full_date = self.send_command(':SLDT{:04d}-{:02d}-{:02d},{:02d}:{:02d}:{:05.2f}'.format(yyyy, mm, dd,
                                                                                                hh, m, ss))

        return full_date

    def set_utc_date_time(self, yyyy, mm, dd, hh, m, ss):
        """
        Set together the UTC date and time to YYYY-MM-DD,HH:MM:SS.SS
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        
        BEWARE of the leap second.
        """
        self.add_debug('mount set_utc_date_time {}-{}-{} {}:{}:{}'.format(yyyy, mm, dd, hh, mm, ss))

        utc_date = self.send_command(':SUDT{:04d}-{:02d}-{:02d},{:02d}:{:02d}:{:05.2f}'.format(yyyy, mm, dd,
                                                                                               hh, m, ss))

        return utc_date

    def set_meridian_side(self, n):
        """
        Set meridian  side  behaviour,  where n  is an ASCII digit  (1..3).
        
        :param n: 
            1 both sides of the meridian allowed;
            2 only objects west of the meridian allowed;
            3 only objects east of the meridian allowed.
        :type n: int
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_meridian_side {}'.format(n))

        command = self.send_command(':SMF{}'.format(n))

        return command

    def set_low_alt_limit(self, dd):
        """
        Set the minimum altitude to which the telescope will slew to sDD degrees.
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount setLewAltLimit {}'.format(dd))

        command = self.send_command(':So{:+02d}#'.format(dd))
        return command

    def set_refraction(self, n):
        """
        Sets the current status of the refraction correction.
        :param n: 0 deactivate refraction correction or 1 activate refraction correction
        :type n: int
            
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_refraction {}'.format(n))

        refraction = self.send_command(':SREF{}#'.format(n))

        return refraction

    def set_pressure_in_model(self, p):
        """
        Sets the atmospheric pressure used in the refraction model to PPPP.P hPa. Note
        that this is the pressure at the location of the telescope, and not the pressure at sea level.
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_pressure_in_model {}'.format(p))

        command = self.send_command(":SRPRS{:06.1f}#".format(p))

        return command

    def set_temp_in_model(self, temperature):
        """
        Sets the temperature used in the refraction model to sTTT.T degrees Celsius
        ( degC).
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_temp_in_model {}'.format(temperature))

        command = self.send_command(':SRTMP{:+06.1f}#'.format(temperature))

        return command

    def set_speed_corr_flag(self, n):
        """
        :param n: 0 deactivate speed correction or 1 activate speed correction
        :type n: int
        
        Sets the current status of the speed correction flag (see the :GSC# command).
            
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        flag = self.send_command(':SSC{}#'.format(n))

        return flag

    def set_meridian_track_limit(self, dd):
        """
        :param dd: tracking limit
        :type dd: float
        
        Sets the meridian limit for tracking in degrees. The minimum value is the same as the
        meridian limit for slews.
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_meridian_track_limit {}'.format(dd))

        degree = str(dd)

        command = self.send_command(':Slmt{}#'.format(degree))

        return command

    def set_meridian_slew_limit(self, dd):
        """
        :param dd: slew rate
        :type dd: float
        
        Sets the meridian limit for slews in degrees. Setting a meridian limit for slews greater
        than the meridian limit for tracking will increase the meridian limit for tracking to the
        same value.
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_meridian_slew_limit {}'.format(dd))

        degree = str(dd)

        command = self.send_command(':Slms{}#'.format(degree))

        return command

    def set_unattended_flip(self, n):
        """
        Enables or disables the unattended flip. Use N=1 to enable, N=0 to disable. This is set
        always to 0 after power up.
        
        :returns: nothing
        """
        self.add_debug('mount setUnattenedFlip {}'.format(n))

        command = self.send_command(':Suaf{}#'.format(n))

        return command

    def set_lat(self, dd, mm, ss):
        """
        :param dd: degree
        :type dd: int
        :param mm: arcminutes
        :type mm: int
        :param ss: arcseconds
        :type ss: float
        
        Sets the current site latitude to sDD*MM:SS.S (sign, degrees, arcminutes,
        arcseconds and tenths of arcsecond)
        
        :returns: 0 if the input is invalid or 1 if the input is valid
        """
        self.add_debug('mount set_lat {}:{}:{}'.format(dd, mm, ss))

        command = self.send_command(':St{:+03d}*{:02d}:{:04.1f}#'.format(dd, mm, ss))

        return command

    def stop(self):
        """
        Halt all current movements, included tracking. If the mount is parked, parking or
        unparking it will be left in parked status. Otherwise, any movement command will
        return   the   mount   to   normal   ope_ration.   Tracking   can   be   restarted   with   the   :AP#
        command.
        
        :returns: nothing
        """

        self.add_debug('mount stop ')

        command = self.send_command(':STOP#')

        return command

    def set_max_slew_rate(self, n):
        """
        Set maximum slew rate to N degrees per second.
        :param n: the new slew rate
        :type n: float
        
        :returns: 0 if the slew rate is invalid or 1 if the slew rate is valid
        """

        self.add_debug('mount set_max_slew_rate ')

        rate = self.send_command(':Sw{}#'.format(n))

        return rate

    def set_lan_config(self, string):
        """
        Set the LAN interface configuration.
        To configure the LAN interface to get the IP address from a DHCP server, the string
        will be "1"
        To configure the LAN interface to a fixed IP address, the string will be
        "0,ip address,network mask,gateway"
        
        :returns: "1#" if the configuration has succeeded or "0#" if the configuration failed
        
        Note: if the parameters of the current connection are changed, it may happen that the
            connection is lost afterwards.
        """

        self.add_debug('mount setLanConfig {}'.format(string))

        lan = self.send_command(':SIP{}#'.format(string))

        return lan

    # ******************************************************************************
    # ******************************************************************************
    #                           TRACKING COMMANDS
    # ******************************************************************************
    # ******************************************************************************

    def pec_on(self):
        """
        Toggles the periodic error correction (pec) on and off. Has no effect if PEC training is active.
        Has no effect with the HPS mounts which don't feature PEC.
        
        :returns: nothing
        """

        self.add_debug('mount pecOn ')

        command = self.send_command(':$Q#')

        return command

    def pec_stop(self):
        """
        Stops the periodic error correction. Has no effect with the HPS mounts which don't
        feature PEC.
        
        :returns: nothing
        """
        self.add_debug('mount pec_stop ')

        command = self.send_command(':p#')

        return command

    def pec_activate(self):
        """
        Activates the periodic error correction. Has no effect with the HPS mounts which don't
        feature PEC.
        
        :returns: nothing
        """

        self.add_debug('mount pec_activate ')

        command = self.send_command(':pP#')

        return command

    def pec_start_training(self):
        """
        Starts the periodic error correction training. Has no effect with the HPS mounts which
        don't feature PEC.
        
        :returns: nothing
        """
        self.add_debug('mount pec_start_training ')

        command = self.send_command(':pR#')

        return command

    def pec_start_training2(self, x):
        """
        :param x: Number to select the modus.
        :type x: int
        
        Starts the periodic error correction training, where X has the following meaning:
            0 short training (~15 minutes at sidereal speed)
            1 medium training (~30 minutes at sidereal speed)
            2 long training (~60 minutes at sidereal speed)
            
        On an equatorial mount, only the R.A. axis is trained.
        On an alt-azimuth mount, both axes are trained. The duration is proportionally longer
        due to the slower rates. Has no effect with the HPS mounts which don't feature PEC.
        
        :returns: nothing
        """
        self.add_debug('mount pexStartTraining2 ')

        command = self.send_command(':pR{}#'.format(x))

        return command

    def track_rate_up(self):
        """
        Increment custom tracking rate by 0.025 arcseconds per second of time.
        :returns: nothing
        """
        self.add_debug('mount track_rate_up ')

        command = self.send_command(':T+#')

        return command

    def track_rate_down(self):
        """
        Decrement custom tracking rate by 0.025 arcseconds per second of time.
        :returns: nothing
        """

        self.add_debug('mount track_rate_down ')

        command = self.send_command(':T-#')

        return command

    def track_lunar(self):
        """
        Set lunar tracking rate
        :returns: nothing
        """

        self.add_debug('mount track_lunar ')

        command = self.send_command(':RT0#')

        return command

    def track_solar(self):
        """
        Set solar tracking rate
        :returns: nothing
        """

        self.add_debug('mount track_solar ')

        command = self.send_command(':RT1#')

        return command

    def track_custom(self):
        """
        Set custom tracking rate
        :returns: nothing
        """

        self.add_debug('mount track_custom ')

        command = self.send_command(':TM#')

        return command

    def track_sidereal(self):
        """
        Set default (sidereal) tracking rate
        :returns: nothing
        """

        self.add_debug('mount track_sidereal ')

        command = self.send_command(':RT9#')

        return command

    def track_stop(self):
        """
        Stop tracking.
        :returns: nothing
        """

        self.add_debug('mount track_stop ')

        command = self.send_command(':RT9#')

        return command

    def track_custom_ra(self, x):
        """
        Set custom tracking rate in right ascension, where sXXX.XXXX is expressed in
        multiples of the sidereal speed. The rate is added to the standard sidereal tracking.
        :returns: 1 valid
        """

        self.add_debug('mount track_custom_ra {}'.format(x))

        command = self.send_command(':RR{:+09.4f}#'.format(x))

        return command

    def track_custom_dec(self, x):
        """
        Set custom tracking rate in declination, where sXXX.XXXX is expressed in multiples
        of the sidereal speed.
        :returns: 1 valid
        """

        self.add_debug('mount track_custom DEC {}'.format(x))

        command = self.send_command(':RR{:+09.4f}#'.format(x))

        return command

    # ******************************************************************************
    # ******************************************************************************
    #                           OTHER COMMANDS
    # ******************************************************************************
    # ******************************************************************************

    def set_astro_physics_emul(self):
        """
        Sets Astro-Physics compatible emulation mode.
        :returns: nothing
        """
        self.add_debug('mount set_astro_physics_emul ')

        emul = self.send_command(':EMUAP#')

        return emul

    def set_lx200_emul(self):
        """
        Sets LX200 emulation mode.
        :returns: nothing
        """
        self.add_debug('mount set_lx200_emul ')

        emul = self.send_command(':EMULX#')

        return emul

    def start_log_file(self):
        """
        Starts a log of the commands received by the mount.
        :returns: nothing
        """
        self.add_debug('mount start_log_file ')

        value = self.send_command(':startlog#')

        return value

    def stop_log_file(self):
        """
        Ends the communication log.
        :returns: nothing
        """
        self.add_debug('mount stop_log_file ')

        value = self.send_command(':stoplog#')
        
        return value
        
    def get_log_file(self):
        """
        Gets the communication log.
        :returns: text containing the communication log (up to 256 Kb)
        """
        self.add_debug('mount get_log_file ')

        value = self.send_command(':getlog#')

        return value

    def get_event_log_file(self):
        """
        Gets the event log.
        :returns: a text containing the communication log (up to 3Kbytes).
        """
        self.add_debug('mount get_event_log_file ')

        value = self.send_command(':evlog#')

        return value

    def userok(self):
        """
        Allow the mount to move, after an inconsistency has been signaled. See also the :Gstat#
        command.
        :returns: nothing
        """
        self.add_debug('mount userok ')

        user = self.send_command(':USEROK#')

        return user

    def user_wait(self):
        """
        Stops the mount and waits the user to send the :USEROK# command or authorize
        movements again using the keypad. You can use this command to block the mount in
        case your system detects some inconsistency. See also the :Gstat# command.
        :returns: nothing
        """

        self.add_debug('mount user_wait ')

        user = self.send_command(':USERWAIT#')

        return user

    def get_id(self):
        """
        Gets an unique hardware identifier for the mount. The identifier does not change (unless
        the mount is serviced, which could lead to a different identifier).
        This command can be use to detect if different connections (i.e. a serial port and a LAN
        connection) are actually a connection to the same mount.
        
        :returns: a 20-digit (64-bit) number terminated by # unique for each mount. XXXXXXXXXXXXXXXXXXXX#
        """

        self.add_debug('mount get_id ')

        id_number = self.send_command(':GETID#')

        return id_number

    def adjust_dome_time(self, x):
        """
        Adjust the time of the mount of the given amount in milliseconds, from +999 to -999.
        
        :returns: "0#" if the command failed or "1#" if the command succeeded.
        """
        self.add_debug('mount adjustDimeTime {}'.format(x))

        command = self.send_command(':NUtim{:+04d}#'.format(x))

        return command


class SerialDummy:
    """
    Dummy-Class for the case that a serial module is not there
    """
    def __init__(self, debug):
        self.debug = debug

    def write(self, text):
        text = text + ''
        self.dummy()
        return text

    def open(self):
        self.dummy()

    def close(self):
        self.dummy()

    def dummy(self):
        self.debug.add('Serial Dummy')


class SerialDome:
    """
    Class to interact with devices which are connected via a serial port.
    """
    def __init__(self, debug=None):

        self.ser_light = None
        self.debug = debug
        if self.debug is not None:
            self.add_debug('init SerialDome')
        self.connect()
        self.lights_on = False
        self.humidifier_on = False

    def connect(self):
        """
        Starts a new connection.
        """
        try:
            self.ser_light = serial.Serial()
    
            self.ser_light.port = 'COM4'
            self.ser_light.baudrate = 19200
            self.ser_light.parity = serial.PARITY_NONE
            self.ser_light.stopbits = serial.STOPBITS_ONE
            self.ser_light.bytesize = serial.EIGHTBITS
            if self.debug is not None:
                self.add_debug('connect SerialDome')
        except NameError as e:
            print('Connect serial dome', e)
            if self.debug is not None:
                self.add_debug('name error connect SerialDome')
            self.ser_light = SerialDummy(self.debug)

    def add_debug(self, text):
        """
        Adds the text to the debug-file.
        
        :param text: the text
        :type text: str
        """
        try:
            if self.debug is not None:
                self.debug.add(text)
        except ValueError:
            pass

    def close_connection(self):
        """
        Closes every connection.
        """
        try:
            self.ser_light.close()
            if self.debug is not None:
                self.add_debug('close_connection SerialDome')
        except NameError:
            if self.debug is not None:
                self.add_debug('name error close_connection SerialDome')

    def lights_on(self):
        """
        Turns ON the lights in the dome connected via serial port
        """
        try:
            # dome lights ON
            self.ser_light.open()
            # self.ser_light.isOpen()
            self.ser_light.write('SE15\r\n')
            time.sleep(.100)
            self.ser_light.write('SO1\r\n')
            time.sleep(.100)
            #        self.ser_light.close()
    
            self.ser_light.close()
            self.lights_on = True
        except serial.SerialException:
            pass

    def lights_off(self):
        """
        Turns OFF the lights in the dome connected via serial port
        """
        try:
            # dome lights OFF
            self.ser_light.open()
            # self.ser_light.isOpen()
            self.ser_light.write('SE15\r\n')
            time.sleep(.100)
            self.ser_light.write('SO0\r\n')
            time.sleep(.100)
            #        self.ser_light.close()
    
            self.ser_light.close()
            self.lights_on = False
            self.humidifier_on = False
        except serial.SerialException:
            pass

    def humidifier_on(self):
        """
        Turns the humidifier on.
        """
        self.ser_light.open()
        self.ser_light.write('SE15\r\n')
        time.sleep(.100)
        self.ser_light.write('SO2\r\n')
        time.sleep(.100)
        self.ser_light.close()
        self.humidifier_on = True


class TcpDome:
    """
    Class to interact with the dome.
    """
    def __init__(self, mount, debug=None):
        self.mount = mount
        self.debug = debug

    def open_shutter(self):
        th = Thread(target=self.__open_shutter__)
        th.start()

    def __open_shutter__(self):
        """
        Opens the shutter by checking if it is open already or not.
        """
        # self.mount.send_command('#')
        self.add_debug('TcpDome open_shutter ')

        shutter = self.mount.send_command(':GDS#')
        if shutter == '2#':
            pass
        elif shutter == '1#':
            response = self.mount.send_command(':SDS2#')
            return response

        stat = self.mount.send_command(':GDS#')
        while stat != '2#':
            stat = self.mount.send_command(':GDS#')

    def close_shutter(self):
        """
        Closes the shutter by checking if it is closed already or not.
        """

        self.add_debug('TcpDome close_shutter ')
        shutter = self.mount.send_command(':GDS#')
        if shutter == '1#':
            pass
        elif shutter == '2#':
            response = self.mount.send_command(':SDS1#')
            return response

        stat = self.mount.send_command(':GDS#')
        while stat != '1#':
            stat = self.mount.send_command(':GDS#')

    def get_az(self):
        """
        Gets the dome azimuth, if a dome is connected.
        
        :returns:
            XXXX# which is the current azimuth of the dome
            in tenths of degree from 0 to 3599. In case of error, returns 9999#.
        """

        self.add_debug('TcpDome get_az ')

        az = self.mount.dome_pos
        try:
            az = az.split('#')[0]
            try:
                az = float(az)/10
                az = '{:05.1f} deg'.format(az)
            except ValueError:
                az = '000.0  deg'
        except AttributeError:
            az = '000.0  deg'

        return az

    def get_homing_status(self):
        """
        Gets the homing ope_ration status on the dome.
        
        :returns:
            0# if there is no homing ope_ration or
            1# if there is homing ope_ration in progress or
            2# there is homing ope_ration completed
        """

        self.add_debug('TcpDome get_homing_status ')

        self.mount.send_command(':GDH#')

    def get_slew_status(self):
        """
        Gets the status of the slew ope_ration for the dome. Use this command in place of :D# if
        you want to check if both the telescope and the dome have arrived at target. The result is
        valid only if the dome is under the control of the internal mount logic.
        
        :returns:
            0# if there is no slew in progress,
            dome at internally computed target or
            1# if there is slew in progress or dome not at internally computed target
        """
        self.add_debug('TcpDome get_slew_status ')

        command = self.mount.send_command(':GDW#')

        return command

    def get_slew_status2(self):
        """
        Gets the status of the slew ope_ration for the dome. The result is valid only if the dome is
        under external control via :SDA commands.
        
        :returns:
            0# if there is no slew in progress,
            dome at manually set target or 1# if there is a slew in progress,
            dome not at manually set target
        """

        self.add_debug('TcpDome get_slew_status2 ')

        command = self.mount.send_command(':GDw#')

        return command

    def start_homing(self):
        """
        Starts homing on the dome. Note that this command succeeds even if no dome is
        connected. Please use :GDA# or :GDS# to check if a dome is connected.
        """
        self.add_debug('TcpDome start_homing ')

        self.mount.send_command(':SDH#')

    def dome_radius(self, x):
        """
        Sets the dome radius to XXXX mm.
        :param x: the radius
        :type x: int
        
        :returns: nothing
        """

        command = self.mount.send_command(':SDR{:04d}#'.format(x))

        return command

    def set_dome_update_int(self, s):
        """
        Sets the dome update interval to SS seconds (i.e. the dome is commanded to an updated
        position every SS seconds).
        
        :returns: nothing
        """

        self.add_debug('TcpDome get_domeUpdateInt {}'.format(s))

        command = self.mount.send_command(':SDU{:02d}'.format(s))

        return command

    def slew_dome(self, x):
        """
        Slews the dome to the given azimuth (from 0 to 3600). This overrides the internal logic
        of the mount in order to give direct control of the dome azimuth to the controlling
        program. Setting any dome parameter from the keypad, or any of the following
        commands will give control again to the internal logic of the mount: :SDR, :SDT, :SDU,
        :SDXM, :SDYM, :SDZM, :SDX, :SDY, :SDAr.
        
        :returns: 0 if the argument is invalid (angle out of ammissible range) or 1 if the argument is valid
        """
        self.add_debug('TcpDome slew_dome {}'.format(x))

        self.mount.send_command(':SDA{:04d}#'.format(x))

    def auto_dome(self):
        """
        Release the dome control to the internal logic of the mount. 
        :returns: nothing
        """
        th = Thread(target=self.__autoDome__)
        th.start()

    def __autoDome__(self):
        """
        Release the dome control to the internal logic of the mount.
        
        :returns: nothing
        """

        self.add_debug('TcpDome auto_dome ')
        command = self.mount.send_command(':SDAr#')

        return command

    def add_debug(self, text):
        """
        Adds a the text to the debug file.
        :param text: new text for the debug file
        :type text: str
        """
        try:
            if self.debug is not None:
                self.debug.add(text)
        except ValueError:
            pass


def get_telescope_driver(telescope_driver=''):
    if telescope_driver != '':
        return CreateObject(telescope_driver)
    c = Chooser(device_type='telescope')
    t_name = c.choose()
    return CreateObject(t_name)
