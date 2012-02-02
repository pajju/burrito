# Created on 2011-12-08
# implement a (near)real-time feed of user activities, sorta like a
# Facebook Feed or Twitter stream


import pygtk
pygtk.require('2.0')
import gtk, pango, gobject

import os, sys, gc
import datetime
import filecmp

import atexit
from signal import signal, SIGTERM

from pymongo import Connection, ASCENDING, DESCENDING

from pygtk_burrito_utils import *

from BurritoUtils import *
from urlparse import urlparse

from annotation_component import AnnotationComponent
from event_fetcher import *

import source_file_prov_viewer, output_file_prov_viewer

from file_version_manager import FileVersionManager, ONE_SEC


WINDOW_WIDTH = 300

FIVE_SECS = datetime.timedelta(seconds=5)


# use the primary X Window clipboard ...
g_clipboard = gtk.Clipboard(selection="PRIMARY")


# Ugh, kludgy globals ... relies on the fact that BurritoFeed is a
# singleton here ... will break down if this isn't the case :)

diff_left_half = None # type: FileFeedEvent.FileEventDisplay
diff_menu_items = []


# Key:   filename
# Value: FileEventDisplay object which is the baseline version to watch for changes
watch_files = {}

# Key: filename
# Value: timestamp of most recent read to this file
file_read_timestamps = {}

# each elt is a FileWriteEvent instance
# Key:   filename
# Value: list of FileWriteEvent instances in sorted order
sorted_write_events = {}


# http://stackoverflow.com/questions/69645/take-a-screenshot-via-a-python-script-linux
def save_screenshot(output_filename):
  assert output_filename.endswith('.png')
  w = gtk.gdk.get_default_root_window()
  sz = w.get_size()
  pb = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB,False,8,sz[0],sz[1])
  pb = pb.get_from_drawable(w,w.get_colormap(),0,0,0,0,sz[0],sz[1])
  if (pb != None):
    pb.save(output_filename, 'png')
    # To prevent a gross memory leak:
    # http://faq.pygtk.org/index.py?req=show&file=faq08.004.htp
    del pb
    gc.collect()
  else:
    print >> sys.stderr, "Failed to save screenshot to", output_filename


# Code taken from: http://stackoverflow.com/questions/1551382/python-user-friendly-time-format
def pretty_date(time=False):
    """
    Get a datetime object or a int() Epoch timestamp and return a
    pretty string like 'an hour ago', 'Yesterday', '3 months ago',
    'just now', etc
    """
    from datetime import datetime
    now = datetime.now()
    if type(time) in (int, long):
        diff = now - datetime.fromtimestamp(time)
    elif isinstance(time,datetime):
        diff = now - time 
    elif not time:
        diff = now - now
    else:
        assert False, time
    second_diff = diff.seconds
    day_diff = diff.days

    if day_diff < 0:
        return ''

    if day_diff == 0:
        if second_diff < 10:
            return "just now"
        if second_diff < 60:
            return str(second_diff) + " seconds ago"
        if second_diff < 120:
            return  "a minute ago"
        if second_diff < 3600:
            return str( second_diff / 60 ) + " minutes ago"
        if second_diff < 7200:
            return "an hour ago"
        if second_diff < 86400:
            return str( second_diff / 3600 ) + " hours ago"
    if day_diff == 1:
        return "Yesterday"
    if day_diff < 7:
        return str(day_diff) + " days ago"
    if day_diff < 31:
        return str(day_diff/7) + " weeks ago"
    if day_diff < 365:
        return str(day_diff/30) + " months ago"
    return str(day_diff/365) + " years ago"


# iterates in reverse over a list of FeedEvent instances and terminates
# either when the list ends or when an element's timestamp is older
# than target_time 
def gen_reverse_bounded_time_elts(lst, target_time):
  for e in reversed(lst):
    if e.timestamp < target_time:
      return
    yield e


class FeedEvent:
  PANGO_TIMESTAMP_TEMPLATE = '<span font_family="sans" size="8000" foreground="#999999">%s</span>'

  def __init__(self, dt, icon_filename):
    self.timestamp = dt # type datetime.datetime

    event_icon = gtk.Image()
    event_icon.set_from_file(icon_filename)

    # start empty
    timestamp_lalign = gtk.Alignment(0, 0.6, 0, 0)
    timestamp_lab = gtk.Label()
    timestamp_lalign.add(timestamp_lab)

    event_header = create_hbox((event_icon, timestamp_lalign), (0, 5))

    show_all_local_widgets(locals())
    self.timestamp_label = timestamp_lab
    self.header = event_header


  def get_widget(self):
    return self.widget

  def update_timestamp(self):
    self.timestamp_label.set_markup(FeedEvent.PANGO_TIMESTAMP_TEMPLATE % pretty_date(self.timestamp))


# represents a user-posted comment
class CommentFeedEvent(FeedEvent):
  def __init__(self, comment, dt, icon_filename, screenshot_filename=None):
    FeedEvent.__init__(self, dt, icon_filename)
    self.comment = comment

    context_menu = gtk.Menu()
    copy_item = gtk.MenuItem('Copy comment')
    copy_item.connect("activate", self.copy_comment)
    hashtag_item = gtk.MenuItem('Copy event hashtag')
    hashtag_item.connect("activate", self.copy_event_hashtag)
    context_menu.append(copy_item)
    context_menu.append(hashtag_item)

    lab = gtk.Label(self.comment)
    lab.modify_font(pango.FontDescription("sans 9"))
    lab.set_line_wrap(True) # turn on word-wrapping!
    lab.set_size_request(WINDOW_WIDTH - 35, -1) # request a reasonable initial width
    lab_box = create_clickable_event_box(lab, context_menu)
    comment_event_body = create_alignment(lab_box)

    comment_vbox = gtk.VBox()
    comment_vbox.pack_start(self.header)

    if screenshot_filename:
      screenshot_link = gtk.Label()
      screenshot_link.set_markup('<span font_family="sans" size="9000"><a href="file://%s">View screenshot</a></span>' % screenshot_filename)
      screenshot_lalign = create_alignment(screenshot_link, ptop=3)
      comment_vbox.pack_start(screenshot_lalign)

    comment_vbox.pack_start(comment_event_body, padding=5)

    show_all_local_widgets(locals())
    self.widget = comment_vbox
    self.update_timestamp()

  def save_to_db(self):
    self.event.save_to_db() # polymorphic!

  def copy_comment(self, _ignore):
    g_clipboard.set_text(self.comment)

  def copy_event_hashtag(self, _ignore):
    g_clipboard.set_text(self.event.get_hashtag())


