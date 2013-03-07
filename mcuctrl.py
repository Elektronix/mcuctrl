#!/usr/bin/env python
# -*- coding: utf-8 -*- 
'''
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

from __future__ import with_statement

import os
import sys
import time
import atexit
import logging
import ConfigParser
from logging import handlers
from optparse import OptionParser
from optparse import OptionGroup
from optparse import OptionValueError
from signal import SIGTERM
from smbus import SMBus

__author__ = u'Rolf Håvard Blindheim'
__copyright__ = 'Copyright 2011, Elektronix AS'
__credits__ = ['Sander Marechal']
__license__ = 'GPL'
__version__ = '1.0'
__maintainer__ = u'Rolf Håvard Blindheim'
__email__ = 'rolf@elektronix.no'
__status__ = 'production'


# DO NOT EDIT
# These are constants for MCU command addresses
# for the I801 SMBUS adapter in the AFL-408B computer
#
# Options ending with _R = Read commands
# Options ending with _W = Write commands
# Options ending with _RW = ReadWrite commands
BRIGHTNESS_R = 0x01
VOLUME_R = 0x02
INCREASE_BRIGHTNESS_W = 0x03
DECREASE_BRIGHTNESS_W = 0x04
INCREASE_VOLUME_W = 0x05
DECREASE_VOLUME_W = 0x06
MUTE_W = 0x07
BRIGHTNESS_W = 0x08
VOLUME_W = 0x09
INVERTER_W = 0x0a
FW_VERSION_R = 0x11
FLAG_R = 0x12
POLLING_W = 0x13
BACKLIGHT_W = 0x14
AUTO_DIMMING_W = 0x15
FW_TYPE_R = 0x16
BACKLIGHT_R = 0x17
RD_NAME_R = 0x18
FUNCTION_R = 0x19
LUX_MODE_R = 0x1b
CHANGE_STATUS_R = 0x1c
LUX_MODE_W = 0x20
KEYPAD_LOCK_W = 0x21
BRIGHTNESS_PWM_MIN_RW = 0x22
BRIGHTNESS_PWM_MAX_RW = 0x23

class MCUSettings(object):
    '''
    Class for overriding default settings from config file
    
    Valid options are:
        mcu_bus:                 Set MCU bus address.
                                 0 indicates /dev/i2c-0,
                                 1 indicates /dev/i2c-1, etc
        mcu_address:             Hexadecimal address of MCU
        min_pwm_threshold:       Minimum PWM Brightness value
        max_pwm_threshold:       Maximum PWM Brightness value
        default_brightness:      Brightness level daemon should
                                 set
        check_interval:          Interval in seconds between each
                                 check
        pidfile:                 Location of program pidfile
        logfile:                 Location of program logfile
        logrotate_backoup_count: How many backups to keep
        logfile_max_size:        Max size in bytes before rotating
                                 logfiles
        loglevel:                debug|info|warning|error|critical
    '''
    defaults = {
        'mcu_bus' : 0,
        'mcu_address' : 0x00,
        'max_pwm_threshold' : 100,
        'min_pwm_threshold' : 0,
        'default_brightness' : 20,
        'check_interval' : 300,
        'pidfile' : '/var/run/mcuctrl.pid',
        'logfile' : '/var/log/mcuctrl.log',
        'logrotate_backup_count' : 5,
        'logfile_max_size' : 102400,
        'loglevel' : 'error'
    }
    
    def __init__(self):
        '''
        Load and override default settings from mcuctrl.conf.
        Applying default where omitted from config file.
        
        NOTE: object attributes are not set before class is
              initialized.
        '''
        config = ConfigParser.RawConfigParser()
        try:
            # make sure config file exists and is readable
            with open('/etc/mcuctrl.conf') as f:
                f.close()
            
            # read config file
            config.read('/etc/mcuctrl.conf')
            cfg = {}
            for key, val in config.items('main'):
                cfg.update({key : val})
            
            # replace defaults with values from config file
            for name, default in self.defaults.iteritems():
                value = cfg.get(name, default)
                setattr(self, name, value)
        except IOError, e:
            # no use to try to log this; logger does not exist
            print e
            sys.exit(1)
        except Exception, e:
            print e
            __mcu_logger__.critical(e)
            sys.exit(1)
        
    
    def get_logger(self):
        '''
        Initialize and return logger instance.
        Use settings from mcuctrl.conf.
        '''
        try:
            logger = logging.getLogger('mcuctrl')
            formatter = logging.Formatter(
                   '%(asctime)s %(levelname)s %(name)s - %(message)s',
                   '%Y-%m-%d %H:%M:%S')
            handler = logging.handlers.RotatingFileHandler(
                    filename=__mcu_settings__.logfile, mode='a',
                    maxBytes=__mcu_settings__.logfile_max_size,
                    backupCount=__mcu_settings__.logrotate_backup_count)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            levelmap = {'debug': logging.DEBUG, 'info': logging.INFO,
                        'warning' : logging.WARNING, 'warn': logging.WARN,
                        'error': logging.ERROR, 'critical': logging.CRITICAL}
            logger.setLevel(levelmap.get(__mcu_settings__.loglevel, logging.ERROR))
        except Exception, e:
            print e
            sys.exit(1)

        return logger
    
    get_logger = classmethod(get_logger)
        

class Daemon(object):
    '''
    Generic daemon class with UNIX double fork magic.
    Usage: subclass this class and override run() method
    Example from 
    http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/
    '''
    def __init__(self, pidfile, stdin=os.path.devnull,
                 stdout=os.path.devnull, stderr=os.path.devnull):
        self.pidfile = pidfile
        self.pid = None
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        
    def deamonize(self):
        '''
        do the UNIX double-fork magic, see Stevens' "Advanced
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        '''
        # first fork
        try:
            pid = os.fork()
            if pid > 0:
                # exit first parent
                sys.exit(0)
        except OSError, e:
            message = 'first fork failed: %d (%s)\n' % (e.errno, e.args[1])
            sys.stderr.write(message)
            __mcu_logger__.critical(message)
            sys.exit(1)
        
        # decouple from parent environment
        os.chdir('/')
        os.setsid()
        os.umask(0)
        
        # second fork
        try:
            pid = os.fork()
            if pid > 0:
                # exit second parent
                sys.exit(0)
        except OSError, e:
            message = 'second fork failed %d (%s)\n' % (e.errno, e.args[1])
            sys.stderr.write(message)
            __mcu_logger__.critical(message)
            sys.exit(1)
        
        # do this only for production code
        # uncomment to redirect std file descriptors from daemon to /dev/null
#        if __status__ == 'production':
#            sys.stdout.flush()
#            sys.stderr.flush()
#            std_in = file(self.stdin, 'r')
#            std_out = file(self.stdout, 'a+')
#            std_err = file(self.stderr, 'a+', 0)
#            os.dup2(std_in.fileno(), sys.stdin.fileno())
#            os.dup2(std_out.fileno(), sys.stdout.fileno())
#            os.dup2(std_err.fileno(), sys.stderr.fileno())
    
        # write pidfile
        atexit.register(self.del_pid)
        self.pid = os.getpid()
        
        __mcu_logger__.debug('daemon PID is %d' % self.pid)
        file(self.pidfile, 'w+').write('%d\n' % self.pid)
        __mcu_logger__.debug('wrote pidfile %s' % self.pidfile)
        
    def del_pid(self):
        '''
        Delete pidfile
        '''
        os.remove(self.pidfile)
        __mcu_logger__.debug('removed pidfile %s' % self.pidfile)
        
    def start(self):
        '''
        Start the daemon
        '''
        # check for pidfile to determine if daemon is running
        try:
            pidfile = file(self.pidfile, 'r')
            pid = int(pidfile.read().strip())
            pidfile.close()
        except IOError:
            pid = None
        
        if pid:
            message = 'pidfile %s already exists. Is daemon already running?\n'
            sys.stderr.write(message % self.pidfile)
            __mcu_logger__.warning(message % self.pidfile)
            sys.exit(1)
        
        # start daemon
        self.deamonize()
        self.run()
        
    def stop(self):
        '''
        Stop the daemon
        '''
        # get pid from pidfile
        try:
            pidfile = file(self.pidfile, 'r')
            pid = int(pidfile.read().strip())
            pidfile.close()
        except IOError:
            pid = None
        
        if not pid:
            message = 'pidfile %s does not exist. Is daemon running?\n'
            sys.stderr.write(message % self.pidfile)
            __mcu_logger__.warning(message % self.pidfile)
            return      # not an error if restarting
        
        # try killing the daemon process
        try:
            while True:
                os.kill(pid, SIGTERM)
                time.sleep(0.1)
            self.pid = None
        except OSError, e:
            err = str(e)
            if err.find("No such process") > 0:
                if os.path.exists(self.pidfile):
                    self.del_pid()
            else:
                # print error message and exit
                print err
                __mcu_logger__.critical(err)
                sys.exit(1)
        print '%s stopped' % sys.argv[0]
        __mcu_logger__.info('daemon stopped')
        
    def restart(self):
        '''
        Restart the daemon
        '''
        __mcu_logger__.info('restarting daemon')
        self.stop()
        self.start()
        
    def run(self):
        '''
        Daemon runtime code.
        '''
        print '%s started' % sys.argv[0]
        __mcu_logger__.info('daemon running')
        mcu = MCUControl(__mcu_settings__.mcu_bus,
                         __mcu_settings__.mcu_address)
        while True:
            __mcu_logger__.debug('daemon performing checks..')
            # compare actual values to config file values
            cur_pwm_min = mcu.read_byte('pwm_min')
            cur_pwm_max = mcu.read_byte('pwm_max')
            cur_brightness = mcu.read_byte('brightness')
            cfg_pwm_min = __mcu_settings__.min_pwm_threshold
            cfg_pwm_max = __mcu_settings__.max_pwm_threshold
            cfg_brightness = __mcu_settings__.default_brightness
            
            try:
                flag = False
                if not cur_pwm_min == int(cfg_pwm_min):
                    flag = True
                    __mcu_logger__.warning('[%d] PWM MIN Read %d (0x%02x). Applying corrective meassures' \
                                        % (self.pid, cur_pwm_min, int(cfg_pwm_min)))
                    mcu.write_byte('pwm_min', int(cfg_pwm_min))
                if not cur_pwm_max == int(cfg_pwm_max):
                    flag = True
                    __mcu_logger__.warning('[%d] PWM MAX Read %d (0x%02x). Applying corrective meassures' \
                                        % (self.pid, cur_pwm_max, int(cfg_pwm_max)))
                    mcu.write_byte('pwm_max', int(cfg_pwm_max))
                # If flag is set, set brightness to default value
                if flag:
                    __mcu_logger__.warning('[%d] BRIGHTNESS Read %d (0x%02x). Applying corrective meassures' \
                                        % (self.pid, cur_brightness, int(cfg_brightness)))
                    mcu.write_byte('brightness', int(cfg_brightness))
                else:
                    __mcu_logger__.debug('daemon - all values within threshold,')
            except Exception, e:
                print e
                __mcu_logger__.critical(e.args[1])
                sys.exit(1)
            
            __mcu_logger__.debug('daemon done performing checks')
            time.sleep(int(__mcu_settings__.check_interval))


class MCUControl(object):
    '''
    This class handles reading and writing to the
    MCU through the python smbus interface.
    '''
    def __init__(self, busno=0,
                 address=0x34):
        self.busno = busno
        self.address = address
        
        try:
            self.bus = SMBus(int(busno))
        except IOError, e:
            message = 'Could not open smbus /dev/i2c-%d. %s' % (int(busno), e.args[1])
            print message
            __mcu_logger__.critical(message)
            sys.exit(1)
            
    def read_byte(self, cmd):
        cmd_read_map = {
           'brightness' : BRIGHTNESS_R,
           'volume' : VOLUME_R,
           'fw' : FW_VERSION_R,
           'fwtype' : FW_TYPE_R,
           'flag' : FLAG_R,
           'backlight' : BACKLIGHT_R,
           'rdname' : RD_NAME_R,
           'function' : FUNCTION_R,
           'luxmode' : LUX_MODE_R,
           'change_status' : CHANGE_STATUS_R,
           'pwm_max' : BRIGHTNESS_PWM_MAX_RW,
           'pwm_min' : BRIGHTNESS_PWM_MIN_RW
           }
        
        try:
            cmd_value = cmd_read_map[cmd]
            retval = self.bus.read_byte_data(int(self.address, 16), cmd_value)
        except KeyError, e:
            print 'Command not found: %s' % cmd
            sys.exit(1)
        except Exception, e:
            print e
            __mcu_logger__.error(e.args[1])
            sys.exit(1)

        return retval
    
    def write_byte(self, cmd, value):
        cmd_write_map = {
           'inc_brightness' : INCREASE_BRIGHTNESS_W,
           'dec_brightness' : DECREASE_BRIGHTNESS_W,
           'inc_volume' : INCREASE_VOLUME_W,
           'dec_volume' : DECREASE_VOLUME_W,
           'mute' : MUTE_W,
           'volume' : VOLUME_W,
           'brightness' : BRIGHTNESS_W,
           'inverter' : INVERTER_W,
           'polling' : POLLING_W,
           'backlight' : BACKLIGHT_W,
           'auto_dimming' : AUTO_DIMMING_W,
           'luxmode' : LUX_MODE_W,
           'keypad_lock' : KEYPAD_LOCK_W,
           'pwm_max' : BRIGHTNESS_PWM_MAX_RW,
           'pwm_min' : BRIGHTNESS_PWM_MIN_RW
           }
        
        try:
            # read and validate pwm_min, pwm_max and brightness from config 
            # before saving new values.
            cfg_pwm_min = __mcu_settings__.min_pwm_threshold
            cfg_pwm_max = __mcu_settings__.max_pwm_threshold
            
            # save new settings
            cmd_value = cmd_write_map[cmd]
            self.bus.write_byte_data(int(self.address, 16),
                                     cmd_value, int(value))
            __mcu_logger__.info('Wrote %s value %d (0x%02x)' % (cmd, int(value), int(value)))
            
            # make sure min and max pwm thresholds always are in range
            if self.read_byte('pwm_min') < int(cfg_pwm_min):
                self.bus.write_byte_data(int(self.address, 16),
                                     cmd_write_map['pwm_min'], int(cfg_pwm_min))
                __mcu_logger__.warning('PWM MIN out of defined range: Wrote new value %d (0x%02x)' \
                                    % (int(cfg_pwm_min), int(cfg_pwm_min)))
            if self.read_byte('pwm_max') > int(cfg_pwm_max):
                self.bus.write_byte_data(int(self.address, 16),
                                     cmd_write_map['pwm_max'], int(cfg_pwm_max))
                __mcu_logger__.warning('PWM MAX out of defined range: Wrote new value %d (0x%02x)' \
                                    % (int(cfg_pwm_max), int(cfg_pwm_max)))
        
        except KeyError, e:
            print 'Command not found: %s' % cmd
            sys.exit(1)
        except Exception, e:
            print e
            __mcu_logger__.error(e.args[1])
            sys.exit(1)

        return True
    

# Global objects
__mcu_settings__ = MCUSettings()
__mcu_logger__ = MCUSettings.get_logger()

if __name__ == '__main__':
    # create the daemon instance
    daemon = Daemon(__mcu_settings__.pidfile)
    
    #
    # optpars callback functions
    #
    def read_mcu_callback(option, opt_str, value, parser):
        '''
        Validate arguments, and process read command
        '''
        if not parser.values.bus:
            raise OptionValueError('must set bus number before read option')
        if not parser.values.addr:
            raise OptionValueError('must set address before read option')
            
        # make sure bus and address are numeric values
        try:
            mcu_bus = '%d' % int(parser.values.bus)
            mcu_addr = '%x' % int(parser.values.addr)
            mcu = MCUControl(busno=mcu_bus, address=mcu_addr)
            retval = mcu.read_byte(value)
            print 'Read %s: %d (0x%02x)' % (value, retval, retval)
        except Exception, e:
            print e
            __mcu_logger__.debug(e.args[1])
            sys.exit(1)
        
        
    def write_mcu_callback(option, opt_str, value, parser):
        '''
        Validate arguments, and process write command
        '''
        if not parser.values.bus:
            raise OptionValueError('must set bus number before write option')
        if not parser.values.addr:
            raise OptionValueError('must set address before write option')
            
        # make sure bus and address are numeric values
        try:
            mcu_bus = '%d' % int(parser.values.bus)
            mcu_addr = '%x' % int(parser.values.addr)
            mcu = MCUControl(busno=mcu_bus, address=mcu_addr)
            mcu.write_byte(value[0], value[1])
            print 'Wrote %s: %d (0x%02x)' % (value[0], int(value[1]), int(value[1]))
        except Exception, e:
            print e
            __mcu_logger__.debug(e.args[1])
            sys.exit(1)
    
    def daemon_callback(option, opt_str, value, parser):
        '''
        This callback method controls the start, stop and restart
        commands from optparse to the daemon.
        '''
        try:
            if value == 'start':
                print 'Trying to start daemon...'
                daemon.start()
            elif value == 'stop':
                print 'Trying to stop daemon...'
                daemon.stop()
            elif value == 'restart':
                print "Trying to restart daemon..."
                daemon.restart()
            else:
                print 'mcuctrl: unkown command: %s' % value
        except Exception, e:
            print e
            __mcu_logger__.debug(e)
            sys.exit(1)
    
    #
    # parse command line arguments
    #
    descr = '''This program can be run as a daemon, which only task
