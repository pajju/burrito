# Integrate all burrito data streams into a centralized MongoDB database
# Created: 2011-11-25

# This process is meant to be run continuously in the background, doing
# incremental indexing approximately every INDEXING_PERIOD_SEC seconds.
# It is a SINGLE-THREADED process, so it will complete one full round of
# incremental indexing, pause for INDEXING_PERIOD_SEC, and then resume
# the next round.  It will run exit_handler() when gracefully killed.

# Note that you can also run this script on an archival dataset (that's
# no longer changing), and it will still work fine.

# TODO: Monitor error output and think about how to make this script
# more failure-oblivious, since we want it to always run in the
# background throughout the duration of the user's session.

'''
Collections within MongoDB burrito_db:

burrito_db.process_trace
  - contains the cleaned output from pass-lite.out.*
  - _id is a concatenation of creation timestamp and PID
  - most_recent_event_timestamp is the most recent time that this
    process entry was updated

burrito_db.gui_trace
  - contains the cleaned output from gui.trace.*,
    integrated with PID information from burrito_db.process_trace
  - _id is the unique timestamp of the GUI event

burrito_db.clipboard_trace
  - contains information about X Window copy/paste events. Fields:
    - contents:       string contents of clipboard
    - copy_time:      datetime of copy event (not necessarily unique
                      since there can be multiple pastes for one copy)
    - _id:            datetime of paste event (should be unique primary key)
    - src_desktop_id: key of source desktop state in burrito_db.gui_trace
    - dst_desktop_id: key of destination desktop state in burrito_db.gui_trace


burrito_db.apps.xpad
burrito_db.apps.vim
burrito_db.apps.bash
burrito_db.apps.chrome
burrito_db.apps.evince
burrito_db.apps.pidgin
  etc. etc. etc.
  - custom logs for individual apps that plug into burrito
  - all logs are indexed by the 'timestamp' field by default (i.e.,
    convert it to a Python datetime and set it as a unique '_id' field
    for MongoDB)

burrito_db.session_status
  - _id:               unique session tag (e.g., sub-directory name within
                       /var/log/burrito)
  - last_updated_time: timestamp of last update to this session

'''

INDEXING_PERIOD_SEC = 10
#INDEXING_PERIOD_SEC = 30


import os, sys, time, optparse
from signal import signal, SIGTERM
from sys import exit
import atexit

import GUItracing
import SystemTap
from SystemTap import Process, parse_raw_pass_lite_line
from BurritoUtils import *

from pymongo import Connection, ASCENDING


# for gen_entries_from_multifile_log
gui_trace_parser_state = {'file_prefix': 'gui.trace.',
                          'callback': json.loads,
                          'cur_file_index': 0, 'cur_line' : 0}

pass_lite_parser_state = {'file_prefix': 'pass-lite.out.',
                          'callback': parse_raw_pass_lite_line,
                          'cur_file_index': 0, 'cur_line' : 0}


# for gen_entries_from_json_log, using json.loads() to parse each line
clipboard_json_parser_state = {'filename': 'clipboard.log', 'cur_line': 0}
bash_json_parser_state      = {'filename': 'bash-history.log', 'cur_line': 0}
vim_json_parser_state       = {'filename': 'vim-trace.log', 'cur_line': 0}
xpad_json_parser_state      = {'filename': 'xpad-notes.log', 'cur_line': 0}


# In our current 'epoch' of indexing, we only snapshot the contents of
# all logs that occurred STRICTLY BEFORE this timestamp
cur_epoch_timestamp  = 0
prev_epoch_timestamp = 0

# The FINAL DesktopState object from the previous epoch, which is
# necessary for detecting copy-and-paste events.
prev_epoch_final_gui_state = None # type is (timestamp, DesktopState)


# GUI states that are the source of clipboard copy events
#
# Key: timestamp of COPY event
# Value: (timestamp of DesktopState, DesktopState)
clipboard_copy_gui_states = {}


