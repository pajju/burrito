# GUI tracer that works with the Linux AT-SPI Accessibility API
#
# Tested on Fedora 14 running the GNOME GUI environment
#
# Pre-req: Before this script will work, you need to first go to
#          this menu: System -> Preferences -> Assistive Technologies
#          check the "Enable assistive technologies" box,
#          then log out and log back in.

# TODO: Factor out Chrome tracing code into its own module to better
# separate out the "platform" from the "apps"

import sys
from BurritoUtils import *
import XpadTracer
import ClipboardLogger


# Output to a series of log files with the prefix of:
# /var/log/BurritoBook/current-session/gui.trace and the
# suffix of .0, .1, etc., switching over to a new file whenever
# MAX_LINES_IN_LOGFILE has been reached
MAX_LINES_IN_LOGFILE = 10000 # 10000 * ~1K per entry = ~10MB per log file
OUTFILE_BASE = '/var/log/BurritoBook/current-session/gui.trace'
num_lines_in_cur_file = 0
cur_file_index = 0
cur_fd = open(OUTFILE_BASE + '.' + str(cur_file_index), 'w')


import pyatspi
import gobject # requires pygtk, i think


# Let's not support Firefox for now since it seems to have some quirks.
#
# e.g., when a window is minimized, its state set usually contains:
#      pyatspi.constants.STATE_ICONIFIED
# except that it doesn't work for Firefox for some reason!!!

# SUPER hacky way of getting the current URL text string from
# Google Chrome and Firefox ... there MUST be a better way :)
#
# Use printDesktopTree.py to find out the exact path to the URL boxes
#
# use the accessibility API to find the exact location of the URL bar.
# Note that this will BREAK if the user's Chrome/Firefox GUI even
# looks slightly different than my own GUI:
def getChromeUrlField(frameElt):
  return frameElt[0][0][2][0][0][1][0][1][1][0][0]

def getFirefoxUrlField(frameElt):
  return frameElt[10][6][1]


# Note: pyatspi has some potentially useful utility functions:
#   http://people.gnome.org/~parente/pyatspi/doc/pyatspi.utils-module.html


# TODO: can I get PIDs of controlling processes of each window?
# (the 'application names' collected by pyatspi sometimes don't exactly
# match the names collected by SystemTap)
# - ugh, sadly I don't think so :(


# What happens when the user has multiple virtual desktops?
#   ahhh, very interesting ... when you move an app to another virtual
#   desktop, it shows up as STATE_ICONIFIED, so it's like it was MINIMIZED


# Class hierarchy: A Desktop contains 0 or more Application instances,
# and each Application contains 1 or more Window instances.
# (ignore applications with no windows)

class Desktop:
  def __init__(self, atspiDesktop):
    # Key:   app ID (INTEGER!  hopefully unique ... try to open multiple
    #                'evince' windows to see how app names are NOT unique,
    #                but IDs are)
    # Value: Application instance
    self.appsDict = {}

    self.atspiDesktop = atspiDesktop
    self.__updateAppsDict()


  # update self.appsDict by scanning through self.atspiDesktop again so
  # that we can check for apps that have been newly-created or deleted
  #
  # return True if the number of apps has changed
  def __updateAppsDict(self):
    newAppsDict = {}

    for app in self.atspiDesktop:
      if not app: continue # some app entries are None; weird

      intID = int(app.id) # ugh, gross casts!

      if intID in self.appsDict:
        # do a straight-up copy for efficiency
        newAppsDict[intID] = self.appsDict[intID]
      else:
        # create a new one, which might incur a *slight* delay
        newApp = Application(app)
        # only add to self.apps if there are SOME windows
        if len(newApp.windows):
          newAppsDict[intID] = newApp

    appNumChanged = (len(self.appsDict) != len(newAppsDict))

    self.appsDict = newAppsDict # VERY important!
    return appNumChanged


  # do an incremental update for efficiency
  def updateApp(self, atspiApp):
    self.__updateAppsDict() # check for added/deleted apps

    try:
      # make sure to cast ID as an int!!!
      self.appsDict[int(atspiApp.id)].updateAllFrames()
    except LookupError:
      # the atspiApp object might now be screwy
      pass


  def printMe(self):
    print '=== DESKTOP ==='
    for appID in sorted(self.appsDict.keys()):
      self.appsDict[appID].printMe()

  
  # serialize the current state to a big dict, which can later be
  # converted to JSON
  def serialize(self):
    out = {}
    for appID in self.appsDict:
      out[appID] = self.appsDict[appID].serialize()

    return out


