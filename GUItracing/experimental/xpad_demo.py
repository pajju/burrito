import os, pyatspi, time, gobject, json

# get the Registry singleton
reg = pyatspi.Registry()

# get desktop
desktop = reg.getDesktop(0)

XPAD_DATA_DIR = os.path.join(os.getenv("HOME"), ".config/xpad/")


last_xpad_event_timestamp = 0
POLLING_INTERVAL_MS = 5000

# heuristic to detect if you're still typing when poll_for_xpad_change is
# called, in which case, DON'T do a save
CONTINUOUS_TYPING_MS = 500

def get_ms_since_epoch():
  milliseconds_since_epoch = int(time.time() * 1000)
  return milliseconds_since_epoch
 

def xpad_text_changed(event):
  if event.host_application.name != 'xpad': return # VERY IMPORTANT!
  global last_xpad_event_timestamp
  last_xpad_event_timestamp = get_ms_since_epoch()


def save_xpad_buffers(t):
  # the xpad data files are saved in $HOME/.config/xpad/content-*
  xpad_data_files = [e for e in os.listdir(XPAD_DATA_DIR) if e.startswith('content-')]

  result = {}
  result['timestamp'] = t
  for f in xpad_data_files:
    path = os.path.join(XPAD_DATA_DIR, f)
    result[f] = open(path).read()

  # use the most compact separators:
  compactJSON = json.dumps(result, separators=(',',':'))

  outf = open('/var/log/burrito/current-session/xpad-notes.log', 'a') # append!
  print >> outf, compactJSON
  outf.close()


def poll_for_xpad_change():
  global last_xpad_event_timestamp
  t = get_ms_since_epoch()

  delta = (t - last_xpad_event_timestamp)

  # if the user still appears to be typing, then don't save!
  if CONTINUOUS_TYPING_MS < delta < POLLING_INTERVAL_MS:
    save_xpad_buffers(t)

  return True # so that gobject.timeout_add will keep firing!


reg.registerEventListener(xpad_text_changed, 'object:text-changed')

def asyncHandler():
  pyatspi.Registry.pumpQueuedEvents()
  return True # so that gobject.timeout_add will keep firing!

gobject.timeout_add(200, asyncHandler)
gobject.timeout_add(POLLING_INTERVAL_MS, poll_for_xpad_change)

save_xpad_buffers(get_ms_since_epoch()) # do a save of the initial start-up state

try:
 # asynchronous is mandatory if you want poll_for_xpad_change to work!
 pyatspi.Registry.start(async=True, gil=False)
except KeyboardInterrupt:
 pass
finally:
  pyatspi.Registry.stop()