# Dict mapping PIDs to active processes (i.e., haven't yet exited)
# Key: PID
# Value: Process object
pid_to_active_processes = {}

# the PARENT pids of all exited processes
exited_process_ppids = set()


# Use time proximity and name heuristics to try to find the PID that
# matches a particular app name and window creation event timestamp
#
# 8 seconds might seem like a LONG time, but sometimes when I launch
# Google Chrome for the first time, it takes up to 6 seconds to start up
# in my slow-ass VM.  Of course, the longer you wait, the greater chance
# you have of false positives creeping up, so be somewhat cautious!
EXECVE_TO_WINDOW_APPEAR_THRESHOLD_MS = 8000

# Each element is an '_id' field from an entry in the MongoDB proc_col
# collection that's already been matched against a GUI element.  This is
# important for implementing "first-come, first-served" behavior for apps
# like 'evince' which launch multiple processes in rapid succession.
# i.e., the first window gets the earliest-execve'd process, etc.
#
# This set is VERY IMPORTANT because without it, if you execve multiple
# identically-named processes (e.g., evince) within a time span of
# EXECVE_TO_WINDOW_APPEAR_THRESHOLD_MS, then there's a chance that all
# of the windows will match up against the PID of the first-launched
# process.  This way, the first window to appear matches up against the
# first-launched PID, the second with the second, etc.
#
# This correspondence is correct assuming that process execve order
# corresponds to GUI window creation order, which is a reasonable
# (although not perfect) assumption.
already_matched_processes = set()


# Keep an ongoing record of which GUI apps are matched with which PIDs,
# and also the 'end times' of those processes, so that we know when to
# 'expire' the matches ...
#
# Note that this global dict persists across multiple calls to
# incremental_index_gui_trace_logs ...
#
# Key: (app ID, app name)
# Value: (matched PID, end time of matched process as a datetime object)
currently_matched_apps = {}


in_critical_section = False # crude "lock"


# also adds session tag!
def save_tagged_db_entry(col, json_entry):
  global session_tag
  json_entry['session_tag'] = session_tag
  col.save(json_entry) # does an insert (if not-exist) or update (if exists)


# Parse one line at a time, and as a side effect, update parser_state so
# that we can know where we've parsed up to, so that we can resume where
# we left off during the next round of processing.
def gen_entries_from_multifile_log(parser_state, max_timestamp):
  global logdir
  print "gen_entries_from_multifile_log {"

  callback = parser_state['callback']

  while True:
    filename = parser_state['file_prefix'] + str(parser_state['cur_file_index'])
    fullpath = os.path.join(logdir, filename)
    f = open(fullpath)

    print "  Processing", fullpath, "at line", parser_state['cur_line']

    for (line_no, line) in enumerate(f):
      # skip directly to cur_line
      if line_no < parser_state['cur_line']:
        continue

      # If any parse error occurs, just straight-up QUIT and wait until
      # the next round of indexing when hopefully the file's contents will
      # be more intact.  In rare cases, our loggers out partial lines
      # to the output file, despite printf newline buffering.
      try:
        entry = callback(line.rstrip())
        # don't parse entries greater than current timestamp

        # each entry should either have an attribute named timestamp or
        # a dict key named 'timestamp'

        entry_timestamp = None
        if hasattr(entry, 'timestamp'):
          entry_timestamp = entry.timestamp
        else:
          entry_timestamp = entry['timestamp']
        assert type(entry_timestamp) in (int, long)
        if entry_timestamp >= max_timestamp:
          print "} max_timestamp reached (file index: %d, line: %d)" % (parser_state['cur_file_index'], parser_state['cur_line'])
          return

        yield entry
      except:
        # failure oblivious, baby!
        print >> sys.stderr, "WARNING: skipping line %d in %s due to uncaught exception" % (line_no, fullpath)
        pass

      parser_state['cur_line'] = line_no + 1

    f.close()

    # ok, so if the NEXT sequentially-higher log file actually exists,
    # then move onto processing it.  but if it doesn't exist, then keep
    # the counter at THIS file and simply return.
    next_file = parser_state['file_prefix'] + str(parser_state['cur_file_index'] + 1)
    if os.path.isfile(os.path.join(logdir, next_file)):
      parser_state['cur_file_index'] += 1
      parser_state['cur_line'] = 0
    else:
      print "} file ended (file index: %d, line: %d)" % (parser_state['cur_file_index'], parser_state['cur_line'])
      return

  assert False


