# -*- coding: utf-8 -*-
"""
Created on Mon Feb 15 20:49:32 2016

@author: Patrick Rauer
"""
from threading import Thread
import time


class Command:
    def __init__(self, id_number, command, output):
        self.ID = id_number
        self.command = command
        self.output = output
        self.time = time.time()

    def __str__(self):
        try:
            return str(self.ID)+' '+self.command+' '+self.output
        except TypeError:
            return str(self.ID)+' '+self.command


class MountCom(Thread):
    """
    Basic class to communicate with the mount.
    
    :param debug: Debug-object to collect debug information
    :type debug: :class:`debug.Debug`
    """
    def __init__(self, debug=None):
        """
        """
        Thread.__init__(self)
        
        self.debug = debug
        self.add_debug('Mount_Com ini')
        self.target_ra = '00:00:00.0'
        self.target_dec = '+00:00:00.0'
        self.telescope_ra = '00:00:00.0'
        self.telescope_dec = '+00:00:00.0'
        self.status = ''
        self.dome_pos = ''
        self.shutter_status = 2
        self.command_read_out = 0
        self.command_output_queue = []
        self.active = True
        self.current_id = 0
        self.time_dif = 0.01
        self.warning = ''
        self.warning_read = False
        self.information = ''
        self.information_read = False
        self.information_flip = False
        self.tracking_status = 0
        self.tracking_time = '100#'
        self.command_outside_wait = False
        self.interrupted_run = False

    def add_debug(self, text):
        """
        Adds the text to the debug-file.
        
        :param text: the text
        :type text: str
        """
        try:
            if self.debug is not None:
                self.debug.add(text)
        except AttributeError:
            pass

    def outside_command(self):
        
        #   proof of the command from outside and sending the command to the mount
        #   and put the output into the output queue
        while self.command_outside_wait:
            self.interrupted_run = True
            time.sleep(self.time_dif)
        self.interrupted_run = False

    def run(self):
        """
        Method for Threading
        Interacting with the mount directly
        """
        self.add_debug('start run-method in Mount_Com')
        while self.active:
            try:
                # print self.active
                # self.outside_command()
                self.update_target_pos()
                # time.sleep(0.1)
                self.outside_command()
                self.update_telescope_pos()
                time.sleep(self.time_dif)
                self.outside_command()
                self.update_mount_status()
                time.sleep(self.time_dif)
                self.update_dome_pos()
                time.sleep(self.time_dif)
                self.update_shutter_status()
                time.sleep(self.time_dif)
                self.update_tracking_time()
                time.sleep(self.time_dif)
                # print self
                self.save_mount()
                time.sleep(self.time_dif)
            except ValueError:
                pass

    def save_mount(self):
        """
        Checks if the mount can track without problems
        """
        estimated_time = self.get_estimate_tracking_time()
        if estimated_time is not None:
            estimated_time = estimated_time.split('#')[0]
            estimated_time = int(estimated_time)
            # If the mount can only 60 minutes more
            if estimated_time < 60:
                flip = self.flip_mount()
                # If the flip wasn't successful
                if flip == 0:
                    self.warning = 'Warning: telescope can be damaged in max. ' + str(estimated_time) + ' minutes'
                    self.warning_read = False
                else:
                    self.information_flip = False
                # If the mount can only track 30 minutes more, stop tracking
                if estimated_time < 30:
                    self.stop()
                    self.warning = 'Telescope stops'
                    self.warning_read = False
                    self.information_flip = False
            elif estimated_time <= 75 and not self.information_flip:
                self.information = 'telescope will flip in 15 min'
                self.information_read = False
                self.information_flip = True

    def flip_mount(self):
        """
        Flips the mount
        """
        ra = self.telescope_ra.split('#')[0]
        dec = self.telescope_dec.split('#')[0]
        ra = ra.split(':')
        dec = dec.split(':')
        try:
            self.slew_ra_dec(int(ra[0]), int(ra[1]), float(ra[2]),
                             int(dec[0]), int(dec[1]), float(dec[2]))
        except IndexError:
            pass
        return -1

    def slew_ra_dec(self, ra_hour, ra_min, ra_sec, dec_deg, dec_min, dec_sec):
        """
        Slew to coordinates. This method is empty an must overwrite.
        
        :param ra_hour: hourangle
        :type ra_hour: int
        :param ra_min: arc-minute
        :type ra_min: int
        :param ra_sec: arcsecond
        :type ra_sec: float
        :param dec_deg: declination angle
        :type dec_deg: int
        :param dec_min: arc-minute
        :type dec_min: int
        :param dec_sec: arc-second
        :type dec_sec: float
        """
        pass

    def stop(self):
        return -1

    def get_estimate_tracking_time(self):
        return ''

    def set_command(self, command):
        """
        Send a command to the mount and waits until the mount response.
        During this time there will be no other communication with the mount.
        
        :param command: The command
        :type command: str
        
        :return: The return value from the mount if the mount gives something back else None
        """
        self.command_outside_wait = True
        time.sleep(0.1)
        while not self.interrupted_run:
            time.sleep(0.1)
        output = self.send_command_to_mount(command)
        time.sleep(0.1)
        self.command_outside_wait = False
        return output
    
    def update_shutter_status(self):
        """
        Updates the shutter position if there is a connection to the mount.
        If not it will set the default value 1 which implies that the shutter is closed.
        """
        shutter_status = self.send_command_to_mount(':GDS#')
        if shutter_status is not None:
            self.shutter_status = int(shutter_status.split('#')[0])
        else:
            self.shutter_status = 1
