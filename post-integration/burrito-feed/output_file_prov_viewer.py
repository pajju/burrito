# Output file provenance viewer, showing a tabular view where each row consists of:
#
# 1.) Input code files (diffs from baseline)
# 2.) Command parameters
# 3.) Output file
# 4.) Annotations


# TODO: support filtering by a time range rather than just a session tag


import pygtk
pygtk.require('2.0')
import gtk, pango, gobject

import os, sys
import datetime
import filecmp
import difflib
import mimetypes

import cgi

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

import source_file_prov_viewer
import burrito_feed


# KLUDGY GLOBAL :(
diff_left_half = None
diff_menu_items = [] # really kludgy!


# Represents a command invocation that involves reading some input files
# and writing ONE particular output file.
# (Note that the command might write additional output files, but for
# the purposes of the file provenance viewer, we are only focused on ONE
# output file.)
class CommandInvocation:
  def __init__(self, cmd_event, read_event_lst, output_event, sorted_write_events_lst, fvm, session_tag):
    self.cmd_event = cmd_event           # type: BashCommandEvent
    self.read_event_lst = read_event_lst # type: list of FileReadEvent
    self.output_event = output_event     # type: FileWriteEvent
    self.fvm = fvm                       # type: FileVersionManager
    self.sorted_write_events_lst = sorted_write_events_lst # type: list of FileWriteEvent
    self.session_tag = session_tag


  def get_output_filename(self):
    return self.output_event.filename

  def get_timestamp(self):
    return self.cmd_event.timestamp

  def view_file_version(self, _ignore, read_evt):
    # gnome-open to the rescue!!!  uses a file's type to determine the
    # proper viewer application :)
    old_version_path = self.fvm.checkout_file(read_evt.filename, read_evt.timestamp)
    if not os.path.isfile(old_version_path):
      d = gtk.MessageDialog(None,
                            gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                            gtk.MESSAGE_ERROR,
                            gtk.BUTTONS_OK,
                            message_format="File not found:\n" + old_version_path)
      d.run()
      d.destroy()
    else:
      os.system('gnome-open "%s" &' % old_version_path)


  def mark_for_diff(self, _ignore, read_evt):
    global diff_left_half, diff_menu_items
    if not diff_left_half:
      diff_left_half = read_evt

      for e in diff_menu_items:
        e.set_label('Diff against selected file')
    else:
      diff_left_half_path = self.fvm.checkout_file(diff_left_half.filename,
                                                   diff_left_half.timestamp)
      diff_right_half_path = self.fvm.checkout_file(read_evt.filename,
                                                    read_evt.timestamp)

      os.system('meld "%s" "%s" &' % (diff_left_half_path, diff_right_half_path))

      # reset!
      diff_left_half = None
      for e in diff_menu_items:
        e.set_label('Select for diff')


  def view_source_prov(self, _ignore, read_evt):
    spv = source_file_prov_viewer.SourceFileProvViewer(read_evt.filename,
                                                       self.session_tag,
                                                       self.fvm)


  # returns a string representing the diff of all input files
  # (the Python HTML diff option looks really ugly, so don't use it!)
  def diff_input_files(self, other):
    unchanged_files = []

    diff_result = []

    for cur_re in self.read_event_lst:
      cur_filepath = self.fvm.checkout_file(cur_re.filename, cur_re.timestamp)

      for other_re in other.read_event_lst:
        if other_re.filename == cur_re.filename:
          other_filepath = self.fvm.checkout_file(other_re.filename, other_re.timestamp)

          if filecmp.cmp(cur_filepath, other_filepath):
            unchanged_files.append(cur_re.filename)

          else:
            # there's a diff, so print if possible

            # render 'other' first!
            d = difflib.unified_diff(open(other_filepath, 'U').readlines(),
                                     open(cur_filepath, 'U').readlines(),
                                     prettify_filename(other_re.filename),
                                     prettify_filename(cur_re.filename),
                                     other_re.timestamp,
                                     cur_re.timestamp)
            diff_result.extend([line for line in d])

          break # break after first match


    # tack all unchanged files on at the end
    for e in unchanged_files:
      diff_result.append('\nUNCHANGED: ' + prettify_filename(e))

    diff_result_str = ''.join(diff_result) # each line already has trailing '\n'
    return diff_result_str


  def diff_output_file(self, cur_output_filepath, other):
    other_output_filepath = self.fvm.checkout_file_before_next_write(other.output_event,
                                                                     other.sorted_write_events_lst)

    # display diff
    if filecmp.cmp(cur_output_filepath, other_output_filepath):
      str_to_display = 'UNCHANGED'
    else:
      # render 'other' first!
      d = difflib.unified_diff(open(other_output_filepath, 'U').readlines(),
                               open(cur_output_filepath, 'U').readlines(),
                               prettify_filename(self.get_output_filename()),
                               prettify_filename(self.get_output_filename()),
                               other.get_timestamp(),
                               self.get_timestamp())

      str_to_display = ''.join([line for line in d])

    return str_to_display


  def render_table_row(self, prev_cmd_invocation, tbl, row_index):
    XPADDING=8
    YPADDING=15
    # using "yoptions=gtk.SHRINK" in table.attach seems to do the trick
    # in not having the table cells expand vertically like nuts

    # Print inputs:

    widgets = []

    for re in self.read_event_lst:
      lab = gtk.Label(prettify_filename(re.filename))
      lab.modify_font(pango.FontDescription("monospace 9"))
      lab.show()

      menu = gtk.Menu()

      view_item = gtk.MenuItem('Open')
      view_item.connect("activate", self.view_file_version, re)
      view_item.show()
      mark_diff_item = gtk.MenuItem('Select for diff')
      mark_diff_item.connect("activate", self.mark_for_diff, re)
      mark_diff_item.show()
      prov_item = gtk.MenuItem('View source file provenance')
      prov_item.connect("activate", self.view_source_prov, re)
      prov_item.show()
      menu.append(view_item)
      menu.append(mark_diff_item)
      menu.append(prov_item)

      global diff_menu_items
      diff_menu_items.append(mark_diff_item)

      lab_box = create_clickable_event_box(lab, menu)
      lab_box.show()

      lab_align = create_alignment(lab_box, pbottom=5)
      lab_align.show()
      widgets.append(lab_align)

    if prev_cmd_invocation:
      diff_result_str = self.diff_input_files(prev_cmd_invocation)

      # TODO: adjust height based on existing height of row/column
      text_widget = create_simple_text_view_widget(diff_result_str, 400, 200)
      #text_widget = create_simple_text_view_widget(diff_result_str, 500, 300)

      widgets.append(text_widget)

    input_vbox = create_vbox(widgets)
    tbl.attach(input_vbox, 0, 1, row_index, row_index+1,
               xpadding=XPADDING + 5,
               ypadding=YPADDING,
               yoptions=gtk.SHRINK)
   

    # Print command:

    # cool that we get to re-use BashFeedEvent objects
    n = burrito_feed.BashFeedEvent(self.cmd_event.pwd)
    n.add_command_chron_order(self.cmd_event)

    # make it not expand like crazy in either the horizontal or vertical directions
    tbl.attach(n.get_widget(), 1, 2, row_index, row_index+1, xpadding=XPADDING, ypadding=YPADDING,
               xoptions=gtk.SHRINK, yoptions=gtk.SHRINK)

    # Print output:
    mime_type_guess = mimetypes.guess_type(self.get_output_filename())[0]

    cur_output_filepath = self.fvm.checkout_file_before_next_write(self.output_event,
                                                                   self.sorted_write_events_lst)

    if 'image/' in mime_type_guess:
      output_image = gtk.Image()
      output_image.set_from_file(cur_output_filepath)
      tbl.attach(output_image, 2, 3, row_index, row_index+1, xpadding=XPADDING, ypadding=YPADDING, yoptions=gtk.SHRINK)

    elif 'text/' in mime_type_guess:
      if prev_cmd_invocation:
        str_to_display = self.diff_output_file(cur_output_filepath, prev_cmd_invocation)
      else:
        # display entire file contents:
        str_to_display = open(cur_output_filepath, 'U').read()

      text_widget = create_simple_text_view_widget(str_to_display, 500, 350)
      tbl.attach(text_widget, 2, 3, row_index, row_index+1, xpadding=XPADDING, ypadding=YPADDING, yoptions=gtk.SHRINK)


    # Print annotations associated with self.output_event:
    annotator = AnnotationComponent(300, self.output_event, '<Click to enter a new note>')
    tbl.attach(annotator.get_widget(), 3, 4, row_index, row_index+1, xpadding=XPADDING, ypadding=YPADDING, yoptions=gtk.SHRINK)

    show_all_local_widgets(locals())


  def render_table_row_HTML(self, prev_cmd_invocation, fd):
    print >> fd, '<tr>'
  

    # Print input diffs
    print >> fd, '<td>'

    if prev_cmd_invocation:
      print >> fd, '<pre>'
      print >> fd, self.diff_input_files(prev_cmd_invocation)
      print >> fd, '</pre>'
    else:
      print >> fd, "<p>Initial version:</p>"
      print >> fd, '<pre>'
      for re in self.read_event_lst:
        print >> fd, prettify_filename(re.filename)
      print >> fd, '</pre>'

    print >> fd, '</td>'


    # Print command
    print >> fd, '<td>'

    print >> fd, '<pre>'
    print >> fd, self.cmd_event.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    print >> fd, prettify_filename(self.cmd_event.pwd)
    print >> fd
    print >> fd, ' '.join(self.cmd_event.cmd)
    print >> fd, '</pre>'

    print >> fd, '</td>'

    
    # Print output:
    print >> fd, '<td>'

    mime_type_guess = mimetypes.guess_type(self.get_output_filename())[0]

    cur_output_filepath = self.fvm.checkout_file_before_next_write(self.output_event,
                                                                   self.sorted_write_events_lst)

    if 'image/' in mime_type_guess:
      print >> fd, '<img src="%s"/>' % cur_output_filepath
    elif 'text/' in mime_type_guess:
      if prev_cmd_invocation:
        str_to_display = self.diff_output_file(cur_output_filepath, prev_cmd_invocation)
      else:
        # display entire file contents:
        str_to_display = open(cur_output_filepath, 'U').read()

      print >> fd, '<pre>'
      print >> fd, str_to_display
      print >> fd, '</pre>'


    print >> fd, '</td>'

 
    # Print notes:
    print >> fd, '<td>'
    print >> fd, cgi.escape(self.output_event.load_annotation()).replace('\n', '<br/>')
    print >> fd, '</td>'

    print >> fd, '</tr>'