# Parse one line at a time using json.loads, and as a side effect,
# update parser_state so that we can know where we've parsed up to, so
# that we can resume where we left off during the next round of
# processing.
def gen_entries_from_json_log(parser_state, max_timestamp):
  global logdir
  print "gen_entries_from_json_log {"

  fullpath = os.path.join(logdir, parser_state['filename'])
  if not os.path.isfile(fullpath):
    print "} file", fullpath, "doesn't exist"
    return

  f = open(fullpath)

  print "  Processing", fullpath, "at line", parser_state['cur_line']

  for (line_no, line) in enumerate(f):
    # skip directly to cur_line
    if line_no < parser_state['cur_line']:
      continue

    # If any parse error occurs, just straight-up QUIT and wait until
    # the next round of indexing when hopefully the file's contents will
    # be more intact.  In rare cases, our loggers out partial lines
    # to the output file, despite printf newline buffering.
    try:
      entry = json.loads(line.rstrip())

      # don't parse entries greater than current timestamp
      # each entry should either have a dict key named 'timestamp'

      entry_timestamp = entry['timestamp']
      assert type(entry_timestamp) in (int, long)
      if entry_timestamp >= max_timestamp:
        print "} max_timestamp reached (line: %d)" % (parser_state['cur_line'],)
        return

      yield entry
    except:
      f.close()
      print "} exception (line: %d)" % (parser_state['cur_line'],)
      return

    parser_state['cur_line'] = line_no + 1


  f.close()
  print "} file ended (line: %d)" % (parser_state['cur_line'],)


# This function runs when the process is killed by civilized means
# (i.e., not "kill -9")
def exit_handler():
  global session_status_col
  cur_time = get_ms_since_epoch()
  print >> sys.stderr, "GOODBYE incremental_integrator.py: in_critical_section =", in_critical_section, ", time:", cur_time
  session_status_col.save({'_id': session_tag, 'last_updated_time': datetime.datetime.now()})

  # Since this call is asynchronous, we might be in the midst of
  # executing a critical section.  In this case, just don't do anything
  # to rock the boat :)  Since MongoDB doesn't have traditional db
  # transactions, our db still might not be in a great state, but it's
  # better than us mucking more with it!!!
  if not in_critical_section:
    do_incremental_index() # go for one last hurrah!

    # now make all active processes into exited processes since our
    # session has ended!
    for p in pid_to_active_processes.values():
      p.mark_exit(cur_time, -1) # use a -1 exit code to mark that it was "rudely" killed :)
      handle_process_exit_event(p)


### pass-lite logs ###

def handle_process_exit_event(p):
  global pid_to_active_processes, exited_process_ppids, proc_col

  assert p.exited

  del pid_to_active_processes[p.pid]
  proc_col.remove({'_id': p.unique_id()}) # remove and later (maybe) re-insert

  skip_me = False

  # Optimization: if this process is 'empty' (i.e., has no phases)
  # and isn't the parent of any previously-exited process or
  # currently-active process, then there is NO POINT in storing it
  # into the database.
  if (not p.phases):
    active_process_ppids = set()
    for p in pid_to_active_processes.itervalues():
      active_process_ppids.add(p.ppid)
    if (p.pid not in exited_process_ppids) and (p.pid not in active_process_ppids):
      skip_me = True

  if not skip_me:
    save_tagged_db_entry(proc_col, p.serialize())
    exited_process_ppids.add(p.ppid)


