# Demo of source file provenance viewer


# TODO: handle copy-and-paste events later if we want more precision
# for, say, ranking

# TODO: if we want to rank webpages/files more precisely, we could
# measure the relative amounts of time spent looking at those things in
# active GUI windows and rank accordingly

# TODO: support filtering by a time range rather than just a session tag

# TODO: support clicking on files to view that version's contents, diffs, etc.


import pygtk
pygtk.require('2.0')
import gtk, pango, gobject

import os, sys
import datetime
import filecmp
import difflib
import mimetypes

from pymongo import Connection, ASCENDING, DESCENDING

from pygtk_burrito_utils import *

from BurritoUtils import *
from urlparse import urlparse

sys.path.insert(0, '../../GUItracing/')

from annotation_component import AnnotationComponent
from event_fetcher import *
from collections import defaultdict

import atexit
from signal import signal, SIGTERM

from file_version_manager import FileVersionManager
from burrito_feed import *

from parse_gui_trace import DesktopState


# hard-code in a bunch of extensions for documents that we want to track:
def document_extension_whitelisted(fn):
  ext = os.path.splitext(fn)[-1].lower()
  return ext in ('.xls', '.doc', '.docx', '.pdf', '.ods', '.odp', '.odt', '.sxw')


# Represents what happens during a particular Vim editing session,
# with a focus on target_filename
class VimFileEditSession:
  
  # represents a series of consecutive FileWriteEvent instances to
  # target_filename without any intervening barrier events
  class CoalescedWrite:
    def __init__(self, first_write_event):
      self.first_write_timestamp = first_write_event.timestamp
      self.timestamp = self.first_write_timestamp # for sorting purposes

      self.last_write_event = None
      self.last_write_timestamp = None
      self.add_write_event(first_write_event)

      self.ending_event = None # what's responsible for ending this streak?


    def add_write_event(self, write_evt):
      self.last_write_event = write_evt
      self.last_write_timestamp = self.last_write_event.timestamp

    def finalize(self, ending_event):
      self.ending_event = ending_event


    def printme(self):
      print 'CoalescedWrite: %s to %s' % \
            (str(self.first_write_timestamp), str(self.last_write_timestamp))


  # represents a faux version of target_filename
  class FauxVersion:
    def __init__(self, target_filename, start_timestamp, fvm):
      self.target_filename = target_filename
      self.start_timestamp = start_timestamp

      self.fvm = fvm

      # will update in finalize()
      self.coalesced_write_evt = None
      self.end_timestamp = None

      self.timestamp = start_timestamp # for sorting purposes

      # Each element is a WebpageVisitEvent (TODO: de-dup later)
      self.webpages_visited = []

      # Key: filename
      # Value: timestamp of FIRST read/write
      self.other_vim_files_read   = {}
      self.other_vim_files_edited = {}

      # files read by external non-vim programs
      # Key: filename
      # Value: timestamp of FIRST read
      self.non_vim_files_read = {}

      self.doodle_save_events = []
      self.happy_face_events = []
      self.sad_face_events = []
      self.status_update_events = []


    def get_last_write_event(self):
      return self.coalesced_write_evt.last_write_event


    def add_ending_event(self, coalesced_write_evt):
      assert not self.end_timestamp
      self.coalesced_write_evt = coalesced_write_evt
      self.end_timestamp = self.coalesced_write_evt.last_write_timestamp

      # if you ended on a HappyFaceEvent or SadFaceEvent, then add that
      # to self, since it's like a "commit message" for this faux version!
      e_evt = coalesced_write_evt.ending_event
      if e_evt:
        if e_evt.__class__ == HappyFaceEvent:
          self.happy_face_events.append(e_evt)
        elif e_evt.__class__ == SadFaceEvent:
          self.sad_face_events.append(e_evt)


    def printme(self):
      print 'FauxVersion: %s to %s' % \
            (str(self.start_timestamp), str(self.end_timestamp))
      print '  Last FileWriteEvent:',
      self.get_last_write_event().printme()
      print '  Ended due to', self.coalesced_write_evt.ending_event
      for e in self.webpages_visited:
        print '    Web:   ', e.title.encode('ascii', 'replace')
      for e in sorted(self.other_vim_files_read.keys()):
        print '    VIM read:  ', e
      for e in sorted(self.other_vim_files_edited.keys()):
        print '    VIM edited:', e
      for e in sorted(self.non_vim_files_read.keys()):
        print '    OTHER read:', e

      for e in self.doodle_save_events + self.happy_face_events + self.sad_face_events + self.status_update_events:
        print '   ',
        e.printme()


    def diff(self):
      left_filepath  = self.fvm.checkout_file(self.target_filename, self.start_timestamp)

      # add ONE_SEC so that we can get the effect of the last WRITE that
      # ended this faux version:
      right_filepath = self.fvm.checkout_file(self.target_filename, self.end_timestamp + ONE_SEC)

      EMPTY_FILE = '/tmp/empty'

      # hack: create a fake empty file to diff in case either doesn't exist
      if not os.path.isfile(left_filepath):
        ef = open('/tmp/empty', 'w')
        ef.close()
        left_filepath = EMPTY_FILE

      if not os.path.isfile(right_filepath):
        ef = open('/tmp/empty', 'w')
        ef.close()
        right_filepath = EMPTY_FILE

      # display diff
      if filecmp.cmp(left_filepath, right_filepath):
        str_to_display = 'UNCHANGED'
      else:
        # render 'other' first!
        d = difflib.unified_diff(open(left_filepath, 'U').readlines(),
                                 open(right_filepath, 'U').readlines(),
                                 prettify_filename(self.target_filename),
                                 prettify_filename(self.target_filename),
                                 self.start_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                                 self.end_timestamp.strftime('%Y-%m-%d %H:%M:%S'))

        str_to_display = ''.join([line for line in d])

      return str_to_display


    def render_table_row(self, tbl, row_index):
      XPADDING=8
      YPADDING=15
      # using "yoptions=gtk.SHRINK" in table.attach seems to do the trick
      # in not having the table cells expand vertically like nuts


      # Print source file diffs

      sd = self.start_timestamp.strftime('%Y-%m-%d')
      ed = self.end_timestamp.strftime('%Y-%m-%d')

      st = self.start_timestamp.strftime('%H:%M:%S')
      et = self.end_timestamp.strftime('%H:%M:%S')

      # If the days are the same, then don't duplicate:
      if sd == ed:
        date_str = '%s to %s (%s)' % (st, et, sd)
      else:
        date_str = '%s %s to %s %s' % (sd, st, ed, et)

      date_lab = gtk.Label(date_str)
      date_lab.modify_font(pango.FontDescription("sans 8"))
      date_lab_lalign = create_alignment(date_lab, pbottom=3)

      diff_result_str = self.diff()

      # TODO: adjust height based on existing height of row/column
      text_widget = create_simple_text_view_widget(diff_result_str, 450, 200)


      source_file_vbox = create_vbox([date_lab_lalign, text_widget])
      tbl.attach(source_file_vbox, 0, 1, row_index, row_index+1,
                 xpadding=XPADDING + 5,
                 ypadding=YPADDING,
                 yoptions=gtk.SHRINK)


      # Print co-reads:
      # 1.) webpages visited
      # 2.) other vim files read
      # 3.) other non-vim files read
      co_read_widgets = []

      # TODO: make these labels clickable with pop-up context menus
      for (fn, timestamp) in self.other_vim_files_read.items() + \
                             self.non_vim_files_read.items():
        lab = gtk.Label(prettify_filename(fn))
        lab.modify_font(pango.FontDescription("monospace 9"))
        lab.set_selectable(True)
        lab.show()
        lab_lalign = create_alignment(lab, pbottom=3)
        lab_lalign.show()
        co_read_widgets.append(lab_lalign)


      # de-dup:
      urls_seen = set()

      if self.webpages_visited:
        n = WebpageFeedEvent()
        for w in self.webpages_visited:
          if w.url not in urls_seen:
            urls_seen.add(w.url)
            n.add_webpage_chron_order(w)

        n_lalign = create_alignment(n.get_widget(), ptop=3)
        co_read_widgets.append(n_lalign)


      co_reads_vbox = create_vbox(co_read_widgets)
      co_reads_vbox_lalign = create_alignment(co_reads_vbox)
      tbl.attach(co_reads_vbox_lalign, 1, 2, row_index, row_index+1,
                 xpadding=XPADDING, ypadding=YPADDING,
                 xoptions=gtk.SHRINK, yoptions=gtk.SHRINK)


      # Print co-writes
      # 1.) other vim files edited
      # 2.) doodle events
      # 3.) happy face events
      # 4.) sad face events
      # 5.) status update events
      co_write_widgets = []

      for (fn, timestamp) in self.other_vim_files_edited.iteritems():
        lab = gtk.Label(prettify_filename(fn))
        lab.modify_font(pango.FontDescription("monospace 9"))
        lab.set_selectable(True)
        lab.show()
        lab_lalign = create_alignment(lab)
        lab_lalign.show()
        co_write_widgets.append(lab_lalign)

      all_feed_evts = []

      for e in self.doodle_save_events:
        d = DoodleFeedEvent(e, self.fvm)
        d.load_thumbnail() # subtle but dumb!!!
        all_feed_evts.append(d)

      for e in self.happy_face_events:
        all_feed_evts.append(HappyFaceFeedEvent(e))

      for e in self.sad_face_events:
        all_feed_evts.append(SadFaceFeedEvent(e))

      for e in self.status_update_events:
        all_feed_evts.append(StatusUpdateFeedEvent(e))


      for e in all_feed_evts:
        co_write_widgets.append(e.get_widget())


      co_writes_vbox = create_vbox(co_write_widgets,
                                   [4 for e in co_write_widgets])
      co_writes_vbox_lalign = create_alignment(co_writes_vbox)

      tbl.attach(co_writes_vbox_lalign, 2, 3, row_index, row_index+1,
                 xpadding=XPADDING, ypadding=YPADDING,
                 xoptions=gtk.SHRINK, yoptions=gtk.SHRINK)


      # Print notes (annotations)

      # stick the annotation on the FINAL FileWriteEvent in this faux version:
      annotator = AnnotationComponent(300, self.get_last_write_event(), '<Click to enter a new note>')
      tbl.attach(annotator.get_widget(), 3, 4,
                 row_index, row_index+1,
                 xpadding=XPADDING, ypadding=YPADDING,
                 yoptions=gtk.SHRINK)

      show_all_local_widgets(locals())


  def __init__(self, target_filename, vim_pid, vim_start_time, vim_end_time, fvm):
    self.target_filename = target_filename
    self.vim_pid = vim_pid
    # start and end times of the vim session editing this file
    self.vim_start_time = vim_start_time
    self.vim_end_time   = vim_end_time

    self.fvm = fvm

    # sometimes processes don't have end times, so make up something
    # ridiculous:
    if not self.vim_end_time:
      print >> sys.stderr, "WARNING: VimFileEditSession [PID: %d] has no end time" % vim_pid
      self.vim_end_time = datetime.datetime(3000,1,1)


    # list of WebpageVisitEvent objects
    self.webpage_visit_events = []

    # list of ActiveVimBufferEvent objects where pid == self.vim_pid
    self.vim_active_buffer_events = []

    # list of FileWriteEvent objects where pid == self.vim_pid
    # (includes saves of ALL files, not just target_filename
    self.vim_file_save_events = []

    # list of ActiveGUIWindowEvent objects that DON'T belong to this vim session
    self.other_gui_events = []

    self.doodle_save_events = []   # list of DoodleSaveEvent
    self.happy_face_events = []    # list of HappyFaceEvent
    self.sad_face_events = []      # list of SadFaceEvent
    self.status_update_events = [] # list of StatusUpdateEvent

    # list of FileReadEvent objects where pid != self.vim_pid and filename == target_filename
    # (useful for creating barriers to write coalescing)
    self.other_process_read_events = []


    # list of CoalescedWrite objects
    self.coalesced_writes = []


    self.faux_versions = [] # see _create_faux_versions()


  def within_time_bounds(self, t):
    return self.vim_start_time <= t <= self.vim_end_time


  def add_vim_buffer_event(self, evt):
    if self.within_time_bounds(evt.timestamp) and evt.pid == self.vim_pid:
      self.vim_active_buffer_events.append(evt)

  def add_webpage_visit_event(self, evt):
    if self.within_time_bounds(evt.timestamp):
      self.webpage_visit_events.append(evt)

  def add_file_read_event(self, evt):
    if (self.within_time_bounds(evt.timestamp) and \
        evt.pid != self.vim_pid and
        evt.filename == self.target_filename):
      self.other_process_read_events.append(evt)


  def add_file_save_event(self, evt):
    # hack: ignore files ending in '~' and '*.swp' files,
    # since those are vim temporary backup files
    if (self.within_time_bounds(evt.timestamp) and \
        evt.pid == self.vim_pid and \
        evt.filename[-1] != '~' and \
        not evt.filename.endswith('.swp')):

      # SUPER HACK: if this write event has an annotation, then add an
      # 'annotation' field to it
      optional_note = evt.load_annotation()
      if optional_note:
        evt.annotation = optional_note

      self.vim_file_save_events.append(evt)


  def add_doodle_save_event(self, evt):
    if (self.within_time_bounds(evt.timestamp)):
      self.doodle_save_events.append(evt)

  def add_happy_face_event(self, evt):
    if (self.within_time_bounds(evt.timestamp)):
      self.happy_face_events.append(evt)

  def add_sad_face_event(self, evt):
    if (self.within_time_bounds(evt.timestamp)):
      self.sad_face_events.append(evt)

  def add_status_update_event(self, evt):
    if (self.within_time_bounds(evt.timestamp)):
      self.status_update_events.append(evt)

  def add_other_gui_event(self, evt):
    if not self.within_time_bounds(evt.timestamp):
      return

    if hasattr(evt, 'vim_event') and evt.vim_event.pid == self.vim_pid:
      return

    self.other_gui_events.append(evt)


  def gen_all_sorted_events(self):
    for e in sorted(self.webpage_visit_events + \
                    self.vim_active_buffer_events + \
                    self.vim_file_save_events + \
                    self.other_gui_events + \
                    self.other_process_read_events + \
                    self.doodle_save_events + \
                    self.happy_face_events + \
                    self.sad_face_events + \
                    self.status_update_events + \
                    self.coalesced_writes, key=lambda e:e.timestamp):
      yield e


  def printraw(self):
    print 'VimFileEditSession [PID: %d] %s to %s' % (self.vim_pid, str(self.vim_start_time), str(self.vim_end_time))

    for e in self.gen_all_sorted_events():
      e.printme()
      if e.__class__ == ActiveGUIWindowEvent and hasattr(e, 'vim_event'):
        print ' >',
        e.vim_event.printme()
    print


  def finalize(self):
    self._coalesce_write_events()
    self._create_faux_versions()

  
  # We coalesce writes of target_filename around the following barriers:
  #
  # 1.) READ events of target_filename made by another process
  #     (e.g., executing a script file, compiling a source file,
  #     compiling a LaTex file, etc.)
  # 2.) Any FileWriteEvent with a non-null annotation, since we don't
  #     want to hide annotations from the user in the GUI
  # 3.) HappyFaceEvent and SadFaceEvent, since those are like manual 'commits'
  def _coalesce_write_events(self):
    self.coalesced_writes = []

    # only try to coalesce for target_filename
    target_filename_writes = [e for e in self.vim_file_save_events if e.filename == self.target_filename]

    cur_cw = None
    cur_urls_visited = set()

    # now group together with all events that are possible write
    # barriers, then SORT the whole damn thing ...
    for e in sorted(target_filename_writes + \
                    self.happy_face_events + \
                    self.sad_face_events + \
                    self.other_process_read_events, key=lambda e:e.timestamp):
      if e.__class__ == FileWriteEvent:
        assert e.filename == self.target_filename   # MUY IMPORTANTE!

        if cur_cw:
          cur_cw.add_write_event(e) # coalesce!!!
        else:
          cur_cw = VimFileEditSession.CoalescedWrite(e)

        # if the write event has an annotation, then that's a write
        # barrier, so start a new cur_cw CoalescedWrite right after it
        if hasattr(e, 'annotation'):
          cur_cw.finalize(e)
          self.coalesced_writes.append(cur_cw)
          cur_cw = None # write barrier!

      else:
        # every other kind of event acts as a barrier
        if cur_cw:
          cur_cw.finalize(e)
          self.coalesced_writes.append(cur_cw)
          cur_cw = None # write barrier!
     
    # append on the final entry
    if cur_cw:
      self.coalesced_writes.append(cur_cw)


  # use coalesced write events to create faux 'versions' of
  # target_filename based on editing (and other) actions.
  # these versions will be displayed by the source file
  # provenance viewer GUI
  def _create_faux_versions(self):
    self.faux_versions = []

    for e in sorted(self.coalesced_writes + self.vim_active_buffer_events,
                    key=lambda e:e.timestamp):
      if not self.faux_versions:
        # create the first faux version by looking for the first
        # ActiveVimBufferEvent where target_filename is being edited
        # (or a regular CoalescedWrite entry)
        if e.__class__ == ActiveVimBufferEvent and e.filename == self.target_filename:
          self.faux_versions.append(VimFileEditSession.FauxVersion(self.target_filename, e.timestamp, self.fvm))
        elif e.__class__ == VimFileEditSession.CoalescedWrite:
          self.faux_versions.append(VimFileEditSession.FauxVersion(self.target_filename, e.first_write_timestamp, self.fvm))
      else:
        # creat additional versions split by CoalescedWrite entries
        cur = self.faux_versions[-1]
        if e.__class__ == VimFileEditSession.CoalescedWrite:
          cur.add_ending_event(e)

          self.faux_versions.append(VimFileEditSession.FauxVersion(self.target_filename, e.last_write_timestamp, self.fvm))

    # get rid of the last entry if it's incomplete
    if self.faux_versions and not self.faux_versions[-1].end_timestamp:
      self.faux_versions.pop()

    
    # sanity check:
    for (prev, cur) in zip(self.faux_versions, self.faux_versions[1:]):
      assert prev.start_timestamp <= prev.end_timestamp
      assert prev.end_timestamp <= cur.start_timestamp
      assert cur.start_timestamp <= cur.end_timestamp


    # ok, this is a bit gross, but HappyFaceEvent and SadFaceEvent
    # objects are used as "write barriers" to mark the end of a series
    # of coalesced writes.  if that's the case, then one of those
    # objects is in the ending_event field for that CoalescedWrite event
    # and thus should NOT be re-used in the next FauxVersion ...
    already_used_happy_sad_faces = set()

    # don't double-render doodle files ...
    doodle_filenames = set()

    cur_version = None
    for e in sorted(self.faux_versions + \
                    self.webpage_visit_events + \
                    self.other_gui_events + \
                    self.vim_active_buffer_events + \
                    self.doodle_save_events + \
                    self.happy_face_events + \
                    self.sad_face_events + \
                    self.status_update_events + \
                    self.vim_file_save_events,
                    key=lambda e:e.timestamp):
      if e.__class__ == VimFileEditSession.FauxVersion:
        cur_version = e
        # kludgy!
        already_used_happy_sad_faces.update(cur_version.happy_face_events)
        already_used_happy_sad_faces.update(cur_version.sad_face_events)
      elif cur_version:
        assert cur_version.start_timestamp <= e.timestamp

        # stay within the time range!
        if e.timestamp > cur_version.end_timestamp:
          continue

        elif e.__class__ == WebpageVisitEvent:
          cur_version.webpages_visited.append(e)
        elif e.__class__ == FileWriteEvent:
          if e.filename != self.target_filename:
            # only keep FIRST write timestamp
            if e.filename not in cur_version.other_vim_files_edited:
              cur_version.other_vim_files_edited[e.filename] = e.timestamp
        elif e.__class__ == ActiveVimBufferEvent:
          if e.filename != self.target_filename:
            # only keep FIRST read timestamp
            if e.filename not in cur_version.other_vim_files_read:
              cur_version.other_vim_files_read[e.filename] = e.timestamp

        elif e.__class__ == ActiveGUIWindowEvent:
          if hasattr(e, 'files_read_set'):
            for fr in e.files_read_set:
              if fr not in cur_version.non_vim_files_read:
                if fr not in doodle_filenames:
                  cur_version.non_vim_files_read[fr] = e.timestamp


        elif e.__class__ == StatusUpdateEvent:
          cur_version.status_update_events.append(e)
        elif e.__class__ == DoodleSaveEvent:
          cur_version.doodle_save_events.append(e)
          doodle_filenames.add(e.filename)
        elif e.__class__ == HappyFaceEvent:
          if e not in already_used_happy_sad_faces:
            cur_version.happy_face_events.append(e)
        elif e.__class__ == SadFaceEvent:
          if e not in already_used_happy_sad_faces:
            cur_version.sad_face_events.append(e)
        else:
          assert False, e


    for fv in self.faux_versions:
      # to eliminate redundancies, remove all entries from
      # other_vim_files_read if they're in other_vim_files_edited
      for f in fv.other_vim_files_edited:
        if f in fv.other_vim_files_read:
          del fv.other_vim_files_read[f]


