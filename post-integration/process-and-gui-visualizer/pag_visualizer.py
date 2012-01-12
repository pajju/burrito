# Crappy PAG (Process And GUI) visualizer

from pymongo import Connection, ASCENDING, DESCENDING

import sys
sys.path.insert(0, '../../GUItracing/')
sys.path.insert(0, '../../SystemTap/')

from parse_gui_trace import DesktopState


session_name = sys.argv[1]

c = Connection()
db = c.burrito_db

proc_col = db.process_trace
gui_col = db.gui_trace

for dat in proc_col.find({'session_tag': session_name}, {'phases.name':1}, sort=[('_id', ASCENDING)]):
  for p in dat['phases']:
    if p['name'] and 'monitor' in p['name']:
      print p