class Application:
  def __init__(self, app):
    self.name = app.name
    self.atspiApp = app

    # Key: unique index of Window object (as given by int(getIndexInParent()))
    # Value: Window object
    self.windows = {}
    self.updateAllFrames()

  # do the super-simple thing and just create NEW Window objects for all
  # frames in this app ...
  def updateAllFrames(self):
    self.windows = {} # clear first!

    for child in self.atspiApp:
      # sometimes apps will have null or non-frame children, so skip those!
      if not child: continue
      if child.getRole() != pyatspi.constants.ROLE_FRAME: continue

      # create a new Window object, which might incur a *slight* delay
      self.windows[int(child.getIndexInParent())] = Window(child, self)


  # return True if the number of frames or cur_atspiFrame have changed
  def updateFrame(self, cur_atspiFrame):
    # update self.windows to account for the fact that frames might
    # have been added or deleted to this app since the last update
    newWindows = {}
    vals = self.windows.values()
    for child in self.atspiApp:
      # recycle existing Window instances if found (for efficiency)
      childFound = False
      for w in vals:
        if child == w.atspiFrame:
          newWindows[int(child.getIndexInParent())] = w
          childFound = True
          break

      # new frame!
      if not childFound:
        if child.getRole() != pyatspi.constants.ROLE_FRAME: continue
        # create a new Window object, which might incur a *slight* delay
        newWindows[int(child.getIndexInParent())] = Window(child, self)

    frameNumChanged = (len(self.windows) != len(newWindows))
    self.windows = newWindows

    for w in self.windows.values():
      if cur_atspiFrame == w.atspiFrame:
        curFrameChanged = w.update()
        return frameNumChanged or curFrameChanged

    # bug triggered when you open Firefox
    assert False # should never reach here


  def printMe(self):
    print 'APP:', self.name
    for w in self.windows.values():
      w.printMe()

  def serialize(self):
    return dict(name=self.name, windows=dict([(k,w.serialize()) for (k,w) in self.windows.iteritems()]))