class OutputFileProvViewer():
  def __init__(self, target_output_filename, session_tag, fvm):
    self.target_output_filename = target_output_filename
    self.session_tag = session_tag
    self.fvm = fvm

    self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
    #self.window.connect("destroy", lambda w: gtk.main_quit())

    self.window.set_title("Output file provenance viewer")
    self.window.set_border_width(0)
    set_white_background(self.window)

    self.window.resize(500, 500)
    self.window.maximize()

    # MongoDB stuff
    c = Connection()
    self.db = c.burrito_db
    db_proc_collection = self.db.process_trace
    db_bash_collection = self.db.apps.bash


    bash_events = []
    # chronological order:
    for m in db_bash_collection.find({'session_tag': session_tag}).sort('_id'):
      evt = fetch_bash_command_event(m)
      if evt:
        bash_events.append(evt)


    # fetch file provenance events

    file_prov_events = []

    for m in db_proc_collection.find({"session_tag": session_tag},
                                     {'pid':1, 'uid':1, 'phases':1}):
      evts = fetch_file_prov_event_lst(m, session_tag)
      file_prov_events.extend(evts)


    # Key: PID
    # Value: list of FileProvenanceEvent instances
    file_evts_by_pid = defaultdict(list)

    for evt in file_prov_events:
      file_evts_by_pid[evt.pid].append(evt)


    target_file_write_events = []
    for evt in file_prov_events:
      if (evt.__class__ == FileWriteEvent and \
          evt.filename == self.target_output_filename):
        target_file_write_events.append(evt)

    target_file_write_events.sort(key=lambda e:e.timestamp)

    cmd_invocation_lst = []

    for evt in target_file_write_events:
      sorted_evts = sorted(file_evts_by_pid[evt.pid], key=lambda e:e.timestamp)

      earliest_timestamp_from_pid = sorted_evts[0].timestamp

      # don't insert duplicates in file_read_events, so in essence we're
      # grabbing the FIRST read out of a series ...
      filenames_read_set = set()
      file_read_events = []

      # find files read by the corresponding process
      for e in sorted_evts:
        if e.__class__ == FileReadEvent and e.filename not in filenames_read_set:
          file_read_events.append(e)
          filenames_read_set.add(e.filename)


      # Use a time- and name-based heuristic for finding the proper bash
      # command that led to the current process.
      #
      # TODO: in the future, we can match the parent pid (ppid) of evt's
      # process to bash_pid, but we STILL can't avoid using a time-based
      # heuristic.
      bash_evts_preceeding_pid = []
      for bash_evt in bash_events:
        if bash_evt.timestamp > earliest_timestamp_from_pid:
          break
        bash_evts_preceeding_pid.append(bash_evt)

      # for now, naively assume that the most recent event preceeding
      # earliest_timestamp_from_pid is the one we want, without regards
      # for its actual name.  In the future, use evt.phase_name to try
      # to disambiguate.
      my_bash_cmd = bash_evts_preceeding_pid[-1]

      n = CommandInvocation(my_bash_cmd, file_read_events, evt, target_file_write_events, self.fvm, self.session_tag)
      cmd_invocation_lst.append(n)


    tbl = gtk.Table(rows=len(cmd_invocation_lst) + 1, columns=4)
    tbl_scroller = gtk.ScrolledWindow()
    tbl_scroller.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
    tbl_scroller.add_with_viewport(tbl)
    set_white_background(tbl_scroller.get_children()[0])

    self.window.add(tbl_scroller)

    # header row
    col1_label = gtk.Label("Inputs")
    col1_label.modify_font(pango.FontDescription("sans 12"))
    col2_label = gtk.Label("Command")
    col2_label.modify_font(pango.FontDescription("sans 12"))
    col3_label = gtk.Label("Output: " + prettify_filename(self.target_output_filename))
    col3_label.modify_font(pango.FontDescription("sans 12"))
    col4_label = gtk.Label("Notes")
    col4_label.modify_font(pango.FontDescription("sans 12"))
    tbl.attach(col1_label, 0, 1, 0, 1, ypadding=8)
    tbl.attach(col2_label, 1, 2, 0, 1, ypadding=8)
    tbl.attach(col3_label, 2, 3, 0, 1, ypadding=8)
    tbl.attach(col4_label, 3, 4, 0, 1, ypadding=8)

    # sort in reverse chronological order:
    cmd_invocation_lst.sort(key=lambda e:e.get_timestamp(), reverse=True)

    # show the window and all widgets first!!!
    show_all_local_widgets(locals())
    self.window.show()

    row_index = 1
    for (cur, prev) in zip(cmd_invocation_lst, cmd_invocation_lst[1:]):
      # ... then use this trick to update the GUI between each loop
      # iteration, since each iteration takes a second or two
      # (this will make the GUI seem more responsive, heh)
      #
      #   http://faq.pygtk.org/index.py?req=show&file=faq03.007.htp
      while gtk.events_pending(): gtk.main_iteration(False)

      print >> sys.stderr, "OutputFileProvViewer rendering row", row_index, "of", len(cmd_invocation_lst)
      cur.render_table_row(prev, tbl, row_index)

      row_index += 1


    while gtk.events_pending(): gtk.main_iteration(False)
    print >> sys.stderr, "OutputFileProvViewer rendering row", row_index, "of", len(cmd_invocation_lst)
    cmd_invocation_lst[-1].render_table_row(None, tbl, row_index) # print baseline (FIRST ENTRY)


    # TODO: make this experimental HTML export mode into an event
    # handler triggered by some button or menu selection:
    ''' 
    fd = open('/tmp/output_prov.html', 'w')
    self.print_html_header(fd)


    chronological_cmd_list = cmd_invocation_lst[::-1]

    row_index = 1
    print >> sys.stderr, "OutputFileProvViewer rendering HTML row", row_index, "of", len(chronological_cmd_list)
    chronological_cmd_list[0].render_table_row_HTML(None, fd)

    for (prev, cur) in zip(chronological_cmd_list, chronological_cmd_list[1:]):
      row_index += 1
      print >> sys.stderr, "OutputFileProvViewer rendering HTML row", row_index, "of", len(chronological_cmd_list)
      cur.render_table_row_HTML(prev, fd)

    self.print_html_footer(fd)

    fd.close()
    os.system('cp output_prov_viewer.css /tmp/ && gnome-open "/tmp/output_prov.html" &')
    ''' 


  def print_html_header(self, fd):
    print >> fd, '<html><head>'
    print >> fd, '<title>%s</title>' % "Output file provenance viewer"
    print >> fd, '<link rel="stylesheet" href="output_prov_viewer.css"/>'

    print >> fd, '</head><body>'
    print >> fd, '<h1>Output file provenance viewer</h1>'
    print >> fd, '<h2>Filename: %s</h2>' % prettify_filename(self.target_output_filename)
    print >> fd, '<table>'

    print >> fd, '<tr>'
    print >> fd, '<td class="header">Inputs</td>'
    print >> fd, '<td class="header">Command</td>'
    print >> fd, '<td class="header">Output file</td>'
    print >> fd, '<td class="header">Notes</td>'
    print >> fd, '</tr>'

  def print_html_footer(self, fd):
    print >> fd, '</table>'
    print >> fd, '</body></html>'



def exit_handler():
  global fvm
  fvm.memoize_checkpoints()
  fvm.unmount_all_snapshots()


if __name__ == '__main__':
  atexit.register(exit_handler)
  signal(SIGTERM, lambda signum,frame: exit(1)) # trigger the atexit function to run

  fvm = FileVersionManager()
  filename = sys.argv[1]
  session_tag = sys.argv[2]
  OutputFileProvViewer(filename, session_tag, fvm)
  gtk.main()

