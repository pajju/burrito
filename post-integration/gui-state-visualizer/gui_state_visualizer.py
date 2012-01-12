from pymongo import Connection, ASCENDING, DESCENDING
from BurritoUtils import *

import sys
sys.path.insert(0, '../../GUItracing/')

from parse_gui_trace import DesktopState


def interactive_print(lst):
  idx = 0
  while True:
    (t, s) = lst[idx]
    for i in range(100): print
    print "%d / %d" % (idx + 1, len(lst)), t
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


# Each element is a (datetime object, DesktopState instance)
timesAndStates = []

if __name__ == "__main__":
  session_name = sys.argv[1]

  c = Connection()
  db = c.burrito_db

  gui_col = db.gui_trace

  for dat in gui_col.find({'session_tag': session_name}, sort=[('_id', ASCENDING)]):
    evt_time = dat['_id']
    dt = DesktopState.from_mongodb(dat)
    timesAndStates.append((evt_time, dt))

  interactive_print(timesAndStates)