def incremental_index_pass_lite_logs():
  global proc_col, cur_epoch_timestamp, prev_epoch_timestamp, pid_to_active_processes

  for pl_entry in gen_entries_from_multifile_log(pass_lite_parser_state, cur_epoch_timestamp):
    if pl_entry.pid not in pid_to_active_processes:
      # remember, creating a new process adds it to
      # the pid_to_active_processes dict (weird, I know!)
      p = Process(pl_entry.pid, pl_entry.ppid, pl_entry.uid, pl_entry.timestamp, pid_to_active_processes)
      assert pid_to_active_processes[pl_entry.pid] == p # sanity check
    else:
      p = pid_to_active_processes[pl_entry.pid]

    is_exited = p.add_entry(pl_entry)

    if is_exited:
      handle_process_exit_event(p)


  # Optimization: don't bother updating the database with info for
  # active processes that haven't changed since the previous indexing
  # epoch, since their data will be identical ...
  changed_active_processes = []
  for p in pid_to_active_processes.itervalues():
    if p.most_recent_event_timestamp >= prev_epoch_timestamp:
      changed_active_processes.append(p)

  for p in changed_active_processes:
    save_tagged_db_entry(proc_col, p.serialize())

  print "=== %d active procs (%d changed) ===" % (len(pid_to_active_processes), len(changed_active_processes))


### GUI tracer logs ###

def match_gui_proc_name(gui_app_name, process_name):
  # WTF in the ultimate form of dumbassery, the SystemTap execname()
  # function seems to only return the first 15 characters of a process
  # name.  It seems like the 15-character limit is in /proc/<pid>/status
  #   http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=513460
  #   http://blogs.oracle.com/bnitz/entry/dtrace_and_process_names
  #
  # e.g., a process named "gnome-system-monitor" will show up with
  #   gui_app_name = "gnome-system-monitor"
  #   process_name = "gnome-system-mo"
  #
  # the best we can do is to do a prefix match for such names ...
  if len(process_name) == 15:
    return gui_app_name.startswith(process_name)
  else:
    # normal case
    return gui_app_name == process_name

  # Ha, seems like there's no more need for this special-case hack for #
  # now ...
  #
  # This still isn't satisfying, though, since the google-chrome process
  # sometimes DIES while chrome is still running ... ugh
  #if gui_app_name == 'google-chrome':
  #  return process_name == 'chrome'
  #else:
  #  return gui_app_name == process_name


# returns either None or a pair of (PID, process exit_time)
def find_PID_and_endtime(gui_app_name, window_create_timestamp):
  global proc_col, already_matched_processes, EXECVE_TO_WINDOW_APPEAR_THRESHOLD_MS

  lower_bound = encode_datetime(window_create_timestamp - EXECVE_TO_WINDOW_APPEAR_THRESHOLD_MS)
  upper_bound = encode_datetime(window_create_timestamp)

  # match then sort chronologically by process phase start_time to get
  # the EARLIEST process first:
  matches = proc_col.find({"phases.start_time":{"$gt":lower_bound, "$lt":upper_bound}}, {"phases.name":1, "pid":1, "exit_time":1}).sort("phases.start_time", ASCENDING)

  #print >> sys.stderr, "find_PID_and_endtime:", gui_app_name, lower_bound, upper_bound
  for m in matches:
    #print >> sys.stderr, ' candidate:', m

    # if the process CROAKED before your window was even created, then
    # obviously skip it!
    if m['exit_time'] and m['exit_time'] < upper_bound:
      continue

    phase_lst = m['phases']
    for p in phase_lst:
      proc_name = p['name']
      if proc_name:
        # note that already_matched_processes implements "first-come,
        # first-served" behavior for apps like 'evince' which launch
        # multiple processes in succession.  i.e., the first window gets
        # the earliest-execve'd process, etc.
        # (if we don't use this, then BOTH evince windows will get
        # associated to the FIRST-launched 'evince. process.)
        if match_gui_proc_name(gui_app_name, proc_name) and (m['_id'] not in already_matched_processes):
          already_matched_processes.add(m['_id'])
          #print >> sys.stderr, '   MATCH:', proc_name, m['pid'], m['exit_time']
          assert m['pid'] > 0
          return (m['pid'], m['exit_time'])

  return None


