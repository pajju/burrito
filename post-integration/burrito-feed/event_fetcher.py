# Functions to fetch events from the master MongoDB burrito_db database

'''
File version annotations are stored in:

  burrito_db.annotations.file_annotations

with schema:
  _id: <filename>-<timestamp.isoformat()>
  filename: absolute path to file
  timestamp: datetime object
  annotation: string annotation
  session_tag: session ID


Status update posts are stored in:
  
  burrito_db.annotations.happy_face
  burrito_db.annotations.sad_face
  burrito_db.annotations.status

with schema:
  _id: timestamp
  annotation: comment
  screenshot_filename: full filename of PNG screenshot (only for happy_face and sad_face)
  session_tag: session ID


Webpage and bash command annotations are stored as 'annotation' fields
within their respective original collections.

  burrito_db.gui_trace (for webpage events)
  burrito_db.apps.bash (for bash events)
'''

from pymongo import Connection
c = Connection()
db = c.burrito_db

import sys
sys.path.insert(0, '../../GUItracing/')
from parse_gui_trace import DesktopState

import os, md5

# only display file events for processes with the user's own UID (and
# not, say, system daemons)
MY_UID = os.getuid()


# TODO: make this user-customizable!!!

# ignore certain boring commands, like 'cd', since that simply
# changes pwd and can lead to a proliferation of boring entries
IGNORED_BASH_COMMANDS = set(['cd', 'echo'])

IGNORED_PROCESSES    = set(['xpad', 'stapio', 'gconfd-2'])
IGNORE_PATH_PREFIXES = ['/home/researcher/.', '/tmp/', '/var/', 'PIPE-']

# right now there's NO POINT in displaying files that aren't in /home,
# since those files aren't being versioned by NILFS anyways
HOMEDIR_PREFIX = '/home/'

def ignore_file(filename):
  if not filename.startswith(HOMEDIR_PREFIX):
    return True

  for p in IGNORE_PATH_PREFIXES:
    if filename.startswith(p):
      return True
  return False


# my MongoDB schema overloads timestamp as either a single element
# or a string (kind of an ugly premature optimization, I suppose!)
def get_timestamp_lst(timestamp_field):
  if type(timestamp_field) is list:
    return timestamp_field
  else:
    return [timestamp_field]


class WebpageVisitEvent:
  def __init__(self, title, url, timestamp):
    self.title = title
    self.url = url
    self.timestamp = timestamp
    self.mongodb_collection = db.gui_trace


  # returns a pair: (entire GUI trace object, active window)
  def __get_db_active_window(self):
    m = self.mongodb_collection.find_one({'_id': self.timestamp})
    assert m # should always be found, or we have a problem!
    # find the active GUI window ... GROSS!!!
    active_app_id = m['active_app_id']
    active_window_index = m['active_window_index']
    for a in m['apps']:
      if a['app_id'] == active_app_id:
        for w in a['app']['windows']:
          if w['window_index'] == active_window_index:
            window_dict = w['window']
            return (m, window_dict)
    assert False

  def get_hashtag(self):
    return '#web-' + md5.md5(self.timestamp.isoformat()).hexdigest()[:10] # make it short


  def insert_annotation(self, annotation):
    (gui_trace_obj, active_window_dict) = self.__get_db_active_window()
    active_window_dict['annotation'] = annotation
    # write the WHOLE element back into the database
    self.mongodb_collection.update({'_id': self.timestamp}, gui_trace_obj,
                                   False, False)

  def delete_annotation(self):
    (gui_trace_obj, active_window_dict) = self.__get_db_active_window()
    if 'annotation' in active_window_dict:
      del active_window_dict['annotation']
      # write the WHOLE element back into the database
      self.mongodb_collection.update({'_id': self.timestamp}, gui_trace_obj,
                                     False, False)

  def load_annotation(self):
    (gui_trace_obj, active_window_dict) = self.__get_db_active_window()
    if 'annotation' in active_window_dict:
      return active_window_dict['annotation']
    else:
      return ''

  def printme(self):
    print 'WEB:\t%s "%s"' % (str(self.timestamp), self.title.encode('ascii', 'replace'))


