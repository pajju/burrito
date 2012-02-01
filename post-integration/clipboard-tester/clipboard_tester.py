# Test to see if burrito properly records clipboard copy/paste events

from pymongo import Connection, ASCENDING, DESCENDING
from BurritoUtils import *

import sys
sys.path.insert(0, '../../GUItracing/')

import pprint
p = pprint.PrettyPrinter()

from parse_gui_trace import DesktopState

c = Connection()
db = c.burrito_db

clipboard_col = db.clipboard_trace
gui_col = db.gui_trace

#for evt in clipboard_col.find(sort=[('_id', DESCENDING)], limit=1):
for evt in clipboard_col.find(sort=[('_id', DESCENDING)]):
  print evt['_id']

  src_desktop_cur = gui_col.find({'_id': evt['src_desktop_id']})
  dst_desktop_cur = gui_col.find({'_id': evt['dst_desktop_id']})

  # sanity checks
  assert src_desktop_cur.count() == 1, evt['src_desktop_id']
  assert dst_desktop_cur.count() == 1, evt['dst_desktop_id']

  src_desktop_json = src_desktop_cur[0]
  dst_desktop_json = dst_desktop_cur[0]

  src_desktop = DesktopState.from_mongodb(src_desktop_json)
  dst_desktop = DesktopState.from_mongodb(dst_desktop_json)

  print "Contents:", evt['contents']
  print "Src app:", src_desktop[src_desktop_json['active_app_id']]
  print " window:", src_desktop[src_desktop_json['active_app_id']][src_desktop_json['active_window_index']].title
  print "Dst app:", dst_desktop[dst_desktop_json['active_app_id']]
  print " window:", dst_desktop[dst_desktop_json['active_app_id']][dst_desktop_json['active_window_index']].title
  print