def incremental_index_gui_trace_logs():
  global gui_col, prev_epoch_timestamp, cur_epoch_timestamp, currently_matched_apps, prev_epoch_final_gui_state

  # each element is a pair of (timestamp, DesktopState)
  # that falls between prev_epoch_timestamp and cur_epoch_timestamp
  timesAndStates = []


  # return the (timestamp, DesktopState) within timesAndStates
  # corresponding to the most recent entry whose timestamp <= target_time
  def get_gui_state_at_time(target_time):
    if not len(timesAndStates) or target_time < timesAndStates[0][0]:
      # crap, we've got no new GUI states in this epoch, so let's rely on prev_epoch_final_gui_state
      assert prev_epoch_final_gui_state
      assert prev_epoch_final_gui_state[0] <= target_time # TODO: this assertion sometimes fails :(
      return prev_epoch_final_gui_state
    else:
      assert target_time >= timesAndStates[0][0] # boundary condition

      for ((prev_t, prev_state), (cur_t, cur_state)) in zip(timesAndStates, timesAndStates[1:]):
        assert prev_t <= cur_t # sanity check

        # use a half-open interval, preferring the PAST
        if prev_t <= target_time < cur_t:
          return (prev_t, prev_state)

      # check the FINAL entry if there's no match yet:
      final_time, final_state = timesAndStates[-1]
      assert target_time >= final_time
      return timesAndStates[-1]


  for data in gen_entries_from_multifile_log(gui_trace_parser_state, cur_epoch_timestamp):
    timestamp = data['timestamp']

    # in RARE cases, GUI log entries come in out of time order, which is
    # really really bizarre ... so the best we can do now is to DROP
    # those entries and issue a warning
    if timesAndStates and (timestamp < timesAndStates[-1][0]):
      print >> sys.stderr, "WARNING: GUI trace entry is not in chronological order, so skipping"
      print >> sys.stderr, "(its timestamp [%d] is less than the prev. timestamp [%d])" % (timestamp, timesAndStates[-1][0])
      print >> sys.stderr, data
      print >> sys.stderr
      continue


    assert prev_epoch_timestamp <= timestamp < cur_epoch_timestamp # sanity check! # TODO: this assertion sometimes fails :(

    timestamp_dt = encode_datetime(timestamp)
    dt = GUItracing.DesktopState(data['desktop_state'])

    timesAndStates.append((timestamp, dt))


    # first fill in PID fields from currently_matched_apps
    for (appId, app) in dt.appsDict.iteritems():
      k = (appId, app.name)
      if k in currently_matched_apps:
        matched_PID, matched_proc_end_dt = currently_matched_apps[k]
        # this entry has expired, so get rid of it!!!
        if matched_proc_end_dt and matched_proc_end_dt < timestamp_dt:
          #print >> sys.stderr, "DELETE:", k
          del currently_matched_apps[k]
        else:
          app.pid = matched_PID # set it!
          #print >> sys.stderr, "Set", app.name, "to pid", app.pid

    # Try to find a PID match for a window creation event ...
    if 'event_type' in data and data['event_type'] == 'window:create':
      t        = data['timestamp']
      appId    = data['src_app_id']
      frameIdx = data['src_frame_index']

      assert type(t) in (int, long)
      assert type(appId) is int
      assert type(frameIdx) is int

      app = dt.appsDict[appId]

      if not app.pid: # don't DOUBLE-SET the pid field!
        ret = find_PID_and_endtime(app.name, t)
        if ret:
          pid, _ = ret
          app.pid = pid
          currently_matched_apps[(appId, app.name)] = ret
          #print >> sys.stderr, "INSERT:", (appId, app.name), "->", ret


  # This is an important step that must be run BEFORE doing copy-paste
  # event detection, since that stage assumes that there is at most one
  # active window at copy/paste time ...
  timesAndStates = GUItracing.enforceSoloActiveWindow(timesAndStates, prev_epoch_final_gui_state)


  # Incrementally process the clipboard log ...
  # (do this BEFORE optimizing timesAndStates, since we don't want the
  # states disappearing)
  for data in gen_entries_from_json_log(clipboard_json_parser_state, cur_epoch_timestamp):
    event_timestamp = data['timestamp']

    (desktop_state_timestamp, desktop_state) = get_gui_state_at_time(event_timestamp)
    assert desktop_state_timestamp <= event_timestamp

    # first pin the appropriate desktop_state instance so that it
    # doesn't get optimized away (and actually gets stored to the db)
    desktop_state.pinned = True


    global clipboard_copy_gui_states
    if data['event_type'] == 'copy':
      # remember that the key is the COPY EVENT's timestamp!!!
      clipboard_copy_gui_states[event_timestamp] = (desktop_state_timestamp, desktop_state)
    else:
      assert data['event_type'] == 'paste'

      copy_time_ms  = data['copy_time_ms']
      paste_x       = data['x']
      paste_y       = data['y']

      (src_desktop_timestamp, src_desktop_state) = clipboard_copy_gui_states[copy_time_ms]

      try:
        assert src_desktop_state.num_active_windows() == 1
        assert desktop_state.num_active_windows() == 1

        # Bounds-check the x & y coordinates with paste_window ...
        paste_window = desktop_state.get_first_active_window()
        assert paste_window.x <= paste_x <= (paste_window.x + paste_window.width)
        assert paste_window.y <= paste_y <= (paste_window.y + paste_window.height)
      except AssertionError:
        print >> sys.stderr, "AssertionError when processing copy/paste event:", data
        continue # be failure-oblivious


      serialized_state = {}
      serialized_state['copy_time'] = encode_datetime(copy_time_ms)
      serialized_state['_id'] = encode_datetime(event_timestamp) # unique primary key
      serialized_state['src_desktop_id'] = encode_datetime(src_desktop_timestamp)
      serialized_state['dst_desktop_id'] = encode_datetime(desktop_state_timestamp)
      serialized_state['contents'] = data['contents']

      # yet more sanity checks ...
      assert serialized_state['src_desktop_id'] <= serialized_state['copy_time']
      assert serialized_state['dst_desktop_id'] <= serialized_state['_id']

      save_tagged_db_entry(clipboard_col, serialized_state)
      #print "  Added copy/paste event:", serialized_state['src_desktop_id'], ',', serialized_state['dst_desktop_id']


  # confirm that all timestamps are UNIQUE, so they can be used as
  # unique MongoDB keys (i.e., '_id' field)
  uniqueTimes = set(e[0] for e in timesAndStates)
  assert len(uniqueTimes) == len(timesAndStates)

  # pin the final entry so that it doesn't get optimized away; we might
  # need it for copy-and-paste detection during the next iteration
  if len(timesAndStates):
    timesAndStates[-1][1].pinned = True
    prev_epoch_final_gui_state = timesAndStates[-1]


  # As a FINAL step, optimize timesAndStates to cut down on noise ...
  #
  # Note that we have to do clipboard entry matching BEFORE we optimize
  # the trace, or else the matching GUI states might be optimized away
  timesAndStates = GUItracing.optimize_gui_trace(timesAndStates)

  if len(timesAndStates):
    assert timesAndStates[-1] == prev_epoch_final_gui_state

  for (t, s) in timesAndStates:
    serialized_state = s.serialize()
    serialized_state['_id'] = encode_datetime(t) # unique!
    save_tagged_db_entry(gui_col, serialized_state)

  if len(timesAndStates):
    print "=== Added %d GUI trace entries ===" % (len(timesAndStates))