class BashCommandEvent:
  def __init__(self, cmd, pwd, timestamp):
    self.cmd = cmd # a list of all arguments
    self.pwd = pwd
    self.timestamp = timestamp
    self.mongodb_collection = db.apps.bash

  def get_hashtag(self):
    return '#bash-' + md5.md5(self.timestamp.isoformat()).hexdigest()[:10] # make it short

  def insert_annotation(self, annotation):
    self.mongodb_collection.update({'_id': self.timestamp},
                                   {'$set':{'annotation':annotation}}, False, False)

  def delete_annotation(self):
    self.mongodb_collection.update({'_id': self.timestamp},
                                   {'$unset':{'annotation':1}}, False, False)

  def load_annotation(self):
    # try to load the 'annotation' field from the database:
    m = self.mongodb_collection.find_one({'_id':self.timestamp}, {'annotation':1})
    if m and 'annotation' in m: 
      return m['annotation']
    else:
      return ''

  def printme(self):
    print 'BASH:\t%s %s' % (str(self.timestamp), ' '.join(self.cmd))


class FileProvenanceEvent:
  def __init__(self, timestamp, pid, phase_name, session_tag):
    self.timestamp = timestamp
    self.pid = pid

    # remember that a process can have multiple phases when there are
    # multiple execve calls
    self.phase_name = phase_name
    self.mongodb_collection = db.annotations.file_annotations
    self.session_tag = session_tag


  # remember we're annotating a particular version of a file, so make
  # the _id field as the concatenation of the timestamp and filename
  def insert_annotation(self, annotation):
    fn = self.filename
    self.mongodb_collection.save({'_id': fn + '-' + self.timestamp.isoformat(),
                                  'filename': fn,
                                  'timestamp': self.timestamp,
                                  'annotation': annotation,
                                  'session_tag': self.session_tag})

  def delete_annotation(self):
    fn = self.filename
    self.mongodb_collection.remove({'_id': fn + '-' + self.timestamp.isoformat()})

  def load_annotation(self):
    fn = self.filename
    m = self.mongodb_collection.find_one({'_id': fn + '-' + self.timestamp.isoformat()})
    if m:
      return m['annotation']
    else:
      return ''

  # kind of a dumb hashtag, but whatever ...
  def get_hashtag(self):
    id_tuple = self.get_unique_id()
    return '#file-' + md5.md5(str(id_tuple)).hexdigest()[:10] # make it SHORT


class FileReadEvent(FileProvenanceEvent):
  def __init__(self, filename, timestamp, pid, phase_name, session_tag):
    FileProvenanceEvent.__init__(self, timestamp, pid, phase_name, session_tag)
    self.filename = filename

  # create a unique identifier that can be used for de-duplication:
  def get_unique_id(self):
    return ('file_read', self.pid, self.phase_name, self.filename, self.timestamp)

  def printme(self):
    print 'READ:\t%s [PID: %s] %s' % (str(self.timestamp), self.pid, self.filename)


class FileWriteEvent(FileProvenanceEvent):
  def __init__(self, filename, timestamp, pid, phase_name, session_tag):
    FileProvenanceEvent.__init__(self, timestamp, pid, phase_name, session_tag)
    self.filename = filename

  # create a unique identifier that can be used for de-duplication:
  def get_unique_id(self):
    return ('file_write', self.pid, self.phase_name, self.filename, self.timestamp)

  def printme(self):
    print 'WRITE:\t%s [PID: %s] %s' % (str(self.timestamp), self.pid, self.filename)


class DoodleSaveEvent(FileWriteEvent):
  def __init__(self, filename, timestamp, pid, phase_name, session_tag):
    FileWriteEvent.__init__(self, filename, timestamp, pid, phase_name, session_tag)

  def printme(self):
    print 'DOODLE:\t%s [PID: %s] %s' % (str(self.timestamp), self.pid, self.filename)


