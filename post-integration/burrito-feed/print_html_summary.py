# Prints an HTML summary of a particular login session


# TODO: display annotations

# TODO: scan through annotations for hashtags (e.g., #bash-238348) and
#       highlight those as HTML hyperlinks to other parts of the
#       document (or later to other documents)

import os, sys
from pymongo import Connection
from event_fetcher import *

from collections import defaultdict
from html_utils import *


# 'Checkpoints' are indicated by:
# 1.) Happy face events
# 2.) Sad face events
# 3.) Status update posts
CHECKPOINT_TYPES = (HappyFaceEvent, SadFaceEvent, StatusUpdateEvent)

IGNORED_FILES = ['bash_burrito_to_json.py']


session_tag = sys.argv[1]

c = Connection()
db = c.burrito_db

db_bash_collection = db.apps.bash
db_proc_collection = db.process_trace
db_gui_trace = db.gui_trace


# fetch bash commands:
all_events = []
for m in db_bash_collection.find({'session_tag': session_tag}):
  evt = fetch_bash_command_event(m)
  if evt:
    all_events.append(evt)

# fetch file provenance events:
for m in db_proc_collection.find({"session_tag": session_tag},
                                 {'pid':1, 'uid':1, 'phases':1}):
  evts = fetch_file_prov_event_lst(m, session_tag)
  all_events.extend(evts)

# fetch webpage visit events:
for m in db_gui_trace.find({"session_tag": session_tag}):
  web_visit_evt = fetch_webpage_visit_event(m)
  if web_visit_evt:
    all_events.append(web_visit_evt)

# fetch checkpoint events: HappyFaceEvent, SadFaceEvent, StatusUpdateEvent
all_events.extend(fetch_toplevel_annotation_events(session_tag))


class TreeNode:
  def __init__(self, path_component):
    self.path_component = path_component
    self.children = [] # TreeNode instances

    # for leaf nodes only
    self.fullpath = None
    self.labels = set()

  def get_child(self, path_component):
    for c in self.children:
      if c.path_component == path_component:
        return c
    return None

  def add_child(self, path_component):
    self.children.append(TreeNode(path_component))

  def printme(self, indent=0):
    print (' '*indent) + self.path_component,
    if self.fullpath:
      assert self.labels
      print '|', sorted(self.labels), self.fullpath
    else:
      print
    for c in self.children:
      c.printme(indent+2)


# adds filename to the tree rooted at tree_root by decomposing its path components
def add_path(filename, tree_root, label):
  assert filename[0] == '/' # we expect absolute paths!
  toks = filename.split('/')
  assert toks[0] == ''
  toks = toks[1:]

  cur_node = tree_root
  for (idx, path_component) in enumerate(toks):
    child = cur_node.get_child(path_component)
    if not child:
      cur_node.add_child(path_component)

    child = cur_node.get_child(path_component)
    assert child
    # leaf node
    if idx == len(toks) - 1:
      child.fullpath = filename
      child.labels.add(label)
      # exit!
    else:
      cur_node = child # recurse!


# print some sensible summary of the events in evts :0
def print_summary(evts):
  webpages_visited = set() # set of tuples (url, title)

  # Key:   pwd
  # Value: set of command (tuples) run in pwd
  bash_commands = defaultdict(set)

  doodles_drawn = []

  # Decomposes a file's full path into a 'tree'
  files_read_dict = {}
  files_written_dict = {}

  file_tree = TreeNode('/')

  for e in evts:
    if e.__class__ == DoodleSaveEvent:
      doodles_drawn.append(e)
    elif e.__class__ == FileReadEvent:
      add_path(e.filename, file_tree, 'read')
    elif e.__class__ == FileWriteEvent:
      add_path(e.filename, file_tree, 'write')
    elif e.__class__ == BashCommandEvent:
      bash_commands[e.pwd].add(tuple(e.cmd))
    elif e.__class__ == WebpageVisitEvent:
      webpages_visited.add((e.url, e.title))
    else:
      assert e.__class__ in CHECKPOINT_TYPES


  for pwd in sorted(bash_commands.keys()):
    print pwd
    for cmd in sorted(bash_commands[pwd]):
      print ' ', ' '.join(cmd)
  print

  for (url, title) in sorted(webpages_visited, key=lambda e:e[1]):
    print url, title
  print

  file_tree.printme()


  for d in doodles_drawn:
    d.printme()
  print


  # the last element MIGHT be in CHECKPOINT_TYPES, but it might not be either ...
  last_evt = evts[-1]
  if last_evt.__class__ in CHECKPOINT_TYPES:
    # render the checkpoint object
    last_evt.printme()


# Phases are separated by checkpoint events, which have type CHECKPOINT_TYPES
# Each phase is itself a list of events, ending in a checkpoint event
phases = []

cur_phase = []

# big alphabetical sort!
for e in sorted(all_events, key=lambda e:e.timestamp):
  cur_phase.append(e)
  if e.__class__ in CHECKPOINT_TYPES:
    phases.append(cur_phase)
    cur_phase = []

if cur_phase: phases.append(cur_phase) # get the last one!

for p in phases:
  print '---'
  print_summary(p)