# pyatspi uses the term 'frame' to refer to what we think of as windows
class Window:
  def __init__(self, frame, parentApp):
    self.parent = parentApp
    self.atspiFrame = frame

    self.title = frame.name

    comp = frame.queryComponent()
    self.x, self.y = comp.getPosition(0)
    self.width, self.height = comp.getSize()

    myStates = frame.getState().getStates()
    self.is_active = pyatspi.constants.STATE_ACTIVE in myStates
    self.is_minimized = pyatspi.constants.STATE_ICONIFIED in myStates

    # special field for Firefox and Google Chrome
    self.browserURL = self.getURL()

    assert not (self.is_active and self.is_minimized)


  # returns a URL string if applicable, or 'None' if the Window isn't a
  # Firefox or Chrome web browser window
  def getURL(self):
    urlField = None
    if self.parent.name == 'google-chrome':
      urlField = getChromeUrlField(self.atspiFrame)
    elif self.parent.name == 'Firefox':
      urlField = getFirefoxUrlField(self.atspiFrame)

    if urlField:
      urlTextField = urlField.queryEditableText()

      # for some weird reason, google-chrome puts an extra 'junk'
      # two bytes at the end of urlString, so adjust accordingly
      nChars = urlTextField.characterCount
      if self.parent.name == 'google-chrome':
        assert nChars > 0
        nChars -= 2
      return urlTextField.getText(0, nChars)

    return None


  # update fields by re-querying self.atspiFrame
  # and return 'True' if any field has been modified
  def update(self):
    modified = False

    new_title = self.atspiFrame.name
    comp = self.atspiFrame.queryComponent()
    new_x, new_y = comp.getPosition(0)
    new_width, new_height = comp.getSize()
    new_states = self.atspiFrame.getState().getStates()
    new_is_active = pyatspi.constants.STATE_ACTIVE in new_states
    new_is_minimized = pyatspi.constants.STATE_ICONIFIED in new_states
    new_browserURL = self.getURL()

    if self.title != new_title:
      self.title = new_title
      modified = True

    if self.x != new_x:
      self.x = new_x
      modified = True

    if self.y != new_y:
      self.y = new_y
      modified = True

    if self.width != new_width:
      self.width = new_width
      modified = True

    if self.height != new_height:
      self.height = new_height
      modified = True

    if self.is_active != new_is_active:
      self.is_active = new_is_active
      modified = True

    if self.is_minimized != new_is_minimized:
      self.is_minimized = new_is_minimized
      modified = True

    if self.browserURL != new_browserURL:
      self.browserURL = new_browserURL
      modified = True

    assert not (self.is_active and self.is_minimized)
    return modified


  def printMe(self):
    if self.is_active:
      print '*',
    elif self.is_minimized:
      print 'm',
    else:
      print ' ',

    print self.title

    print '    x:%d,y:%d (%dx%d)' % (self.x, self.y, self.width, self.height)
    if self.browserURL:
      print '   ', self.browserURL


  def serialize(self):
    out = {}

    out['title'] = self.title
    out['x'] = self.x
    out['y'] = self.y
    out['width'] = self.width
    out['height'] = self.height
    out['is_active'] = self.is_active
    out['is_minimized'] = self.is_minimized
    if self.browserURL is not None:
      out['browserURL'] = self.browserURL

    return out


reg = pyatspi.Registry()    # get the Registry singleton
atspiDesktop = reg.getDesktop(0) # get desktop

# The plan here is to initialize a singleton myDesktop instance at the
# beginning of execution and to selectively update myDesktop as events
# occur while making AS FEW QUERIES to the at-spi API as possible, since
# these queries can be SLOW!

myDesktop = Desktop(atspiDesktop) # singleton

'''
Notes about window events:

- When you drag to move a window, it first generates 'window:deactivate'
  when you start dragging, and then 'window:activate' when you release the
  mouse and finish dragging

- When you finish resizing a window, a 'window:activate' event fires
  (doesn't seem to happen for Google Chrome, though)

- 'window:minimize', 'window:maximize', and 'window:restore' are for
  minimizing, restoring, and maximizing windows, respectively

- 'window:create' is when a new window pops up.  Perhaps this is a good
  time to update the list of running applications?

- when a window is closed, it seems like only a 'window:deactivate'
  event fires (there's no window close event???)


Notes about object events:

- 'object:state-changed:active' fires on a 'frame' object whenever it
  comes into focus (with event.detail1 == 1)

- 'object:state-changed:iconified' fires whenever it gets "minimized",
  it seems

- 'object:bounds-changed' fires on a 'frame' object whenever it's
  resized

- 'object:property-change:accessible-name' fires on a 'frame' object
  whenever its title changes ... good for detecting webpage and terminal
  title changes


'focus' events are kinda flaky, but they seem to be triggered when the
mouse clicks on a particular GUI element like a panel or something.


Adapted from:
   http://developers-blog.org/blog/default/2010/08/21/Track-window-and-widget-events-with-AT-SPI
'''


