# Parse the GUI trace log file produced by GUItracer.py

# Pass in the DIRECTORY containing gui.trace.* as sys.argv[1]

import os, json, sys, datetime

# If you want to vary the amount of filtering, you can set the various
# threshold constants later in this file ...

# Optimization passes:
def optimize_gui_trace(input_lst):
  # NOP for an empty list ...
  if not input_lst: return input_lst

  # file format sanity checks:
  assert type(input_lst[0][0]) in (int, long)
  assert input_lst[0][1].__class__ is DesktopState

  l2 = coalesceAndDedup(input_lst)
  l3 = removeInactiveStates(l2)

  return l3

  # TODO: investigate this below ...

  # do another round just for good times (since removeInactiveStates
  # might introduce some new duplicates)
  #l4 = coalesceAndDedup(l3)
  # TODO: I don't know whether this is sufficient, or whether we have to
  # keep running until fixpoint


# A DesktopState is only supposed to have at most ONE active window,
# but sometimes there is some "stickiness" in GUI events, so that there
# will be a DesktopState with TWO active windows.  What happens is that
# a new window will become active, but the old one won't have
# deactivated yet.  So let's correct this dirtiness ...
#
# For every pair of neighboring states (prev, cur), if 'cur' has more
# than one active window, then DEACTIVATE the window in 'cur' that
# matches the sole active window in 'prev'.
#
# Run this pass BEFORE coalesceAndDedup(), since this optimization pass
# might create some duplicates that can be eliminated in coalesceAndDedup()
#
# SUPER GROSS HACK: also pass in prev_final_entry to account for the
# case when the FIRST element of lst has more than one active window,
# in which case we have to consult prev_final_entry for the proper
# window to deactivate in the first element of lst.
def enforceSoloActiveWindow(lst, prev_final_entry):
  ret = []
  cInd = 0

  orig_len = len(lst)

  # ugh this is so ugly ...
  augmented_lst = [prev_final_entry] + lst

  # start counting at 1 since we want to SKIP prev_final_entry
  for cInd in xrange(1, len(augmented_lst)):
    prev = augmented_lst[cInd - 1]
    cur  = augmented_lst[cInd]

    if not prev: # what if we have no prev_final_entry?
      assert cur[1].num_active_windows() <= 1
      ret.append(cur)
    else:
      pState = prev[1]
      cState = cur[1]

      n = cState.num_active_windows()
      assert n <= 2 # there should never be more than 2 active windows!!!

      if n > 1:
        assert n == 2

        pActiveWindowsLst = pState.get_active_windows()

        assert len(pActiveWindowsLst) <= 1
        if len(pActiveWindowsLst) == 1:
          pActiveWindow = pActiveWindowsLst[0]

          # modify cState to DEACTIVATE the window that matches pActiveWindow
          for (appId, a) in cState.appsDict.iteritems():
            for (windowIndex, w) in a.windows.iteritems():
              if w.is_active:
                if (appId, windowIndex) == pActiveWindow:
                  w.is_active = False # MUTATE IT!
        else:
          # pState has no active windows, so punt to the desperation case ...
          pass

        # in the RARE case that we still haven't eliminated multiple
        # windows, then simply issue a warning and just disable one window
        # chosen at 'random' ... this is non-ideal but hopefully should
        # be rare ...
        if cur[1].num_active_windows() > 1:
          activeWindows = cState.get_active_windows()
          assert len(activeWindows) == 2
          (random_a, random_w) = activeWindows[0]
          cState[random_a][random_w].is_active = False
          print >> sys.stderr, "WARNING in enforceSoloActiveWindow: Disabled arbitrary window in DesktopState at timestamp", cur[0]


      ret.append(cur)


  # end-to-end sanity checks ...
  assert len(ret) == orig_len
  for e in ret:
    assert e[1].num_active_windows() <= 1

  return ret


# If two neighboring entries are duplicates of one another, then only
# keep the EARLIER one (since that's when the GUI was FIRST in that state)
#
# Also coalesce entries that occur within 'threshold' milliseconds of one
# another and keep on the LAST one in a streak, to make the output stream
# a bit cleaner.
#
# Oftentimes the GUI generates several events in quick succession,
# and it's only useful to keep the LAST one in a streak.
COALESCE_WINDOW_MS = 500 # half a second seems to work pretty darn well

