#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Shows the positions of the fingers on a touchpad.
# It interprets the MT protocol as defined in Linux Documentation/input/multi-touch-protocol.rst

# Copyright 2010-2019, Eric Piel <eric.piel@tremplin-utc.net>

# This file contains part of touchd - 2008, Scott Shawcroft, scott.shawcroft@gmail.com
# This file uses pyinputevent available http://github.com/rmt/pyinputevent/ by Robert Thomson and individual contributors.

# FingerViewer is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

# FingerViewer is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with FingerViewer.  If not, see <http://www.gnu.org/licenses/>.

# Runs the finger view window.
# use a command like:
# sudo python fingerviewer.py /dev/input/event1

from __future__ import division, print_function

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk, Gdk

import math
import time
import threading
import logging
import cairo
from pyinputevent import *

# As defined in include/uapi/linux/input-event-codes.h
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

SYN_REPORT    = 0
SYN_CONFIG    = 1
SYN_MT_REPORT = 2
SYN_DROPPED   = 3

ABS_PRESSURE   = 0x18
ABS_DISTANCE   = 0x19
ABS_TILT_X     = 0x1a
ABS_TILT_Y     = 0x1b
ABS_TOOL_WIDTH = 0x1c

ABS_MT_SLOT        = 0x2f    # MT slot being modified
ABS_MT_TOUCH_MAJOR = 0x30    # Major axis of touching ellipse
ABS_MT_TOUCH_MINOR = 0x31    # Minor axis (omit if circular)
ABS_MT_WIDTH_MAJOR = 0x32    # Major axis of approaching ellipse
ABS_MT_WIDTH_MINOR = 0x33    # Minor axis (omit if circular)
ABS_MT_ORIENTATION = 0x34    # Ellipse orientation
ABS_MT_POSITION_X  = 0x35    # Center X touch position
ABS_MT_POSITION_Y  = 0x36    # Center Y touch position
ABS_MT_TOOL_TYPE   = 0x37    # Type of touching device
ABS_MT_BLOB_ID     = 0x38    # Group a set of packets as a blob
ABS_MT_TRACKING_ID = 0x39    # Unique ID of initiated contact
ABS_MT_PRESSURE    = 0x3a    # Pressure on contact area
ABS_MT_DISTANCE    = 0x3b    # Contact hover distance
ABS_MT_TOOL_X      = 0x3c    # Center X tool position
ABS_MT_TOOL_Y      = 0x3d    # Center Y tool position



class MouseDevice(SimpleDevice):
    """
    Report Multitouch events
    """
    def __init__(self, viewer, *args, **kwargs):
        SimpleDevice.__init__(self, *args, **kwargs)
        self.viewer = viewer
        self.num = 0
        self.slot = 0
        self.slots = {} # int -> int "slot" = touch number -> tracking ID
        self.tid = 0
        self.tids = {} # int -> (int, int, int): "tracking ID" = finger number -> X/Y/pressure 

    def receive(self, event):
    # In reality: slot only present, if more than one finger?
#   ABS_MT_SLOT 0
#   ABS_MT_TRACKING_ID 45
#   ABS_MT_POSITION_X x[0]
#   ABS_MT_POSITION_Y y[0]
#   ABS_MT_SLOT 1
#   ABS_MT_TRACKING_ID 46
#   ABS_MT_POSITION_X x[1]
#   ABS_MT_POSITION_Y y[1]
#   SYN_REPORT
        print("%s" % event)
        etype, ecode, evalue = event.etype, event.ecode, event.evalue
        if etype == EV_ABS:
            if ecode == ABS_MT_POSITION_X:
                self.tids[self.tid][0] = evalue
            elif ecode == ABS_MT_POSITION_Y:
                self.tids[self.tid][1] = evalue
            elif ecode == ABS_PRESSURE:
                if evalue == 0:  # 0 is just another way to say the finger is gone
                    return
                if self.tid in self.tids:
                    self.tids[self.tid][2] = evalue
                else:
                    print("tracking ID %d is already gone" % (self.tid,))
            elif ecode == ABS_MT_SLOT:
                self.slot = evalue
                if evalue in self.slots:
                    self.tid = self.slots[evalue]
            elif ecode == ABS_MT_TRACKING_ID:
                if evalue == -1: # finger gone
                    del self.tids[self.tid]
                    if self.slot in self.slots:
                        del self.slots[self.slot]
                else:
                    self.tid = evalue
                    self.slots[self.slot] = evalue
                    self.tids.setdefault(evalue, [0, 0, 0])
        elif etype == EV_SYN:
            if ecode == SYN_REPORT:
                for i, pos in self.tids.items():
                    viewer.update_finger(i, pos[0], pos[1], 0, 0, pos[2])
                    print("Finger %d at %s" % (i, pos))
                viewer.draw_fingers() # TODO: should be automatic after a few finger updates