class StatusUpdateFeedEvent(CommentFeedEvent):
  def __init__(self, status_update_event):
    self.event = status_update_event
    CommentFeedEvent.__init__(self, self.event.annotation,
                                    self.event.timestamp,
                                    "accessories-text-editor-24x24.png")

class HappyFaceFeedEvent(CommentFeedEvent):
  def __init__(self, happy_face_event):
    self.event = happy_face_event
    CommentFeedEvent.__init__(self, self.event.annotation,
                                    self.event.timestamp,
                                    "yellow-happy-face-24x24-antialiased.xpm",
                                    self.event.screenshot_filename)

class SadFaceFeedEvent(CommentFeedEvent):
  def __init__(self, sad_face_event):
    self.event = sad_face_event
    CommentFeedEvent.__init__(self, self.event.annotation,
                                    self.event.timestamp,
                                    "red-sad-face-24x24-antialiased.xpm",
                                    self.event.screenshot_filename)


# represents a BASH shell event object in the feed
class BashFeedEvent(FeedEvent):

  class BashCommandDisplay:
    def __init__(self, bash_cmd_event):
      self.bash_cmd_event = bash_cmd_event # BashCommandEvent instance
      self.cmd_str = ' '.join(bash_cmd_event.cmd)
      self.annotator = AnnotationComponent(WINDOW_WIDTH-50, bash_cmd_event)


      command_context_menu = gtk.Menu()
      cc_item1 = gtk.MenuItem('Copy command')
      cc_item1.connect("activate", self.copy_cmd)
      cc_item2 = gtk.MenuItem('Copy event hashtag')
      cc_item2.connect("activate", self.copy_event_hashtag)
      add_comment_item = gtk.MenuItem('Annotate invocation')
      add_comment_item.connect("activate", self.annotator.show_comment_box)

      command_context_menu.append(cc_item1)
      command_context_menu.append(cc_item2)
      command_context_menu.append(add_comment_item)

      cmd_label = gtk.Label(self.cmd_str)
      cmd_label.modify_font(pango.FontDescription("monospace 8"))
      cmd_label_box = create_clickable_event_box(cmd_label, command_context_menu)
      cmd_label_box.set_has_tooltip(True)
      cmd_label_box.connect('query-tooltip', show_tooltip, self.cmd_str)

      cmd_lalign = create_alignment(cmd_label_box, ptop=2, pbottom=2, pleft=2)

      cmd_vbox = create_vbox((cmd_lalign, self.annotator.get_widget()))

      show_all_local_widgets(locals())
      self.widget = cmd_vbox


    def copy_cmd(self, _ignore):
      g_clipboard.set_text(self.cmd_str)

    def copy_event_hashtag(self, _ignore):
      g_clipboard.set_text(self.bash_cmd_event.get_hashtag())

    def get_widget(self):
      return self.widget


  def copy_pwd(self, _ignore):
    g_clipboard.set_text('cd ' + self.pwd)

  def __init__(self, pwd):
    FeedEvent.__init__(self, None, "terminal-24x24-icon.png")
    self.pwd = pwd

    def create_pwd_popup_menu():
      menu = gtk.Menu()
      item = gtk.MenuItem('Copy directory')
      item.connect("activate", self.copy_pwd)
      item.show()
      menu.append(item)
      return menu # don't show() the menu itself; wait for a popup() call

    pwd_popup_menu = create_pwd_popup_menu()

    pwd_display = gtk.Label()
    pwd_display.set_markup('<span underline="single" font_family="monospace" size="9000" foreground="#555555">%s</span>' % prettify_filename(pwd))

    pwd_display.set_has_tooltip(True)
    pwd_display.connect('query-tooltip', show_tooltip, prettify_filename(pwd))

    pwd_display_box = create_clickable_event_box(pwd_display, pwd_popup_menu)

    bash_event_body = gtk.VBox()

    pwd_valign = create_alignment(pwd_display_box, ptop=3, pbottom=4, pleft=1)
    bash_event_body.pack_start(pwd_valign)

    bash_vbox = gtk.VBox()
    bash_vbox.pack_start(self.header)
    bash_vbox.pack_start(bash_event_body)

    show_all_local_widgets(locals())

    # assign these locals to instance vars after they've been shown ...
    self.widget = bash_vbox
    self.events_vbox = bash_event_body
    self.commands_set = set()


  def add_command_chron_order(self, bash_cmd_event):
    # since we're presumably inserting in chronological order,
    # then update the timestamp when inserting each comment in
    # succession, even if it's already in the collection
    assert not self.timestamp or bash_cmd_event.timestamp > self.timestamp
    self.timestamp = bash_cmd_event.timestamp
    self.update_timestamp()

    cmd_str = ' '.join(bash_cmd_event.cmd)

    # eliminate duplicates
    if cmd_str in self.commands_set:
      return
    self.commands_set.add(cmd_str)

    n = BashFeedEvent.BashCommandDisplay(bash_cmd_event)
    self.events_vbox.pack_start(n.get_widget(), expand=True)