# use the 'timestamp' field as the unique MongoDB '_id' (after
# converting to datetime)
def incremental_index_app_plugin(parser_state, db_cursor):
  global cur_epoch_timestamp
  for json_data in gen_entries_from_json_log(parser_state, cur_epoch_timestamp):
    json_data['_id'] = encode_datetime(json_data['timestamp']) # convert to datetime object!
    del json_data['timestamp']
    save_tagged_db_entry(db_cursor, json_data)


def do_incremental_index():
  global cur_epoch_timestamp, prev_epoch_timestamp
  cur_epoch_timestamp = get_ms_since_epoch()

  # process the pass-lite logs BEFORE GUI logs, since we want to
  # integrate the latest data from pass-lite logs into the GUI stream
  # to find desktop app PIDs

  incremental_index_pass_lite_logs()
  incremental_index_gui_trace_logs()

  # do incremental parsing for custom apps:
  incremental_index_app_plugin(vim_json_parser_state, vim_col)
  incremental_index_app_plugin(bash_json_parser_state, bash_col)
  incremental_index_app_plugin(xpad_json_parser_state, xpad_col)

  session_status_col.save({'_id': session_tag, 'last_updated_time': encode_datetime(cur_epoch_timestamp)})
  prev_epoch_timestamp = cur_epoch_timestamp