# Given an entry from the burrito_db.db.gui_trace collection, either
# create a new WebpageVisitEvent or None, if there's no webpage visit
def fetch_webpage_visit_event(gui_trace_elt):
  timestamp = gui_trace_elt['_id']
  desktop_state = DesktopState.from_mongodb(gui_trace_elt)
  active_w = desktop_state.get_first_active_window()

  # ignore non-existent or empty URLs:
  if hasattr(active_w, 'browserURL') and active_w.browserURL:
    prettified_URL = active_w.browserURL
    # urlparse needs a URL to start with something like 'http://'
    if not prettified_URL.startswith('http://') and \
       not prettified_URL.startswith('https://'):
      prettified_URL = 'http://' + prettified_URL

    prettified_title = active_w.title

    # special hacks for Google Chrome:
    if prettified_title.endswith(' - Google Chrome'):
      prettified_title = prettified_title[:(-1 * len(' - Google Chrome'))]
    if prettified_title == 'New Tab':
      return None

    return WebpageVisitEvent(prettified_title, prettified_URL, timestamp)

  return None


# Given an entry from the burrito_db.apps.bash collection, either create
# a new BashCommandEvent or None, if there's no valid event
def fetch_bash_command_event(bash_trace_elt):
  timestamp  = bash_trace_elt['_id']
  my_pwd = bash_trace_elt['pwd']
  cmd_components = bash_trace_elt['command']

  if cmd_components[0] in IGNORED_BASH_COMMANDS:
    return None

  return BashCommandEvent(cmd_components, my_pwd, timestamp)


# Given an entry from the burrito_db.process_trace collection, then
# create a (possibly-empty) list of FileProvenanceEvent objects
def fetch_file_prov_event_lst(process_trace_elt, session_tag):
  ret = []

  # only match the user's own processes!
  if process_trace_elt['uid'] != MY_UID:
    return ret

  pid = process_trace_elt['pid']

  for phase in process_trace_elt['phases']:
    phase_name = phase['name']

    if phase_name in IGNORED_PROCESSES:
      continue

    if phase['files_read']:
      for e in phase['files_read']:
        fn = e['filename']
        if not ignore_file(fn):
          for t in get_timestamp_lst(e['timestamp']):
            ret.append(FileReadEvent(fn, t, pid, phase_name, session_tag))

    if phase['files_written']:
      for e in phase['files_written']:
        fn = e['filename']
        if not ignore_file(fn):
          for t in get_timestamp_lst(e['timestamp']):
            # create a special DoodleSaveEvent if phase_name is
            # gnome-paint, since that represents a doodle (sketch)!
            if phase_name == 'gnome-paint':
              evt = DoodleSaveEvent(fn, t, pid, phase_name, session_tag)
            else:
              evt = FileWriteEvent(fn, t, pid, phase_name, session_tag)
            ret.append(evt)

    if phase['files_renamed']:
      for e in phase['files_renamed']:
        old_fn = e['old_filename']
        new_fn = e['new_filename']

        # create a virtual 'read' for old_fn and a virtual 'write' for new_fn

        if not ignore_file(old_fn):
          for t in get_timestamp_lst(e['timestamp']):
            ret.append(FileReadEvent(old_fn, t, pid, phase_name, session_tag))

        if not ignore_file(new_fn):
          for t in get_timestamp_lst(e['timestamp']):
            ret.append(FileWriteEvent(new_fn, t, pid, phase_name, session_tag))

  return ret



class ToplevelAnnotationEvent:
  def __init__(self, annotation, timestamp, session_tag, screenshot_filename=None):
    self.annotation = annotation
    self.timestamp = timestamp
    self.session_tag = session_tag
    self.screenshot_filename = screenshot_filename

  def serialize(self):
    return {'_id': self.timestamp,
            'screenshot_filename': self.screenshot_filename,
            'annotation': self.annotation,
            'session_tag': self.session_tag}