# represents a webpage visit event object in the feed
class WebpageFeedEvent(FeedEvent):

  class WebpageDisplay:
    def __init__(self, webpage_event):
      self.webpage_event = webpage_event # WebpageVisitEvent instance
      self.annotator = AnnotationComponent(WINDOW_WIDTH-50, webpage_event)

      webpage_context_menu = gtk.Menu()
      hashtag_item = gtk.MenuItem('Copy event hashtag')
      hashtag_item.connect("activate", self.copy_event_hashtag)
      add_comment_item = gtk.MenuItem('Annotate web visit')
      add_comment_item.connect("activate", self.annotator.show_comment_box)
      webpage_context_menu.append(hashtag_item)
      webpage_context_menu.append(add_comment_item)

      # make the domain name concise:
      domain_name = urlparse(webpage_event.url).netloc
      if domain_name.startswith('www.'):
        domain_name = domain_name[len('www.'):]

      domain_display = gtk.Label()
      domain_display.set_markup('<span font_family="sans" size="8000" foreground="#666666">[%s] </span>' % domain_name)
      domain_display_box = create_clickable_event_box(domain_display, webpage_context_menu)
      domain_display_box.set_has_tooltip(True)
      domain_display_box.connect('query-tooltip', show_tooltip, webpage_event.url)

      link_display = gtk.Label()
      encoded_url = webpage_event.url.replace('&', '&amp;')
      encoded_title = webpage_event.title.replace('&', '&amp;')

      link_display.set_markup('<span font_family="sans" size="8000"><a href="%s">%s</a></span>' % (encoded_url, encoded_title))

      domain_and_link_display = create_hbox((domain_display_box, link_display))
      webpage_display_lalign = create_alignment(domain_and_link_display, ptop=2, pbottom=1, pleft=1)

      disp_vbox = create_vbox((webpage_display_lalign, self.annotator.get_widget()))

      show_all_local_widgets(locals())
      self.widget = disp_vbox


    def copy_event_hashtag(self, _ignore):
      g_clipboard.set_text(self.webpage_event.get_hashtag())

    def get_widget(self):
      return self.widget


  def __init__(self):
    FeedEvent.__init__(self, None, "google-chrome.png")

    webpage_event_body = gtk.VBox()
    webpage_vbox = gtk.VBox()
    webpage_vbox.pack_start(self.header)
    webpage_vbox.pack_start(webpage_event_body)

    show_all_local_widgets(locals())

    self.widget = webpage_vbox
    self.webpage_event_body = webpage_event_body
    self.stored_URLs = set()


  def add_webpage_chron_order(self, webpage_event):
    # since we're presumably inserting in chronological order,
    # then update the timestamp when inserting each comment in
    # succession, even if it's already in the collection
    assert not self.timestamp or webpage_event.timestamp >= self.timestamp
    self.timestamp = webpage_event.timestamp
    self.update_timestamp()

    # eliminate dups (but still update timestamp unconditionally)
    if webpage_event.url in self.stored_URLs:
      return
    self.stored_URLs.add(webpage_event.url)

    n = WebpageFeedEvent.WebpageDisplay(webpage_event)
    self.webpage_event_body.pack_start(n.get_widget())


THUMBNAIL_WIDTH = 250

class DoodleFeedEvent(FeedEvent):
  def __init__(self, doodle_event, fvm):
    FeedEvent.__init__(self, doodle_event.timestamp, 'mypaint.png')
    self.doodle_event = doodle_event # type: DoodleSaveEvent
    self.timestamp = doodle_event.timestamp
    self.update_timestamp()
    self.fvm = fvm

    thumbnail = gtk.Image()

    thumbnail_lalign = create_alignment(thumbnail, ptop=3, pbottom=4)

    thumbnail_event_box = gtk.EventBox()
    thumbnail_event_box.add(thumbnail_lalign)
    set_white_background(thumbnail_event_box)
    thumbnail_event_box.connect('realize',
                                lambda e:e.window.set_cursor(g_handcursor))

    thumbnail_event_box.connect("button_press_event", self.load_fullsize_image)

    doodle_vbox = gtk.VBox()
    doodle_vbox.pack_start(self.header)
    doodle_vbox.pack_start(thumbnail_event_box)

    show_all_local_widgets(locals())
    self.widget = doodle_vbox
    self.thumbnail = thumbnail # don't load the image just yet!


  def load_thumbnail(self):
    # regular behavior:
    if self.doodle_event.filename in sorted_write_events:
      # ok, we need to grab the version of the file that existed after
      # self.timestamp and BEFORE the next write to that file, since the
      # user might have CLOBBERED this doodle image file with newer doodles,
      # so self.filename might not be correct (or it could be non-existent!)
      filename = self.fvm.checkout_file_before_next_write(self.doodle_event,
                                                          sorted_write_events[self.doodle_event.filename])
    else:
      # if we don't have sorted_write_events, just use the following
      # approximation ...
      filename = self.fvm.checkout_file(self.doodle_event.filename,
                                        self.doodle_event.timestamp + datetime.timedelta(seconds=5))

    assert filename

    # resize the doodle down to a respectable size
    # http://faq.pygtk.org/index.py?req=show&file=faq08.006.htp
    pixbuf = gtk.gdk.pixbuf_new_from_file(filename)
    w = pixbuf.get_width()
    h = pixbuf.get_height()
    if w > THUMBNAIL_WIDTH:
      scaled_buf = pixbuf.scale_simple(THUMBNAIL_WIDTH,
                                       int(float(THUMBNAIL_WIDTH) * float(h) / float(w)),
                                       gtk.gdk.INTERP_BILINEAR)
      self.thumbnail.set_from_pixbuf(scaled_buf)
    else:
      self.thumbnail.set_from_file(filename)
    self.thumbnail.show()


  def load_fullsize_image(self, _ignore, _ignore2):
    if self.doodle_event.filename in sorted_write_events:
      # dynamically generate the filename since the path might have
      # changed (due to new writes ... tricky and subtle!)
      filename = self.fvm.checkout_file_before_next_write(self.doodle_event,
                                                          sorted_write_events[self.doodle_event.filename])
    else:
      filename = self.fvm.checkout_file(self.doodle_event.filename,
                                        self.doodle_event.timestamp + datetime.timedelta(seconds=5))

    assert filename
    os.system('gnome-open "%s" &' % filename)