if __name__ == "__main__":
  parser = optparse.OptionParser()

  parser.add_option("-s", "--session", dest="session_tag",
                    help="Session tag")
  parser.add_option("-d", "--delete-session", dest="delete_session",
                    action="store_true",
                    help="Remove all db entries for session")
  parser.add_option("-o", "--one-shot", dest="one_shot",
                    action="store_true",
                    help="Run only one full round of indexing and then exit")

  (options, args) = parser.parse_args()

  logdir = args[0]
  assert os.path.isdir(logdir)

  # Unique tag name for this session.  Usually set this to the
  # sub-directory name of this session within /var/log/burrito
  #
  # This tag comes in handy both for discovering the origin of some
  # document in the database and also for bulk-clearing all the documents
  # matching a particular session tag.
  session_tag = options.session_tag
  assert session_tag


  # Setup MongoDB stuff:
  c = Connection()
  db = c.burrito_db

  proc_col = db.process_trace
  gui_col = db.gui_trace
  clipboard_col = db.clipboard_trace
  xpad_col = db.apps.xpad
  vim_col = db.apps.vim
  bash_col = db.apps.bash
  session_status_col = db.session_status

  all_cols = [proc_col, gui_col, clipboard_col, xpad_col, vim_col, bash_col]

  # First clear all entries matching session_tag:
  for c in all_cols:
    c.remove({"session_tag": session_tag})
  session_status_col.remove({"_id": session_tag})

  if options.delete_session:
    print "Done deleting session named '%s'" % (session_tag,)
    sys.exit(0)


  # Create indices

  # TODO: I don't know whether it's wasteful or dumb to KEEP creating
  # these indices every time you start up the connection ...
  proc_col.ensure_index('pid')
  proc_col.ensure_index('exited')
  proc_col.ensure_index('most_recent_event_timestamp')

  # For time range searches!  This multi-key index ensures fast
  # searches for creation_time alone too!
  proc_col.ensure_index([('creation_time', ASCENDING), ('exit_time', ASCENDING)])

  proc_col.ensure_index('phases.name')
  proc_col.ensure_index('phases.start_time')
  proc_col.ensure_index('phases.files_read.timestamp')
  proc_col.ensure_index('phases.files_written.timestamp')
  proc_col.ensure_index('phases.files_renamed.timestamp')

  # index all collections by session_tag:
  for c in all_cols:
    c.ensure_index('session_tag')


  # one-shot mode is useful for debugging or running on archival logs
  if options.one_shot:
    do_incremental_index()
    sys.exit(0)


  atexit.register(exit_handler)
  signal(SIGTERM, lambda signum,frame: exit(1)) # trigger the atexit function to run

  # this loop can only be interrupted by exit_handler()
  while True:
    # sleep first so that we can give the logs some time to build up at
    # the beginning of a login session ...
    time.sleep(INDEXING_PERIOD_SEC)
    in_critical_section = True
    do_incremental_index()
    in_critical_section = False

