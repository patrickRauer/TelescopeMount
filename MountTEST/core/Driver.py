# -*- coding: utf-8 -*-
"""
Created on Fri Oct 14 19:41:01 2016

@author: Jean Patrick Rauer

This file contains the basic level of comtype driver interaction. The classes 
are low level classes, this means you can use them as parent classes but not 
as a direct interaction to comtype drivers.
"""

from datetime import datetime
from threading import Lock
try:
    from comtypes import COMError
except ImportError:
    COMError = AttributeError
from comtypes.client import CreateObject
import os


class DriverLog:
    """
    The DriverLog is a log class for the drivers which are using the comtypes.
    It collects the changes/calls of the different method and if active_log 
    enabled it will save the information in a log file.
    With this class you can track the driver interactions to find ex. an error.
    """
    def __init__(self, log_file=''):
        self.last_update_time = datetime.now()
        self.last_update = 'ini'
        self.log_file = log_file
        self.active_log = False
        if self.log_file is not '':
            path = log_file.split('/')[-1]
            path = log_file.split(path)[0]
            if not os.path.exists(path):
                os.makedirs(os.path.abspath(path))
            self.active_log = True
        
    def set_new_update(self, update_kind):
        """
        Sets a new update information and write it to the log if log writing is
        active.
        
        :param update_kind: type of update
        :type update_kind: str
        """
        self.last_update = update_kind
        self.last_update_time = datetime.now()
        if self.active_log:
            self.write_log()
            
    def set_error_update(self, method, e):
        """
        Sets a new error information as the new status update. For this it 
        will convert the information and call :meth:`set_new_update`.
        
        :param method: Name of the method where the error happens
        :type method: str
        :param e: The error information
        :type e: Exception
        """
        self.set_new_update('error in ' + method + '\n' + str(e))
        
    def write_log(self):
        """
        Adds the last update to the log file.
        """
        f = open(self.log_file, 'a')
        f.write(self.last_update + '\t' +
                self.last_update_time.strftime("%Y-%m-%d %H:%M:%S") + '\n')
        f.close()
        
        
class Driver:
    """
    The Driver class is the basic class for comtype driver interaction. It has 
    the very basic methods to create a connection to a driver. It can be used 
    for all comtype drivers like interface, filter wheel or mount ASCOM-driver.
    """
    def __init__(self, driver_type, driver_name):
        """
        :param driver_type: The type of the driver in ASCOM-meaning.
        :type driver_type: str
        :param driver_name: Name of the driver
        :type driver_name: str
        """
        self.config_path = './config.txt'
        self.driver_type = driver_type
        self.driver = None
        self.connection = False
        print(driver_name)
        self.__driver_initialisation__(driver_name)
        self.error_message = ''
        self.driver_lock = Lock()
        
    def __driver_initialisation__(self, driver_name, test=False):
        """
        Initialized the ASCOM driver
        :param driver_name: Name of the driver
        :type driver_name: str
        :param test: True if the current run is a test else false
        :type test: bool
        """
        # If there is no information of the drivers
        if driver_name == '':
            if driver_name == '':
                cam = Chooser(device_type=self.driver_type)
                driver_name = cam.choose()
                if not test:
                    set_driver_information(self.config_path, self.driver_type,
                                           driver_name)
        # Create an object of a COM-object of the interface
        self.driver = CreateObject(driver_name)
        self.connect()

    def connect(self):
        """
        Starts the connection to the ASCOM driver
        """
        try:
            self.driver.Connected = True
            self.connection = True
        except COMError:
            self.connection = False
        
    def disconnect(self):
        """
        Closes the connection to the ASCOM driver
        """
        self.driver.Connected = False
        self.connection = False
        
    def __create_error_message__(self, message):
        """
        Creates a proper error message with the message itself and stores the 
        message with additional information. The error message is available by 
        the method :meth:`get_error_message`.
        
        :param message: The message of the error
        :type message: str
        """
        message += '\n'
        # adds time information of the error
        message += 'Time: ' + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # store the complete error message 
        self.error_message = message
        print(message)
        
    def get_error_message(self):
        """
        Returns the last error message
        
        :returns: last error message
        :rtype: str
        """
        return self.error_message
    
    def is_connect(self):
        """
        Asks if the device is connected or not.
        
        :returns: True if the device is connected, else False
        :rtype: bool
        """
        return self.connection

        
class Chooser:
    """
    Class to choose 
    
    :param device_type: the type of device like 'Camera' or 'Filterwheel'
    :type device_type: str
    """
    def __init__(self, device_type='Camera'):
        self.c = CreateObject("ASCOM.Utilities.Chooser")
        self.c.DeviceType = device_type

    def choose(self):
        """
        Open a dialog to select the driver
        """
        name = self.c.Choose('')
        return name

    def telescope(self):
        self.c.DeviceType = 'Telescope'
        return CreateObject(self.choose())


def get_driver_information(path, driver_type):
    """
    Return the driver information from the config-file
    
    :param path:
        Path to the config-file
    :type path:
    :param driver_type:
        Camera or Filterwheel to select the right information
    :type path: str
        
    :returns: Internal name of the ascom driver
    :rtype: str
    """
    f = open(path)
    driver_info = ''
    for line in f:
        row = line.split('\t')
        if row[0] == driver_type:
            driver_info = row[1]
            if len(row) == 2:
                driver_info = driver_info.split('\n')[0]
            break
    f.close()
    return driver_info


def set_driver_information(path, driver_type, driver_name):
    """
    Sets new driver information (previous driver information won't be replaced)
    
    :param path:
        Path to the config-file
    :type path: str
    :param driver_type:
        Camera or Filterwheel
    :type driver_type: str
    :param driver_name:
        Internal driver name of ascom
    :type driver_name: str
    """
    if os.path.exists(path):
        f = open(path, 'a')
    else:
        f = open(path, 'w')
    try:
        lines = f.readlines()
        prefix = ''
        if '\n' not in lines[-1]:
            prefix = '\n'
        f.write('{}{}\t{}\t\n'.format(prefix, driver_type, driver_name+'\n'))
        f.flush()
    except IOError as e:
        print(e)

    f.close()