class FileFeedEvent(FeedEvent):

  class FileEventDisplay:
    def __init__(self, file_provenance_event, parent):
      self.file_provenance_event = file_provenance_event
      self.parent = parent # sub-class of FileFeedEvent
      self.fvm = parent.fvm # instance of FileVersionManager

      self.annotator = AnnotationComponent(WINDOW_WIDTH-50, file_provenance_event)

      file_context_menu = gtk.Menu()

      diff_cur_item = gtk.MenuItem('Diff against latest')
      diff_cur_item.connect("activate", self.diff_with_latest)

      diff_pred_item = gtk.MenuItem('Diff against predecessor')
      diff_pred_item.connect("activate", self.diff_with_predecessor)

      mark_diff = gtk.MenuItem('Select for diff')
      mark_diff.connect("activate", self.mark_for_diff)

      global diff_menu_items
      diff_menu_items.append(mark_diff)

      view = gtk.MenuItem('Open')
      view.connect("activate", self.open_to_view, 'current')
      view_pred = gtk.MenuItem('Open predecessor')
      view_pred.connect("activate", self.open_to_view, 'predecessor')

      revert_current = gtk.MenuItem('Revert to current')
      revert_current.connect("activate", self.revert, 'current')
      revert_pred = gtk.MenuItem('Revert to predecessor')
      revert_pred.connect("activate", self.revert, 'predecessor')
      watch_me = gtk.MenuItem('Watch for changes')
      watch_me.connect("activate", self.watch_for_changes)
      view_source_prov = gtk.MenuItem('View source file provenance')
      view_source_prov.connect("activate", self.view_source_prov)
      view_output_prov = gtk.MenuItem('View output file provenance')
      view_output_prov.connect("activate", self.view_output_prov)

      # not implemented yet
      item5 = gtk.MenuItem('Ignore file')
      item6 = gtk.MenuItem('Ignore directory')

      copy_filename_item = gtk.MenuItem('Copy filename')
      copy_filename_item.connect("activate", self.copy_filename)
      hashtag_item = gtk.MenuItem('Copy event hashtag')
      hashtag_item.connect("activate", self.copy_event_hashtag)
      add_comment_item = gtk.MenuItem('Annotate file version')
      add_comment_item.connect("activate", self.annotator.show_comment_box)

      separator1 = gtk.SeparatorMenuItem()
      separator2 = gtk.SeparatorMenuItem()
      separator3 = gtk.SeparatorMenuItem()
      separator4 = gtk.SeparatorMenuItem()

      file_context_menu.append(copy_filename_item)
      file_context_menu.append(hashtag_item)
      file_context_menu.append(add_comment_item)
      file_context_menu.append(separator1)
      file_context_menu.append(diff_cur_item)
      file_context_menu.append(diff_pred_item)
      file_context_menu.append(mark_diff)
      file_context_menu.append(separator2)
      file_context_menu.append(view)
      file_context_menu.append(view_pred)
      file_context_menu.append(watch_me)
      file_context_menu.append(separator3)
      file_context_menu.append(revert_current)
      file_context_menu.append(revert_pred)
      file_context_menu.append(separator4)
      file_context_menu.append(view_source_prov)
      file_context_menu.append(view_output_prov)
      #file_context_menu.append(item5)
      #file_context_menu.append(item6)

      # only show base path in label for brevity
      file_label = gtk.Label(os.path.basename(self.file_provenance_event.filename))
      file_label.modify_font(pango.FontDescription("monospace 8"))
      file_label_box = create_clickable_event_box(file_label, file_context_menu)
      # ... but show FULL file path in tooltip
      file_label_box.set_has_tooltip(True)
      file_label_box.connect('query-tooltip', show_tooltip, prettify_filename(self.file_provenance_event.filename))

      icon_and_label_box = gtk.HBox()
      icon_and_label_box.pack_end(file_label_box, expand=False)

      file_lalign = create_alignment(icon_and_label_box, ptop=2, pbottom=2, pleft=2)

      file_vbox = create_vbox((file_lalign, self.annotator.get_widget()))

      show_all_local_widgets(locals())
      self.widget = file_vbox
      self.icon_and_label_box = icon_and_label_box
      self.watchme_icon_alignment = None # lazily allocate to save memory


      global watch_files
      try:
        old_version_path = watch_files[self.file_provenance_event.filename].checkout_and_get_path()
        if os.path.exists(old_version_path):
          if not filecmp.cmp(old_version_path, self.file_provenance_event.filename):
            # there's a diff!
            changed_icon = gtk.Image()
            changed_icon.set_from_file('red-exclamation-point-16x16.png')
            changed_icon.show()
            changed_icon_alignment = create_alignment(changed_icon, pright=3)
            changed_icon_alignment.show()
            self.icon_and_label_box.pack_end(changed_icon_alignment)
            file_label.modify_fg(gtk.STATE_NORMAL, gtk.gdk.Color('#800517')) # make it red!
          else:
            # 'passed' the informal regression test set by watchfile
            test_pass_icon = gtk.Image()
            test_pass_icon.set_from_file('tasque-check-box.png')
            test_pass_icon.show()
            test_pass_icon_alignment = create_alignment(test_pass_icon, pright=3)
            test_pass_icon_alignment.show()
            self.icon_and_label_box.pack_end(test_pass_icon_alignment)
      except KeyError:
        pass


    def get_widget(self):
      return self.widget
    
    def get_filename(self):
      return self.file_provenance_event.filename

    def copy_filename(self, _ignore):
      g_clipboard.set_text(self.file_provenance_event.filename)

    def copy_event_hashtag(self, _ignore):
      g_clipboard.set_text(self.file_provenance_event.get_hashtag())


    def checkout_and_get_path(self):
      return self.fvm.checkout_file_before_next_write(self.file_provenance_event,
                                                      sorted_write_events[self.file_provenance_event.filename])

    # to find the predecessor, simply check out the file one second
    # before the write occurred ...
    #
    # TODO: this isn't exactly correct, since you could've had a bunch
    # of coalesced writes, so you might want to get the version BEFORE
    # the series of coalesced writes.
    def checkout_predecessor_and_get_path(self):
      return self.fvm.checkout_file(self.get_filename(),
                                    self.file_provenance_event.timestamp - ONE_SEC)


    def diff_with_latest(self, _ignore):
      # requires the 'meld' visual diff tool to be installed
      old_version_path = self.checkout_and_get_path()
      fn = self.file_provenance_event.filename
      os.system('meld "%s" "%s" &' % (old_version_path, fn))


    def diff_with_predecessor(self, _ignore):
      post_write_path = self.checkout_and_get_path()
      predecessor_path = self.checkout_predecessor_and_get_path()
      os.system('meld "%s" "%s" &' % (predecessor_path, post_write_path))


    def mark_for_diff(self, _ignore):
      global diff_left_half, diff_menu_items # KLUDGY!
      if diff_left_half:
        diff_right_half_path = self.checkout_and_get_path()
        diff_left_half_path = diff_left_half.checkout_and_get_path()
        os.system('meld "%s" "%s" &' % (diff_left_half_path, diff_right_half_path))

        # RESET!
        diff_left_half = None
        for e in diff_menu_items:
          e.set_label('Select for diff')
      else:
        diff_left_half = self 
        for e in diff_menu_items:
          e.set_label('Diff against selected file')


    def open_to_view(self, _ignore, option):
      if option == 'current':
        old_version_path = self.checkout_and_get_path()
      elif option == 'predecessor':
        old_version_path = self.checkout_predecessor_and_get_path()
      else:
        assert False

      # gnome-open to the rescue!!!  uses a file's type to determine the
      # proper viewer application :)
      if not os.path.isfile(old_version_path):
        create_popup_error_dialog("File not found:\n" + old_version_path)
      else:
        os.system('gnome-open "%s" &' % old_version_path)


    def view_source_prov(self, _ignore):
      global cur_session
      spv = source_file_prov_viewer.SourceFileProvViewer(self.get_filename(), cur_session, self.fvm)

    def view_output_prov(self, _ignore):
      global cur_session # KLUDGY!
      print 'view_output_prov:', self.get_filename(), cur_session
      opv = output_file_prov_viewer.OutputFileProvViewer(self.get_filename(), cur_session, self.fvm)


    def watch_for_changes(self, _ignore):
      global watch_files
      fn = self.file_provenance_event.filename
      if fn in watch_files:
        # un-watch the other file:
        other = watch_files[fn]
        assert other.watchme_icon_alignment
        other.icon_and_label_box.remove(other.watchme_icon_alignment)

        # if other is actually self, then un-watch!
        if other == self:
          del watch_files[fn]
          return # PUNTTT!

      watch_files[fn] = self

      # "freeze" the enclosing FileMutatedFeedEvent object when you
      # create a watchpoint so that subsequent writes don't coalesce into
      # this FileMutatedFeedEvent entry and possibly destroy the current
      # FileEventDisplay object in the # process!
      self.parent.frozen = True

      watchme_icon = gtk.Image()
      watchme_icon.set_from_file('magnifying-glass-16x16.png')
      watchme_icon.show()
      self.watchme_icon_alignment = create_alignment(watchme_icon, pright=3)
      self.watchme_icon_alignment.show()

      self.icon_and_label_box.pack_end(self.watchme_icon_alignment)


    # option = 'current' or 'predecessor'
    def revert(self, _ignore, option):
      if option == 'current':
        old_version_path = self.checkout_and_get_path()
      elif option == 'predecessor':
        old_version_path = self.checkout_predecessor_and_get_path()
      else:
        assert False

      if not os.path.isfile(old_version_path):
        create_popup_error_dialog("File not found:\n" + old_version_path)
      else:
        # pop-up a confirmation dialog before taking drastic action!
        d = gtk.MessageDialog(None,
                              gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                              gtk.MESSAGE_QUESTION,
                              gtk.BUTTONS_YES_NO,
                              message_format="Are you sure you want to revert\n\n  %s\n\nto\n\n  %s" % \
                                             (self.get_filename(), old_version_path))
        d.show()
        response = d.run()
        d.destroy()

        if response == gtk.RESPONSE_YES:

          # VERY INTERESTING: the 'cp' command sometimes doesn't work
          # for NILFS, since it thinks that the snapshot version is
          # IDENTICAL to the latest current version of the file and will
          # thus refuse to do the copy even though their contents are
          # clearly different.
          #
          # Thus, we will do a super-hack where we copy the file to
          # tmp_blob and then rename it to the real filename ...
          tmp_blob = '/tmp/tmp-reverted-file'
          revert_cmd = "cp '%s' '%s'; mv '%s' '%s'" % (old_version_path, tmp_blob,
                                                       tmp_blob, self.get_filename())
          os.system(revert_cmd)


  def revert_all_files_to_pred(self, _ignore):
    for v in self.contents.itervalues():
      v.revert(None, 'predecessor')

  def watch_all_files(self, _ignore):
    for v in self.contents.itervalues():
      v.watch_for_changes(None)


  def __init__(self, process_name, fvm, icon_filename):
    FeedEvent.__init__(self, None, icon_filename)
    self.process_name = process_name
    self.fvm = fvm

    self.frozen = False # if frozen, then don't allow any more coalescing into it!

    def create_proc_popup_menu():
      menu = gtk.Menu()
      #item1 = gtk.MenuItem('Ignore process')

      revert_all = gtk.MenuItem('Revert all files to predecessors')
      revert_all.connect('activate', self.revert_all_files_to_pred)
      revert_all.show()

      watch_all_files = gtk.MenuItem('Watch all files for changes')
      watch_all_files.connect('activate', self.watch_all_files)
      watch_all_files.show()

      menu.append(watch_all_files)
      menu.append(revert_all)
      return menu # don't show() the menu itself; wait for a popup() call


    proc_display = gtk.Label()
    proc_display.set_markup('<span underline="single" font_family="monospace" size="9000" foreground="#555555">%s</span>' % self.process_name)

    # Punt on this menu for now ...
    proc_popup_menu = create_proc_popup_menu()
    proc_display_box = create_clickable_event_box(proc_display, proc_popup_menu)

    proc_valign = create_alignment(proc_display_box, ptop=3, pbottom=4, pleft=1)
    file_event_body = gtk.VBox()
    file_event_body.pack_start(proc_valign)

    file_vbox = gtk.VBox()
    file_vbox.pack_start(self.header)
    file_vbox.pack_start(file_event_body)

    show_all_local_widgets(locals())

    # assign these locals to instance vars after they've been shown ...
    self.widget = file_vbox
    self.events_vbox = file_event_body

    # Key: filename
    # Value: FileFeedEvent.FileEventDisplay object
    self.contents = {}


  def add_file_evt_chron_order(self, file_provenance_event):
    # since we're presumably inserting in chronological order,
    # then update the timestamp when inserting each comment in
    # succession, even if it's already in the collection
    #
    # loosened the '>' comparison to '>=' to handle some corner cases:
    assert not self.timestamp or file_provenance_event.timestamp >= self.timestamp
    self.timestamp = file_provenance_event.timestamp
    self.update_timestamp()

    fn = file_provenance_event.filename

    # de-dup by removing existing widget for this filename (if it exists)
    try:
      existing_widget = self.contents[fn].get_widget()
      self.events_vbox.remove(existing_widget)
    except KeyError:
      pass

    # ALWAYS add the latest entry (so we can have an up-to-date timestamp) ...
    n = FileFeedEvent.FileEventDisplay(file_provenance_event, self)
    self.contents[fn] = n
    self.events_vbox.pack_start(n.get_widget(), expand=True)


