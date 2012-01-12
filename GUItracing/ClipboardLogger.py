# Logs clipboard copy-and-paste activity in JSON format
#
# Timestamps and click coordinates can be synchronized with the
# GUItracer.py log to get the source and destination windows for the
# copy and paste, respectively.


'''
Limitations: Can only detect paste events of the 'primary' clipboard,
which are triggered with a mouse middle-click.

This script CANNOT detect paste events of the Gtk clipboard, which can
either be triggered by Ctrl-V or by selecting from a menu item.

Known bug: If you copy and then middle-click paste on another
gnome-terminal without first clicking on it, then the mouse click event
triggers BEFORE the window switch event, so the system will think that
you pasted in your OLD window ... wow this doesn't happen ALL the time
... sometimes it happens, though.  i guess it depends on the order of
at-spi receiving "mouse button released" and active window focus change
events.

  - Note: I've seen this happen with Google Chrome as well!

  - One possible workaround (which I haven't implemented yet) is to
  detect such cases (by seeing whether the click was OUT OF BOUNDS of
  the supposedly active window in the matched paste destination
  DesktopState), and then finding the NEXT DesktopState entry in the
  list, which should be the one right AFTER the window switch.

'''

import time
import pyatspi
import gtk, gobject
from BurritoUtils import *


def middleMouseEventHandler(event):
  global theClipboard

  # if there's an empty clipboard, don't bother doing anything!!!
  if not theClipboard.primary_clipboard_text: return

  xCoord = int(event.detail1)
  yCoord = int(event.detail2)
  paste_time_ms = get_ms_since_epoch()

  # log the paste event now ...
  serializedState = dict(x=xCoord, y=yCoord,
                         copy_time_ms=theClipboard.copy_time_ms,
                         timestamp=paste_time_ms,
                         event_type='paste',
                         contents=theClipboard.primary_clipboard_text)

  compactJSON = to_compact_json(serializedState)
  print >> outf, compactJSON
  outf.flush() # don't forget!


# Clipboard code adapted from:
#   Glipper - Clipboardmanager for GNOME
#   Copyright (C) 2007 Glipper Team
class Clipboard(gobject.GObject):
   def __init__(self):
      gobject.GObject.__init__(self)

      # primary X clipboard ... highlight to copy, middle-mouse-click to paste
      self.primary_clipboard = gtk.clipboard_get("PRIMARY")

      self.primary_clipboard_text = None
      self.copy_time_ms = None

      # 'owner-change' event is triggered when there's a new clipboard entry
      self.primary_clipboard.connect('owner-change', self.on_primary_clipboard_owner_change)


      # We don't support the Gtk clipboard for now since we can't detect
      # paste events.
      # Ctrl-C copy, Ctrl-V paste
      #self.default_clipboard = gtk.clipboard_get()
      #self.default_clipboard_text = self.default_clipboard.wait_for_text()
      #self.default_clipboard.connect('owner-change', self.on_default_clipboard_owner_change)
 
  
   def on_primary_clipboard_owner_change(self, clipboard, event):
      assert clipboard == self.primary_clipboard
      self.copy_time_ms = get_ms_since_epoch()
      self.primary_clipboard_text = self.primary_clipboard.wait_for_text()

      # log the copy event right away, but just record the timestamp and
      # not the contents ...
      global outf
      serializedState = dict(timestamp=self.copy_time_ms, event_type='copy')
      compactJSON = to_compact_json(serializedState)
      print >> outf, compactJSON
      outf.flush() # don't forget!

     
   #def on_default_clipboard_owner_change(self, clipboard, event):
   #   assert clipboard == self.default_clipboard
   #   self.default_clipboard_text = self.default_clipboard.wait_for_text()
   #   print 'DEFAULT:', self.default_clipboard_text

 
# global singleton
theClipboard = Clipboard()
outf = None

def initialize(reg):
  global outf
  outf = open('/var/log/BurritoBook/current-session/clipboard.log', 'w')

  # register the middle mouse button click
  # VERY IMPORTANT: register the RELEASE event ('2r') of the middle mouse
  # button, since that's the only way to get the PROPER x and y
  # coordinates; otherwise if you register the PRESS event ('2p'), then
  # the coordinates will be INCORRECT ... AHHHHH!
  reg.registerEventListener(middleMouseEventHandler, 'mouse:button:2r')


def teardown():
  global outf
  outf.close()

