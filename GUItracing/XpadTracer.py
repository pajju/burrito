# 'xpad' tracing module for GUItracer.py
# 2011-11-20

import os, gobject
from BurritoUtils import *


XPAD_DATA_DIR = os.path.join(os.getenv("HOME"), ".config/xpad/")

last_xpad_event_timestamp = 0
POLLING_INTERVAL_MS = 15000

outf = None


def xpad_text_changed(event):
  if not event: return
  if not event.host_application: return
  if event.host_application.name != 'xpad': return # VERY IMPORTANT!
  global last_xpad_event_timestamp
  last_xpad_event_timestamp = get_ms_since_epoch()


def save_xpad_buffers(t):
  # the xpad raw data files are saved in $HOME/.config/xpad/content-*
  xpad_data_files = [e for e in os.listdir(XPAD_DATA_DIR) if e.startswith('content-')]

  result = {}
  result['timestamp'] = t
  for f in xpad_data_files:
    path = os.path.join(XPAD_DATA_DIR, f)
    result[f] = open(path).read()

  compactJSON = to_compact_json(result)

  #print "SAVE", t
  global outf
  print >> outf, compactJSON
  outf.flush() # don't forget!


def poll_for_xpad_change():
  global last_xpad_event_timestamp
  t = get_ms_since_epoch()

  delta = (t - last_xpad_event_timestamp)

  #print "POLL", t
  if delta < POLLING_INTERVAL_MS:
    save_xpad_buffers(last_xpad_event_timestamp) # save the last typed timestamp!

  return True # so that gobject.timeout_add will keep firing!


def initialize(reg):
  global outf
  outf = open('/var/log/burrito/current-session/xpad-notes.log', 'w')

  save_xpad_buffers(get_ms_since_epoch()) # do a save of the initial start-up state
  reg.registerEventListener(xpad_text_changed, 'object:text-changed')
  gobject.timeout_add(POLLING_INTERVAL_MS, poll_for_xpad_change)

def teardown():
  poll_for_xpad_change() # do one final check

  global outf
  outf.close()