class HappyFaceEvent(ToplevelAnnotationEvent):
  def __init__(self, annotation, timestamp, session_tag, screenshot_filename):
    ToplevelAnnotationEvent.__init__(self, annotation, timestamp, session_tag, screenshot_filename)

  def save_to_db(self):
    db.annotations.happy_face.save(self.serialize())

  def get_hashtag(self):
    return '#happy-' + md5.md5(self.timestamp.isoformat()).hexdigest()[:10] # make it short

  def printme(self):
    print 'HAPPY:', self.timestamp, self.annotation


class SadFaceEvent(ToplevelAnnotationEvent):
  def __init__(self, annotation, timestamp, session_tag, screenshot_filename):
    ToplevelAnnotationEvent.__init__(self, annotation, timestamp, session_tag, screenshot_filename)

  def save_to_db(self):
    db.annotations.sad_face.save(self.serialize())

  def get_hashtag(self):
    return '#sad-' + md5.md5(self.timestamp.isoformat()).hexdigest()[:10] # make it short

  def printme(self):
    print 'SAD:', self.timestamp, self.annotation


class StatusUpdateEvent(ToplevelAnnotationEvent):
  def __init__(self, annotation, timestamp, session_tag):
    ToplevelAnnotationEvent.__init__(self, annotation, timestamp, session_tag)

  def save_to_db(self):
    db.annotations.status.save(self.serialize())

  def get_hashtag(self):
    return '#status-' + md5.md5(self.timestamp.isoformat()).hexdigest()[:10] # make it short

  def printme(self):
    print 'STATUS_UPDATE:', self.timestamp, self.annotation


def fetch_toplevel_annotation_events(session_tag):
  ret = []

  for m in db.annotations.happy_face.find({'session_tag': session_tag}):
    ret.append(HappyFaceEvent(m['annotation'], m['_id'], m['session_tag'], m['screenshot_filename']))

  for m in db.annotations.sad_face.find({'session_tag': session_tag}):
    ret.append(SadFaceEvent(m['annotation'], m['_id'], m['session_tag'], m['screenshot_filename']))

  for m in db.annotations.status.find({'session_tag': session_tag}):
    ret.append(StatusUpdateEvent(m['annotation'], m['_id'], m['session_tag']))

  return ret


# somewhat gimpy
class ActiveGUIWindowEvent:
  def __init__(self, desktop_state, timestamp):
    self.desktop_state = desktop_state
    self.timestamp = timestamp

    active_windows_lst = desktop_state.get_active_windows()
    assert len(active_windows_lst) == 1
    active_appID, active_windowIndex = active_windows_lst[0]

    active_app = desktop_state[active_appID]
    active_window = active_app[active_windowIndex]

    self.active_app_pid = active_app.pid
    self.active_window_title = active_window.title

  def printme(self):
    print 'GUI:\t%s [PID: %s] "%s"' % (str(self.timestamp), str(self.active_app_pid), self.active_window_title)


def fetch_active_gui_window_event(gui_trace_elt):
  timestamp = gui_trace_elt['_id']
  desktop_state = DesktopState.from_mongodb(gui_trace_elt)

  if desktop_state.num_active_windows() > 0:
    return ActiveGUIWindowEvent(desktop_state, timestamp)
  else:
    return None


class ActiveVimBufferEvent:
  def __init__(self, pid, filename, timestamp):
    self.pid = pid
    self.filename = filename
    self.timestamp = timestamp

  def printme(self):
    print 'VIM:\t%s [PID: %s] %s' % (str(self.timestamp), str(self.pid), self.filename)


def fetch_active_vim_buffer_event(vim_trace_elt):
  if vim_trace_elt['event'] == 'BufEnter':
    return ActiveVimBufferEvent(vim_trace_elt['pid'], vim_trace_elt['filename'], vim_trace_elt['_id'])
  else:
    return None