# represents a file 'read' event (either a read or the source of a
# rename operation) by a particular process
class FileObservedFeedEvent(FileFeedEvent):
  def __init__(self, process_name, fvm):
    FileFeedEvent.__init__(self, process_name, fvm, "magnifying-glass.png")

# represents a file-mutated event in the feed (either a write or the
# target of a rename operation), whereby one or more files are being
# mutated by a particular process (either active or exited).
class FileMutatedFeedEvent(FileFeedEvent):
  def __init__(self, process_name, fvm):
    FileFeedEvent.__init__(self, process_name, fvm, "media-floppy.png")


class BurritoFeed:
  def create_status_pane(self):

    happy_img = gtk.Image()
    happy_img.set_from_file("yellow-happy-face.xpm")
    happy_face = gtk.Button()
    happy_face.add(happy_img)
    happy_face.set_relief(gtk.RELIEF_HALF)
    happy_face.connect('clicked', self.happy_face_button_clicked)

    sad_img = gtk.Image()
    sad_img.set_from_file("red-sad-face.xpm")
    sad_face = gtk.Button()
    sad_face.add(sad_img)
    sad_face.set_relief(gtk.RELIEF_HALF)
    sad_face.connect('clicked', self.sad_face_button_clicked)

    happy_sad_face_pane = gtk.HBox()
    happy_sad_face_pane.pack_start(happy_face, expand=True, fill=True, padding=15)
    happy_sad_face_pane.pack_end(sad_face, expand=True, fill=True, padding=15)


    su_input = gtk.TextView()
    su_input.set_wrap_mode(gtk.WRAP_WORD)
    su_input.set_left_margin(3)
    su_input.set_right_margin(3)
    # add a thin gray border around the text input box:
    su_input.set_border_width(1)
    su_input.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color('#bbbbbb'))

    # I dunno how to set the number of displayed rows, so I just did a
    # hack and set the requested size to be something fairly small ...
    su_input.set_size_request(0, 50)

    sw = gtk.ScrolledWindow()
    sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
    sw.add(su_input)

    status_update_pane = gtk.VBox()
    status_update_pane.pack_start(sw, padding=3)

    su_post_button = gtk.Button("   Post   ")
    su_post_button.connect('clicked', self.post_button_clicked)

    l = gtk.Label("What's on your mind?")
    l.set_alignment(0, 0.5)

    post_pane = gtk.HBox()
    post_pane.pack_start(l, expand=True, fill=True)

    post_pane.pack_end(su_post_button, expand=False, fill=False)
    status_update_pane.pack_start(post_pane, padding=2)

    status_pane = create_vbox((happy_sad_face_pane, status_update_pane), (5, 0))

    show_all_local_widgets(locals())

    su_input.grab_focus() # do this as late as possible

    # kinda impure, but whatever ...
    self.status_input = su_input
    self.most_recent_status_str = None # to prevent accidental multiple-clicks

    return status_pane


  def __init__(self, cur_session):
    self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
    self.window.connect("destroy", lambda w: gtk.main_quit())

    self.cur_session = cur_session # unique session ID

    self.window.set_title("Activity Feed")
    self.window.set_icon_from_file("yellow-happy-face.xpm")
    self.window.set_border_width(5)

    vpane = gtk.VBox()
    self.window.add(vpane)

    self.status_pane = self.create_status_pane()

    feed_pane = gtk.ScrolledWindow()
    feed_pane.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

    feed_vbox = gtk.VBox()

    vp = gtk.Viewport()
    vp.add(feed_vbox)
    vp.set_shadow_type(gtk.SHADOW_NONE)
    vp.set_size_request(int((WINDOW_WIDTH * 2.0) / 3), 20) # limit its width
    set_white_background(vp)
    feed_pane.add(vp)

    hs = gtk.HSeparator()
    vpane.pack_start(self.status_pane, expand=False, padding=5)
    vpane.pack_start(hs, expand=False, padding=3)
    vpane.pack_start(feed_pane, expand=True) # fill up the rest of the vbox!


    # move window to left side and make it as tall as the desktop
    self.window.move(0, 0)
    #_w, _h = self.window.get_size()
    self.window.resize(WINDOW_WIDTH, self.window.get_screen().get_height())

    set_white_background(self.window)

    show_all_local_widgets(locals())
    self.window.show() # show the window last

    self.feed_vbox = feed_vbox

    self.feed_events = [] # each element is an instance of a FeedEvent subclass


    # MongoDB stuff
    c = Connection()
    self.db = c.burrito_db

    # we want to incrementally update events in a 'sandwiched' time
    # range between prev_db_last_updated_time and cur_db_last_updated_time
    self.prev_db_last_updated_time = None
    self.cur_db_last_updated_time  = None

    # for making sure we always fetch fresh new FileProvenanceEvent objects
    # each elt is the return value from FileProvenanceEvent.get_unique_id()
    self.file_events_seen = set()

    self.first_time = True

    # for managing NILFS file versions:
    self.fvm = FileVersionManager()


  # returns a list of BashCommandEvent objects
  def fetch_new_bash_events(self):
    db_bash_collection = self.db.apps.bash
    ret = []
    
    if self.prev_db_last_updated_time:
      # tricky tricky ... start looking from the PREVIOUS epoch
      query = db_bash_collection.find({"session_tag": self.cur_session, "_id":{"$gte":self.prev_db_last_updated_time}})
    else:
      query = db_bash_collection.find({"session_tag": self.cur_session})

    for m in query:
      evt = fetch_bash_command_event(m)
      if evt:
        ret.append(evt)

    return ret


  # returns a list of WebpageVisitEvent objects
  def fetch_new_webpage_events(self):
    db_gui_collection = self.db.gui_trace
    ret = []

    if self.prev_db_last_updated_time:
      # tricky tricky ... start looking from the PREVIOUS epoch
      query = db_gui_collection.find({"session_tag": self.cur_session, "_id":{"$gte":self.prev_db_last_updated_time}})
    else:
      query = db_gui_collection.find({"session_tag": self.cur_session})

    for m in query:
      evt = fetch_webpage_visit_event(m)
      if evt:
        ret.append(evt)

    return ret


  # returns a list of FileProvenanceEvent objects
  def fetch_new_file_events(self):
    db_proc_collection = self.db.process_trace

    ret = []
    if self.prev_db_last_updated_time:
      # tricky tricky ... start looking from the PREVIOUS epoch
      query = db_proc_collection.find({"session_tag": self.cur_session,
                                       "most_recent_event_timestamp":{"$gte":self.prev_db_last_updated_time}},
                                       {'pid':1, 'uid':1, 'phases':1})
    else:
      query = db_proc_collection.find({"session_tag": self.cur_session},
                                      {'pid':1, 'uid':1, 'phases':1})

    for m in query:
      evts = fetch_file_prov_event_lst(m, self.cur_session)
      # de-dup!!!
      for e in evts:
        e_id = e.get_unique_id()
        if e_id not in self.file_events_seen:
          ret.append(e)
          self.file_events_seen.add(e_id)

    return ret


  def fetch_new_status_update_events(self):
    # ONLY RUN THIS ONCE at the beginning of execution!!!
    if self.first_time:
      return fetch_toplevel_annotation_events(self.cur_session)
    else:
      return []


  def poll_for_all_event_updates(self):
    bash_events = self.fetch_new_bash_events()
    web_events  = self.fetch_new_webpage_events()
    file_events = self.fetch_new_file_events()
    status_update_events = self.fetch_new_status_update_events()

    db_bash_collection = self.db.apps.bash

    print datetime.datetime.now()
    print '# bash events:', len(bash_events)
    print '# web events:', len(web_events)
    print '# file events:', len(file_events)
    print '# status events :', len(status_update_events)
    print

    self.first_time = False


    # Now "weave" together all streams of event updates:
    all_events = bash_events + web_events + file_events + status_update_events
 
    all_events.sort(key=lambda e:e.timestamp) # chronologically

    new_doodle_feed_events = []

    last_feed_event = None
    for evt in all_events:
      if self.feed_events:
        last_feed_event = self.feed_events[-1]

      if evt.__class__ == BashCommandEvent:
        if (last_feed_event and \
            last_feed_event.__class__ == BashFeedEvent and \
            last_feed_event.pwd == evt.pwd):
          last_feed_event.add_command_chron_order(evt)
        else:
          n = BashFeedEvent(evt.pwd)
          n.add_command_chron_order(evt)
          self.push_feed_event(n)

      elif evt.__class__ == WebpageVisitEvent:
        if (last_feed_event and \
            last_feed_event.__class__ == WebpageFeedEvent):
          last_feed_event.add_webpage_chron_order(evt)
        else:
          n = WebpageFeedEvent()
          n.add_webpage_chron_order(evt)
          self.push_feed_event(n)

      elif evt.__class__ == DoodleSaveEvent:
        # copy-and-paste from FileWriteEvent
        if evt.filename in sorted_write_events:
          assert sorted_write_events[evt.filename][-1].timestamp < evt.timestamp
        else:
          sorted_write_events[evt.filename] = []

        sorted_write_events[evt.filename].append(evt)

        n = DoodleFeedEvent(evt, self.fvm)
        self.push_feed_event(n)
        new_doodle_feed_events.append(n)

      elif evt.__class__ == FileWriteEvent:
        if evt.filename in sorted_write_events:
          assert sorted_write_events[evt.filename][-1].timestamp <= evt.timestamp
        else:
          sorted_write_events[evt.filename] = []

        sorted_write_events[evt.filename].append(evt)

        # First try to coalesce with last_feed_event, regardless of its timestamp ...
        # (unless it's frozen)
        if (last_feed_event and \
            last_feed_event.__class__ == FileMutatedFeedEvent and \
            last_feed_event.process_name == evt.phase_name and \
            not last_feed_event.frozen):

          # except if there's a read barrier!
          last_read_time = None
          try:
            last_read_time = file_read_timestamps[evt.filename]
          except KeyError:
            pass

          if not last_read_time or last_read_time <= evt.timestamp:
            last_feed_event.add_file_evt_chron_order(evt)
            #print 'C:', evt.phase_name, evt.filename
            continue # move along!


        # Process coalescing heuristic: try to go back FIVE SECONDS in
        # the feed to see if there are any matching events with the same
        # process name, and if so, coalesce evt into that process's
        # feed entry.
        #
        # The rationale for this heuristic is that when you're running a
        # ./configure or make compile job, there are often several
        # related 'friend' processes such as cc1/as, sed/grep/cat, etc.
        # that run very quickly back-and-forth, so if you don't
        # coalesce, then you would create a TON of separate
        # FileMutatedFeedEvent instances, when in fact the multiple
        # invocations could be grouped into one instance.  e.g., if you
        # didn't coalesce, you would get something like:
        #   [cc1, as, cc1, as, cc1, as, cc1, as, cc1, as ...]
        #
        # but if you coalesce, you get something much cleaner:
        #   [cc1, as]

        coalesced = False
        for cur_feed_elt in gen_reverse_bounded_time_elts(self.feed_events, evt.timestamp - FIVE_SECS):

          # VERY IMPORTANT!  If there is an intervening read of THIS
          # PARTICULAR FILE, then break right away, because we don't want
          # to coalesce writes beyond read barriers
          try:
            last_read_time = file_read_timestamps[evt.filename]
            if last_read_time > cur_feed_elt.timestamp:
              break
          except KeyError:
            pass

          if (cur_feed_elt.__class__ == FileMutatedFeedEvent and \
              cur_feed_elt.process_name == evt.phase_name):
            if not cur_feed_elt.frozen:
              cur_feed_elt.add_file_evt_chron_order(evt)
              coalesced = True

            # exit loop after the first FileMutatedFeedEvent regardless
            # of whether it's been frozen
            break


        # fallback is to create a new FileMutatedFeedEvent
        if not coalesced:
          n = FileMutatedFeedEvent(evt.phase_name, self.fvm)
          n.add_file_evt_chron_order(evt)
          self.push_feed_event(n)


      elif evt.__class__ == FileReadEvent:
        # add a "read barrier" to prevent write coalescing
        # over-optimizations
        file_read_timestamps[evt.filename] = evt.timestamp

      elif evt.__class__ == StatusUpdateEvent:
        n = StatusUpdateFeedEvent(evt)
        self.push_feed_event(n)

      elif evt.__class__ == HappyFaceEvent:
        n = HappyFaceFeedEvent(evt)
        self.push_feed_event(n)

      elif evt.__class__ == SadFaceEvent:
        n = SadFaceFeedEvent(evt)
        self.push_feed_event(n)

      else:
        print evt
        assert False


    # defer loading of thumnbnails until ALL DoodleFeedEvent instances
    # have been processed, since that's the only way we can ensure that
    # the proper versions of the files are loaded for the thumbnails
    for d in new_doodle_feed_events:
      d.load_thumbnail()


  def push_feed_event(self, evt):
    self.feed_events.append(evt)
    # push new entries to the TOP of the feed
    self.feed_vbox.pack_end(evt.get_widget(), expand=False, padding=6)
    self.update_all_timestamps()

  def update_all_timestamps(self):
    for e in self.feed_events:
      e.update_timestamp()

  def post_button_clicked(self, widget):
    buf = self.status_input.get_buffer()
    status_str = buf.get_text(*buf.get_bounds())
    if status_str and status_str != self.most_recent_status_str:
      self.most_recent_status_str = status_str # to prevent accidental multiple-submits
      n = StatusUpdateFeedEvent(StatusUpdateEvent(status_str,
                                                  datetime.datetime.now(),
                                                  self.cur_session))
      self.push_feed_event(n)
      n.save_to_db() # very important!!!

  def happy_face_button_clicked(self, widget):
    self.commit_handler(widget, True)

  def sad_face_button_clicked(self, widget):
    self.commit_handler(widget, False)

  def commit_handler(self, widget, is_happy):
    if is_happy:
      state = 'happy'
    else:
      state = 'sad'

    label = gtk.Label("What just made you %s?" % state)

    ci = gtk.TextView()
    ci.set_wrap_mode(gtk.WRAP_WORD)
    ci.set_border_width(1)
    ci.set_left_margin(3)
    ci.set_right_margin(3)
    ci.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color('#999999'))
    ci.modify_font(pango.FontDescription("sans 10"))

    sw = gtk.ScrolledWindow()
    sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    sw.add(ci)
    sw.set_size_request(350, 150)

    dialog = gtk.Dialog("%s snapshot" % state,
                       None,
                       gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                       (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                        gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    dialog.vbox.pack_start(label, expand=False, padding=8)
    dialog.vbox.pack_start(sw, expand=False)

    # move dialog to where the mouse pointer is
    rootwin = widget.get_screen().get_root_window()
    x, y, mods = rootwin.get_pointer()
    dialog.move(x, y)

    show_all_local_widgets(locals())
    response = dialog.run()

    # get text before destroying the dialog
    buf = ci.get_buffer()
    msg_str = buf.get_text(*buf.get_bounds())

    dialog.destroy() # destroy the dialog first so it doesn't show up in screenshot

    if response == gtk.RESPONSE_ACCEPT: # 'OK' button pressed
      # don't allow empty commit messages
      if msg_str:
        self.push_commit_event(msg_str, is_happy)


  def push_commit_event(self, msg_str, is_happy):
    now = get_ms_since_epoch()
    now_dt = encode_datetime(now)
    if is_happy:
      prefix = 'happy'
    else:
      prefix = 'sad'
    output_filename = os.path.join(SCREENSHOTS_DIR, 'screenshot-%s.%d.png' % (prefix, now))
    save_screenshot(output_filename)
    if is_happy:
      n = HappyFaceFeedEvent(HappyFaceEvent(msg_str, now_dt, self.cur_session, output_filename))
    else:
      n = SadFaceFeedEvent(SadFaceEvent(msg_str, now_dt, self.cur_session, output_filename))
    bff.push_feed_event(n)
    n.save_to_db() # very important!!!


  def timer_interrupt(self):
    # update BEFORE polling for events
    db_last_updated_time = None
    e = self.db.session_status.find_one({'_id': self.cur_session})
    if e:
      db_last_updated_time = e['last_updated_time']


    if db_last_updated_time != self.cur_db_last_updated_time:
      if self.cur_db_last_updated_time:
        assert db_last_updated_time > self.cur_db_last_updated_time

      self.prev_db_last_updated_time = self.cur_db_last_updated_time
      self.cur_db_last_updated_time = db_last_updated_time

    #print 'Prev:', self.prev_db_last_updated_time
    #print 'Cur: ', self.cur_db_last_updated_time
    #print

    self.poll_for_all_event_updates()

    self.update_all_timestamps()

    # now we've presumably pulled all MongoDB events up to
    # self.prev_db_last_updated_time, so push it forward:
    self.prev_db_last_updated_time = self.cur_db_last_updated_time

    return True # to keep timer interrupts firing


  def main(self):
    gtk.main()


def exit_handler():
  global bff
  bff.fvm.memoize_checkpoints()
  bff.fvm.unmount_all_snapshots()


if __name__ == "__main__":
  if len(sys.argv) > 1:
    cur_session = sys.argv[1]
  else:
    # if you don't pass in an argument, then use the CONTENTS of
    # /var/log/burrito/current-session as the session tag
    cur_session = os.readlink('/var/log/burrito/current-session').strip()

  assert cur_session[-1] != '/' # don't have a weird trailing slash!

  SCREENSHOTS_DIR = '/var/log/burrito/%s/' % cur_session
  assert os.path.isdir(SCREENSHOTS_DIR)

  # have tooltips pop up fairly quickly
  gtk.settings_get_default().set_long_property('gtk-tooltip-timeout', 300, '')

  bff = BurritoFeed(cur_session)

  atexit.register(exit_handler)
  signal(SIGTERM, lambda signum,frame: exit(1)) # trigger the atexit function to run

  bff.timer_interrupt() # call it once on start-up
  gobject.timeout_add(5000, bff.timer_interrupt)
  bff.main() # infinite loop!!!