def printDesktopState(event=None):
  # nasty globals!
  global cur_fd, num_lines_in_cur_file, cur_file_index

 
  desktop_state = myDesktop.serialize()
  timestamp     = get_ms_since_epoch()

  serializedState = dict(desktop_state=desktop_state, timestamp=timestamp)

  # for some sorts of events, we should include the event info:
  if event and event.type == 'window:create':
    assert event.source.getRole() == pyatspi.constants.ROLE_FRAME
    wIdx = int(event.source.getIndexInParent()) # make sure to cast as int!

    # can be negative on error, so punt on those ...
    if wIdx >= 0:
      serializedState['event_type'] = 'window:create'
      serializedState['src_app_id'] = int(event.host_application.id)
      serializedState['src_frame_index'] = wIdx

      # sanity checks!!!
      assert serializedState['src_app_id'] in desktop_state
      assert serializedState['src_frame_index'] in desktop_state[serializedState['src_app_id']]['windows']


  compactJSON = to_compact_json(serializedState)

  # for debugging ...
  '''
  if event and event.type == 'window:create':
    for i in range(100): print
    import pprint
    pp = pprint.PrettyPrinter(indent=2)
    pp.pprint(serializedState)
  '''


  print >> cur_fd, compactJSON

  cur_fd.flush() # force a flush to disk

  # roll over to a new file if necessary
  num_lines_in_cur_file += 1
  if num_lines_in_cur_file >= MAX_LINES_IN_LOGFILE:
    cur_fd.close()

    cur_file_index += 1
    num_lines_in_cur_file = 0
    cur_fd = open(OUTFILE_BASE + '.' + str(cur_file_index), 'w')



def frameEventHandler(event):
  try:
    if event.source.getRole() != pyatspi.constants.ROLE_FRAME:
      return
  except LookupError:
    # silently fail on weird at-spi lookup errors o.O
    return

  myDesktop.updateApp(event.host_application)

  #print event # debugging
  printDesktopState(event)


# the minimal set of required listeners to get what we want ...
#
# Known shortcomings:
# - won't fire an update event when a Chrome window is moved :(
#
# - for SOME apps, won't fire an update event when you CLOSE a window
# without first putting it in focus (since the focus never changed from
# the foreground window, and stateChangedHandler doesn't work either)


# we want to detect BOTH when a frame becomes active and also inactive
reg.registerEventListener(frameEventHandler, 'object:state-changed:active')

# frame title changes
reg.registerEventListener(frameEventHandler, 'object:property-change:accessible-name')

# If you detect (event.detail1 == 0) for a 'frame', then that means the
# frame has gone invisible.  This detects SOME cases of when you close a
# window without first putting it in focus (but doesn't work on all apps)
def stateChangedHandler(event):
  # only handle for when object:state-changed:visible is 0 ...
  if event.detail1 == 0:
    frameEventHandler(event)

reg.registerEventListener(stateChangedHandler, 'object:state-changed:visible')


reg.registerEventListener(frameEventHandler, 'window:create')
reg.registerEventListener(frameEventHandler, 'window:minimize')
reg.registerEventListener(frameEventHandler, 'window:maximize')
reg.registerEventListener(frameEventHandler, 'window:restore')



printDesktopState()   # print the initial desktop state


# initialize 'plug-ins'
XpadTracer.initialize(reg)
ClipboardLogger.initialize(reg)


def goodbye():
  print >> sys.stderr, "GOODBYE from GUItracer.py"
  global cur_fd
  pyatspi.Registry.stop()
  cur_fd.close()
  
  # Tear down 'plug-ins'
  XpadTracer.teardown()
  ClipboardLogger.teardown()


# We need to make sure signal handlers get set BEFORE the weird pyatspi
# and gobject event-related calls ...
from signal import signal, SIGINT, SIGTERM
import atexit

atexit.register(goodbye)
signal(SIGTERM, lambda signum,frame: exit(1)) # trigger the atexit function to run


# This idiom of gobject.timeout_add, pumpQueuedEvents, and async=True
# was taken from the Accerciser project

def asyncHandler():
  pyatspi.Registry.pumpQueuedEvents()
  return True # so that gobject.timeout_add will keep firing!

gobject.timeout_add(200, asyncHandler)


# being asynchronous is MANDATORY if you want object.timeout_add events to work!
try:
  pyatspi.Registry.start(async=True, gil=False)
except KeyboardInterrupt:
  pass