#            elif ecode == SYN_MT_REPORT: # Only protocol A
#               viewer.got_finger(self.num, self.x, self.y, 0, 0, 10)
#               self.num += 1


#XRES = 1152
#YRES = 768

XRES = 6000
YRES = 5000
YOFF = 0


class FingerViewer(object):
    def __init__(self):
        self._running = True
        self.window = Gtk.Window()
        self.window.set_title("Fingers")
        self.width = 600
        self.height = 500
        self.window.width = self.width
        self.window.height = self.height
        self.fingers = []
        
        self.window.connect("destroy", self.destroy)

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width,self.height)
        self.context = cairo.Context(surface)
        self.image = Gtk.Image.new_from_surface(surface)
        self._draw_fingers()
        self.image.show()

        self.window.add(self.image)
        self.window.show()

    def update_finger(self,num,x,y,dx,dy,p):
        self.fingers.append((num,x,y,dx,dy,p))

    def draw_fingers(self):
        """
        Thread-safe version of draw_fingers()
        """
        GLib.idle_add(self._draw_fingers)

    def _draw_fingers(self):
        self.context.rectangle(0, 0, self.width, self.height) # fill with white
        self.context.set_source_rgb(1, 1, 1)
        self.context.fill()

        for num,x,y,dx,dy,p in self.fingers:
            self.draw_finger(num, x, y, dx, dy, p)

        self.image.queue_draw()
        self.fingers = []

    def draw_finger(self, num, x, y, dx, dy, p):
        # draw the finger
        tx, ty = self.to_screen_coord(x, y)
        self.context.arc(tx, ty, 10 + p / 3, 0, 2*math.pi)
        self.context.set_source_rgba(0,0,1)
        self.context.fill()

        # draw the velocity
        VRES = 500
        VSCALE = 100
        self.context.set_source_rgb(0,0,0)
        self.context.move_to(tx,ty)
        self.context.line_to(tx+(float(dx)/VRES)*VSCALE,ty-(float(-dy)/VRES)*VSCALE)
        self.context.stroke()
        
        # draw number label
        self.context.set_source_rgb(1, 1, 1)
        self.context.move_to(tx-5,ty+5)
        self.context.set_font_size(15)
        self.context.show_text(str(num + 1))
    
    def num_fingers(self, i):
        if i==0:
            self._wipe()

    def to_screen_coord(self, x, y):
        """
        translate to the graphical coordinates
        """
        return x / XRES * self.width, (y + YOFF) / YRES* self.height
    
    def destroy(self, _):
        self._running = False
        Gtk.main_quit()

    def readValues(self, args):
        import select
        controller = Controller("Controller")
        fds = {}
        poll = select.poll()
        dev = args
        print(dev)
        dev = MouseDevice(self, dev)
        fds[dev.fileno()] = dev
        poll.register(dev, select.POLLIN | select.POLLPRI)
        while self._running:
            for x,e in poll.poll():
                dev = fds[x]
                dev.read()

if __name__ == "__main__":
    viewer = FingerViewer()
    threading.Thread(target=viewer.readValues, args=sys.argv[1:]).start()
    Gtk.main()


# vim:shiftwidth=4:expandtab:spelllang=en_gb:spell:         