def coalesceAndDedup(lst):
  ret = []
  pInd = 0
  cInd = 1

  # Make sure that pinned states remain in the final list:
  pinned_elts = [e for e in lst if e[1].pinned]

  # Do the normal coalesce/dedup:
  while cInd < len(lst):
    prev = lst[pInd]
    cur  = lst[cInd]
    deltaTime = cur[0] - prev[0]

    # Dedup: remember, the cadr of the tuple is the payload ...
    if prev[1] == cur[1]:
      # advance cInd to "skip" this entry;
      # we want to keep pInd in the same place to keep the EARLIER one
      cInd += 1
    elif deltaTime >= COALESCE_WINDOW_MS:
      ret.append(prev)
      pInd = cInd
      cInd = pInd + 1
    else:
      pInd += 1
      cInd += 1

  if lst:
    ret.append(lst[-1]) # always append the final entry

  # Put pinned states back in ret
  for p in pinned_elts:
    if p not in ret:
      ret.append(p)

  # sort chronologically again!
  ret.sort(key=lambda e:e[0])

  return ret


# Delete all DesktopState instances without an active window if they're
# followed < N seconds later by a state WITH an active window.
#
# The justification here is that when windows are being moved or
# resized, there is temporarily NO active window for a few seconds,
# and when the move/resize is completed, there's an active window again.
#
# Our current 4-second heuristic seems to work well in practice.
INACTIVE_DEDUP_THRESHOLD_MS = 4000

def removeInactiveStates(lst):
  ret = []
  cInd = 0
  nInd = 1

  while cInd < len(lst):
    cur  = lst[cInd]

    # Remember, the cadr of the tuple is the payload ...
    # make sure not to skip pinned entries!
    if cur[1].num_active_windows() == 0 and (not cur[1].pinned):
      next = None

      # edge case!
      if nInd < len(lst):
        next = lst[nInd]
        deltaTime = next[0] - cur[0]

      if not next or deltaTime > INACTIVE_DEDUP_THRESHOLD_MS:
        ret.append(cur)

      # otherwise SKIP cur
    else:
      ret.append(cur)

    cInd += 1
    nInd += 1

  return ret


# represents the current state of the user's desktop
class DesktopState:
  def __init__(self, dat):
    assert type(dat) is dict
    # Key:   app ID
    # Value: ApplicationState
    self.appsDict = {}
    for (k, v) in dat.iteritems():
      # convert key into an INTEGER since JSON only supports keys of
      # type 'string', but they're conceptually INTEGERS!
      self.appsDict[int(k)] = ApplicationState(v)

    # if this is True, then do NOT optimize this state away,
    # since we probably need to keep it around for cross-reference
    self.pinned = False

  def __eq__(self, other):
    return self.pinned == other.pinned and self.appsDict == other.appsDict

  # serialize for MongoDB; note that we need to add an _id field later
  def serialize(self):
    ret = {}
    ret['apps'] = []

    for (k,v) in self.appsDict.iteritems():
      ret['apps'].append(dict(app_id=k, app=v.serialize()))

    active_windows = self.get_active_windows()
    assert len(active_windows) <= 1
    if len(active_windows) == 1:
      app_id, window_idx = active_windows[0]
      ret['active_app_id'] = app_id
      ret['active_window_index'] = window_idx
    else:
      ret['active_app_id'] = -1
      ret['active_window_index'] = -1

    return ret

  @staticmethod
  def from_mongodb(mongodb_dat):
    ret = DesktopState({}) # start with an empty desktop
    for e in mongodb_dat['apps']:
      ret.appsDict[int(e['app_id'])] = ApplicationState.from_mongodb(e['app'])
    return ret

  def __getitem__(self, i):
    return self.appsDict[i]

  def printMe(self, indent=0):
    if self.pinned:
      print "PINNED!!!"
    for appId in sorted(self.appsDict.keys()):
      self.appsDict[appId].printMe(indent)

  # should normally be 1 ... anything other than 1 is WEIRD!
  def num_active_windows(self):
    n = 0
    for a in self.appsDict.itervalues():
      for w in a.windows.itervalues():
        if w.is_active:
          n += 1
    return n

  # returns a list of pairs (app ID, window index)
  def get_active_windows(self):
    ret = []
    for (appId, a) in self.appsDict.iteritems():
      for (windowIndex, w) in a.windows.iteritems():
        if w.is_active:
          ret.append((appId, windowIndex))

    return ret


  # returns the actual WindowState instance (or None)
  def get_first_active_window(self):
    for (appId, a) in self.appsDict.iteritems():
      for (windowIndex, w) in a.windows.iteritems():
        if w.is_active:
          return w
    return None



