mcuctrl
=======

Python daemon to monitor the Brightness of MCU in the AFL-408BB computer.


Installation
------------

#. Copy mcuctrl.py to somewhere in your PATH (eg. /usr/local/bin)
#. Copy mcuctrl.conf to `/etc/mcuctrl.conf`
#. Edit `/etc/mcuctrl.conf` to your liking
#. Start with

    .. code-block:: none

        root@computer:~# python /usr/local/bin/mcuctrl -d start