class SourceFileProvViewer():
  def __init__(self, target_filename, session_tag, fvm):
    self.fvm = fvm
    self.session_tag = session_tag
    self.target_filename = target_filename

    # MongoDB stuff
    c = Connection()
    self.db = c.burrito_db

    all_events = []

    # Get GUI events
    for m in self.db.gui_trace.find({"session_tag": session_tag}):
      web_visit_evt = fetch_webpage_visit_event(m)
      if web_visit_evt:
        all_events.append(web_visit_evt)
      else:
        gui_evt = fetch_active_gui_window_event(m)
        if gui_evt:
          all_events.append(gui_evt)


    # Get file read/write events

    # Key:   child PID
    # Value: parent PID
    #
    # TODO: assumes that there is no recycling of PIDs, which should be an
    # okay assumption if we're operating within one session but needs to be
    # revised when we're querying over multiple sessions
    pid_parents = {}

    # Key:   PID
    # Value: process creation/exit time
    pid_creation_times = {}
    pid_exit_times = {}

    def get_pid_and_parents(pid):
      ret = [pid]
      try:
        parent = pid_parents[pid]
        while True:
          ret.append(parent)
          parent = pid_parents[parent]
      except KeyError:
        return ret

    for m in self.db.process_trace.find({"session_tag": session_tag},
                                        {'pid':1, 'ppid':1, 'uid':1, 'phases':1,
                                         'creation_time':1, 'exit_time':1}):
      pid_creation_times[m['pid']] = m['creation_time']
      pid_exit_times[m['pid']] = m['exit_time']
      pid_parents[m['pid']] = m['ppid']

      prov_evts = fetch_file_prov_event_lst(m, session_tag)
      all_events.extend(prov_evts)


    # Get VIM edit events
    for m in self.db.apps.vim.find({"session_tag": session_tag}):
      vim_evt = fetch_active_vim_buffer_event(m)
      if vim_evt:
        all_events.append(vim_evt)

    
    # Get HappyFaceEvent, SadFaceEvent, and StatusUpdateEvent events
    all_events.extend(fetch_toplevel_annotation_events(session_tag))


    # Key: PID
    # Value: set of files read by this process or by one of its children
    pid_to_read_files = defaultdict(set)

    # Key: PID
    # Value: VimFileEditSession
    # (each VimFileEditSession has a list of faux_versions)
    self.vim_sessions = {}

    # les means "latest edit session":
    # we are associating all events with the most recently-active vim session
    # (which is a reasonable simplifying assumption)
    les = None

    # massive chronological sort!
    all_events.sort(key=lambda e:e.timestamp)

    for (ind, e) in enumerate(all_events):
      if e.__class__ == FileReadEvent:
        # We want to associate GUI windows with files read by the application
        # that controls each window.  For example, we want to associate an
        # ActiveGUIWindowEvent for the OpenOffice Calc app with some *.xls
        # spreadsheet file that the app is currently editing.
        #
        # incrementally build up this set in chronological order,
        #
        # and for simplicity, just have a whitelist of document extensions
        # that we're looking for:
        if document_extension_whitelisted(e.filename):
          for p in get_pid_and_parents(e.pid):
            pid_to_read_files[p].add(e.filename)

        if les: les.add_file_read_event(e)
      elif e.__class__ == FileWriteEvent:
        if les: les.add_file_save_event(e)
      elif e.__class__ == WebpageVisitEvent:
        if les: les.add_webpage_visit_event(e)
      elif e.__class__ == ActiveGUIWindowEvent:
        # Now associate each ActiveGUIWindowEvent with the ActiveVimBufferEvent
        # directly preceeding it if ...
        #   ActiveVimBufferEvent.pid is a parent of ActiveVimBufferEvent.pid
        #
        # This forms a bond between an ActiveGUIWindowEvent and VIM by adding
        # a vim_event field to ActiveGUIWindowEvent
        #
        # go backwards ...
        for vim_event in reversed(all_events[:ind]):
          if vim_event.__class__ == ActiveVimBufferEvent:
            # the vim process will probably be a child of 'bash', which is
            # itself a child of 'gnome-terminal' (or whatever terminal app
            # controls the GUI window), so we need to match on parent
            # processes all the way up the chain
            candidate_pids = get_pid_and_parents(vim_event.pid)
            if e.active_app_pid in candidate_pids:
              e.vim_event = vim_event # establish a link
              break
        
        
        if not hasattr(e, 'vim_event'):
          # if this process of any of its children have read files, then add
          # the set of files as a new field called files_read_set
          if e.active_app_pid in pid_to_read_files:
            e.files_read_set = pid_to_read_files[e.active_app_pid]

        if les: les.add_other_gui_event(e)

      elif e.__class__ == ActiveVimBufferEvent:
        if e.pid not in self.vim_sessions:
          n = VimFileEditSession(self.target_filename, e.pid, pid_creation_times[e.pid], pid_exit_times[e.pid], self.fvm)
          self.vim_sessions[e.pid] = n

        les = self.vim_sessions[e.pid]

        # unconditionally add!
        les.add_vim_buffer_event(e)

      elif e.__class__ == DoodleSaveEvent:
        if les: les.add_doodle_save_event(e)
      elif e.__class__ == HappyFaceEvent:
        if les: les.add_happy_face_event(e)
      elif e.__class__ == SadFaceEvent:
        if les: les.add_sad_face_event(e)
      elif e.__class__ == StatusUpdateEvent:
        if les: les.add_status_update_event(e)
      else:
        assert False, e


    # SUPER important to finalize!
    for e in self.vim_sessions.values():
      e.finalize()


    self.all_faux_versions = []
    for e in self.vim_sessions.values():
      self.all_faux_versions.extend(e.faux_versions)

    # reverse chronological order
    self.all_faux_versions.sort(key=lambda e:e.timestamp, reverse=True)


    '''
    for e in sorted(self.vim_sessions.values(), key=lambda e:e.vim_start_time):
      e.printraw()
      print '---'
      for fv in e.faux_versions:
        fv.printme()
      print
    '''


    # ok, now time for the GUI part!
    self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
    self.window.set_title("Source file provenance viewer")
    self.window.set_border_width(0)
    set_white_background(self.window)

    self.window.resize(500, 500)
    self.window.maximize()


    tbl = gtk.Table(rows=len(self.all_faux_versions) + 1, columns=4)
    tbl_scroller = gtk.ScrolledWindow()
    tbl_scroller.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
    tbl_scroller.add_with_viewport(tbl)
    set_white_background(tbl_scroller.get_children()[0])

    self.window.add(tbl_scroller)

    # header row
    col1_label = gtk.Label(prettify_filename(self.target_filename))
    col1_label.modify_font(pango.FontDescription("sans 12"))
    col2_label = gtk.Label("Co-reads")
    col2_label.modify_font(pango.FontDescription("sans 12"))
    col3_label = gtk.Label("Co-writes")
    col3_label.modify_font(pango.FontDescription("sans 12"))
    col4_label = gtk.Label("Notes")
    col4_label_lalign = create_alignment(col4_label, pleft=15)
    col4_label.modify_font(pango.FontDescription("sans 12"))
    tbl.attach(col1_label, 0, 1, 0, 1, ypadding=8)
    tbl.attach(col2_label, 1, 2, 0, 1, ypadding=8)
    tbl.attach(col3_label, 2, 3, 0, 1, ypadding=8)
    tbl.attach(col4_label_lalign, 3, 4, 0, 1, ypadding=8)


    # show the window and all widgets first!!!
    show_all_local_widgets(locals())
    self.window.show()


    row_index = 1

    for fv in self.all_faux_versions:
      # ... then use this trick to update the GUI between each loop
      # iteration, since each iteration takes a second or two
      # (this will make the GUI seem more responsive, heh)
      #
      #   http://faq.pygtk.org/index.py?req=show&file=faq03.007.htp
      while gtk.events_pending(): gtk.main_iteration(False)

      print >> sys.stderr, "SourceFileProvViewer rendering row", \
               row_index, "of", len(self.all_faux_versions)

      fv.render_table_row(tbl, row_index)
      row_index += 1

      # stent!
      #if row_index > 20: break


def exit_handler():
  global fvm
  fvm.memoize_checkpoints()
  fvm.unmount_all_snapshots()


if __name__ == '__main__':
  atexit.register(exit_handler)
  signal(SIGTERM, lambda signum,frame: exit(1)) # trigger the atexit function to run

  fvm = FileVersionManager()
  target_filename = sys.argv[1]
  session_tag = sys.argv[2]
  SourceFileProvViewer(target_filename, session_tag, fvm)
  gtk.main()