class ApplicationState:
  def __init__(self, dat):
    self.name = dat['name']
    w = dat['windows']
    assert type(w) is dict
    self.windows = {}
    for (k,v) in w.iteritems():
      # convert key into an INTEGER since JSON only supports keys of
      # type 'string', but they're conceptually INTEGERS!
      self.windows[int(k)] = WindowState(v)

    # Update with a PID by matching up with the SystemTap logs.
    #
    # For simplicity ...
    # we're assuming here that an 'application' only has one PID;
    # for apps that spawn off multiple processes, try to grab the master
    # controlling process (we can always grab its children later using
    # the process tree)
    self.pid = None


  def __eq__(self, other):
    return (self.name == other.name and \
            self.pid == other.pid and \
            self.windows == other.windows)

  def __str__(self):
    return '%s [PID: %s]' % (self.name, str(self.pid))

  # serialize for MongoDB
  def serialize(self):
    ret = {}
    ret['name'] = self.name
    ret['pid'] = self.pid
    ret['windows'] = []
    for (k,v) in self.windows.iteritems():
      ret['windows'].append(dict(window_index=k, window=v.serialize()))

    return ret

  @staticmethod
  def from_mongodb(mongodb_dat):
    dat = {}
    dat['name'] = mongodb_dat['name']
    dat['windows'] = {}
    for e in mongodb_dat['windows']:
      dat['windows'][e['window_index']] = e['window']

    ret = ApplicationState(dat)  # use the regular ApplicationState constructor
    ret.pid = mongodb_dat['pid'] # don't forget to tack this on!
    return ret

  def __getitem__(self, i):
    return self.windows[i]


  def printMe(self, indent=0):
    print (' ' * indent), self

    for k in sorted(self.windows.keys()):
      self.windows[k].printMe(indent)


class WindowState:
  def __init__(self, dat):
    self.__dict__.update(dat) # 1337 trick!

  def __eq__(self, other):
    return self.__dict__ == other.__dict__

  # serialize for MongoDB
  def serialize(self):
    return self.__dict__

  def printMe(self, indent=0):
    print ' ' * indent,
    if self.is_active:
      print '*',
    elif self.is_minimized:
      print 'm',
    else:
      print ' ',

    print self.title, '| (%d,%d) [%dx%d]' % (self.x, self.y, self.width, self.height)
    if hasattr(self, 'browserURL'):
      print (' ' * indent), '   URL:', self.browserURL


# Generate entries one at a time from the file named 'fn'
def gen_gui_entries_from_file(fn):
  print >> sys.stderr, "gen_gui_entries_from_file('%s')" % (fn,)
  for line in open(fn):
    data = json.loads(line) # each line must be valid JSON!
    yield data


def gen_gui_entries_from_dir(dn):
  log_files = [e for e in os.listdir(dn) if e.startswith('gui.trace')]

  # go through log_files in CHRONOLOGIAL order, which isn't the same as
  # an alphabetical sort by name.  e.g., we want "gui.trace.out.2" to
  # come BEFORE "gui.trace.out.10", but if we alphabetically sort, then
  # "gui.trace.out.10" will come first!
  for i in range(len(log_files)):
    cur_fn = 'gui.trace.' + str(i)
    assert cur_fn in log_files, cur_fn
    fullpath = os.path.join(dn, cur_fn)

    for entry in gen_gui_entries_from_file(fullpath):
      yield entry