is to make sure that MCU PWM Minimum and Maximum values,
as well as brightness level are within threshold set in mcuctrl.conf.
The program can also be run as a command line program to set MCU
values through the SMBUS interface. NOTE: This program only support reading
or writing byte data.'''
    
    epilog = '''%s <%s>. %s''' % (__author__, __email__, __copyright__)
    
    usage = 'usage %prog [options]'
    parser = OptionParser(description=descr, epilog=epilog)
    parser.add_option('-b', '--bus', type='string',
          dest='bus', action='store', help='MCU bus. This must be a decimal \
                  number representing the /dev/i2c-x device. A given value \
                  of 0 indicates /dev/i2c-0, 1 indicates /dev/i2c-1 and so on')
    parser.add_option('-a', '--address', type='int',
          dest='addr', action='store',
          help='MCU address. Can be hex(0x34) or decimal(52)')
    parser.add_option('-r', '--read', type='string',
          dest='read', action='callback', callback=read_mcu_callback,
          help='read MCU option. Valid commands are: \
                  brightness, volume, fw, fwtype, flag, backlight,\
                  rdname, function, luxmode, change_status,\
                  pwm_min, pwm_max. All values are read out \
                  in decimal numbers')
    parser.add_option('-w', '--write', type='string', nargs=2,
          dest='write', action='callback', callback=write_mcu_callback,
          help='write MCU option. Valid commands are: inc_brightness, \
                  dec_brightness, inc_volume, dec_volume, mute, volume, \
                  brightness, inverter, polling, backlight, auto_dimming, \
                  luxmode, keypad_lock, pwm_min, pwm_max. All values must be \
                  decimal(18) numbers')
    daemon_group = OptionGroup(parser, title='Daemon options',
                       description='Control mcuctrl daemon behavior')
    daemon_group.add_option('-d', '--daemon', action='callback',
                        callback=daemon_callback,
                        type='string', dest='cmd',
                        help='control daemon behavior. Valid options\
                         are start, stop, or restart.')

    parser.add_option_group(daemon_group)
    (options, args) = parser.parse_args()
    