#        self.shutter_status = 2

    def get_command_output(self, command_id):
        """
        Returns the oldest return value from the mount
        """
        self.add_debug('get_command_output')
        count = 0
        while len(self.command_output_queue) == 0:
            time.sleep(0.5)
            count += 1
            if count == 5:
                break
        # print 'output queue', self.command_output_queue
        if len(self.command_output_queue) > 0:
            counter = 0
            right = False
            output = None
            while counter < 10 and not right:
                output_list = []
                t = time.time()

                for i in range(len(self.command_output_queue)):
                    out = self.command_output_queue[i]
                    # print 'command output', out.ID, command_id
                    if out.ID == command_id:
                        output = out
                    # print 'command output delta t', t-out.time
                    if t-out.time < 60:
                        output_list.append(out)
                self.command_output_queue = output_list
                if output is None:
                    time.sleep(0.5)
                else:
                    right = True
            self.command_read_out -= 1
            return output
        # If queue is empty
        else:
            print("Output queue is empty.")
            return None

    def update_target_pos(self):
        """
        Updates the target position which is stored in the mount if there is a connection to the mount.
        If not it will set the default values to the target positions.
        """
        self.target_ra = self.send_command_to_mount(':U1#:Gr#')
        self.target_dec = self.send_command_to_mount(':U2#:Gd#')
        if self.target_ra is None:
            self.target_ra = '00:00:00.0'
        if self.target_dec is None:
            self.target_dec = '+00:00:00.0'

    def update_telescope_pos(self):
        """
        Updates the telescope position if there is a connection to the mount.
        If not then it will set the default values to the telescope position.
        """
        self.telescope_ra = self.send_command_to_mount(':U1#:GR#')
        self.telescope_dec = self.send_command_to_mount(':U2#:GD#')
        if self.telescope_ra is None:
            self.telescope_ra = '00:00:00.0'
        if self.telescope_dec is None:
            self.telescope_dec = '+00:00:00.0'

    def update_dome_pos(self):
        """
        Updates the dome position if there is a connection to the mount.
        If not it will set the default values to the dome position.
        """
        dome_pos = self.send_command_to_mount(':GDA#')
        if dome_pos is not None:
            dome_pos = dome_pos.split('#')[0]
            if dome_pos != '':
                dome_pos = float(dome_pos)
            else:
                dome_pos = 9999
        else:
            dome_pos = 9999
        self.dome_pos = dome_pos/10

    def update_mount_status(self):
        """
        Updates the mount status if there is a connection to the mount.
        If not it will set the default value '-1' which means that there is no connection.
        """
        self.status = self.send_command_to_mount(':Gstat#')
        if self.status is None:
            self.status = '-1'

    def update_tracking_status(self):
        """
        Updates the tracking status of the mount if there is a connection to the mount.
        If not it will set the default value 0 which means that there is no tracking.
        """
        status = self.send_command_to_mount(':GTRK#')
        if status is not None:
            try:
                self.tracking_status = int(status)
            except ValueError:
                self.tracking_status = int(status.split('#')[0])
        else:
            self.tracking_status = 0

    def update_tracking_time(self):
        """
        Updates time to the meridian. If there is no connection the mount if 
        will set the tracking time to 100.
        """
        tracking_time = self.send_command_to_mount(':Gmte#')
        if tracking_time is not None:
            self.tracking_time = tracking_time
        else:
            self.tracking_time = '100#'

    def send_command_to_mount(self, command):
        """
        Sends a command to the mount

        :param command: The command for the mount
        :type command: str
        :return: The answer of the mount
        :rtype: str
        """
        return ''

    def __str__(self):
        try:
            out = 'RA: {}\tDec: {}\tStatus: {}'.format(self.telescope_ra, self.telescope_dec, self.status)
        except AttributeError:
            out = 'some problems i don\'t know'
        return out