# lst should be a list of (timestamp, DesktopState) pairs:
def interactive_print(lst):
  idx = 0
  while True:
    (t, s) = lst[idx]

    for i in range(100): print
    print "%d / %d" % (idx + 1, len(lst)), datetime.datetime.fromtimestamp(float(t) / 1000), t
    print
    s.printMe()
    print
    print "Next state: <Enter>"
    print "Prev state: 'p'+<Enter>"
    print "Next PINNED state: 'a'+<Enter>"
    print "Jump: <state number>'+<Enter>"

    k = raw_input()
    if k == 'p':
      if idx > 0:
        idx -= 1
    elif k == 'a':
      idx += 1
      while True:
        (t, s) = lst[idx]
        if not s.pinned:
          idx += 1
        else:
          break
    else:
      try:
        jmpIdx = int(k)
        if 0 <= jmpIdx < len(lst):
          idx = (jmpIdx - 1)
      except ValueError:
        if idx < len(lst) - 1:
          idx += 1


def print_window_diff(old, new, app_name, print_inactive=False):
  diffstrs = []
  if old.is_active != new.is_active:
    if new.is_active:
      diffstrs.append('went active')

    # don't print when a window goes INACTIVE unless there are NO active
    # windows anywhere throughout the entire DesktopState
    # (otherwise it's redundant since SOME other window is going active)
    elif old.is_active and print_inactive:
      diffstrs.append('went inactive')

  if old.is_minimized != new.is_minimized:
    if new.is_minimized:
      diffstrs.append('minimized')
    else:
      diffstrs.append('un-minimized')

  if old.title != new.title:
    diffstrs.append('title changed from "%s"' % (old.title,))

  if (old.x, old.y) != (new.x, new.y):
    diffstrs.append('moved (%d,%d) -> (%d,%d)' % (old.x, old.y, new.x, new.y))

  if (old.width, old.height) != (new.width, new.height):
    diffstrs.append('resized [%dx%d] -> [%dx%d]' % (old.width, old.height, new.width, new.height))

  # awkward!
  if hasattr(old, 'browserURL') and hasattr(new, 'browserURL'):
    if old.browserURL != new.browserURL:
      diffstrs.append('URL changed to "%s"' % (new.browserURL,))

  if diffstrs:
    print app_name, ': "%s"' % (new.title,),
    print ', '.join(diffstrs)


def print_app_diff(old, new, print_inactive_window=False):
  old_windowIdxs = set(old.windows.keys())
  new_windowIdxs = set(new.windows.keys())

  added_windowIdxs = new_windowIdxs - old_windowIdxs
  if added_windowIdxs:
    for w in new_windowIdxs:
      print new.name, "created window:",
      new.windows[w].printMe()

  deleted_windowIdxs = old_windowIdxs - new_windowIdxs
  if deleted_windowIdxs:
    for w in deleted_windowIdxs:
      print old.name, "deleted window:",
      old.windows[w].printMe()
 
  # now diff the windows in common:
  for w in old_windowIdxs.intersection(new_windowIdxs):
    print_window_diff(old.windows[w], new.windows[w], new.name, print_inactive_window)


# Pretty-print a diff of two DesktopState instances
def print_desktop_diff(old, new):
  old_appIDs = set(old.appsDict.keys())
  new_appIDs = set(new.appsDict.keys())

  added_appIDs = new_appIDs - old_appIDs
  if added_appIDs:
    print "New application:"
    for a in added_appIDs:
      new.appsDict[a].printMe(2)

  deleted_appIDs = old_appIDs - new_appIDs
  if deleted_appIDs:
    print "Deleted application:"
    for a in deleted_appIDs:
      print '  ', old.appsDict[a]


  new_has_no_active_windows = (new.num_active_windows() == 0)

  # now diff the apps that are in common ...
  for a in old_appIDs.intersection(new_appIDs):
    print_app_diff(old.appsDict[a], new.appsDict[a], new_has_no_active_windows)

