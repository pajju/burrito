# PyGTK component for creating, loading, viewing, and saving
# annotations into a MongoDB database
#
# Created on 2011-12-13

import pygtk
pygtk.require('2.0')
import gtk, pango
from pygtk_burrito_utils import *
from pymongo import Connection


# db_liaison needs to have three methods to interact with an underlying
# database: insert_annotation(), delete_annotation(), load_annotation()
#
# if display_when_empty is non-null, then display the given message
# when there's no annotation
class AnnotationComponent:
  def __init__(self, width, db_liaison, display_when_empty=False):
    self.display_when_empty = display_when_empty

    ci = gtk.TextView()
    ci.set_wrap_mode(gtk.WRAP_WORD)
    ci.set_border_width(1)
    ci.set_left_margin(3)
    ci.set_right_margin(3)
    ci.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color('#999999')) # need a gray border
    ci.modify_font(pango.FontDescription("sans 9"))

    comment_input = gtk.ScrolledWindow()
    comment_input.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    comment_input.set_size_request(width, 50)
    comment_input.add(ci)

    comment_post_btn = gtk.Button(' Post ')
    comment_post_btn.connect('clicked', self.post_comment)
    comment_cancel_btn = gtk.Button('Cancel')
    comment_cancel_btn.connect('clicked', self.cancel_comment)
    comment_button_hbox = gtk.HBox()
    comment_button_hbox.pack_start(comment_post_btn, expand=False)
    comment_button_hbox.pack_start(comment_cancel_btn, expand=False, padding=5)

    comment_box = gtk.VBox()
    comment_box.pack_start(comment_input)
    comment_box.pack_start(comment_button_hbox, padding=3)

    comment_display = gtk.Label()
    comment_display.modify_font(pango.FontDescription("sans 9"))
    # make annotations colored ...
    comment_display.modify_fg(gtk.STATE_NORMAL, gtk.gdk.Color('#3D477B'))
    comment_display.set_line_wrap(True) # turn on word-wrapping!

    comment_display.set_size_request(width, -1)

    comment_display_lalign = gtk.Alignment(0, 0, 0, 0)

    # only use the "Edit annotation" context menu when
    # display_when_empty is non-null
    if display_when_empty:
      edit_menu = gtk.Menu()
      edit_item = gtk.MenuItem('Edit annotation')
      edit_item.connect("activate", self.show_comment_box)
      edit_menu.append(edit_item)

      comment_display_evt_box = create_clickable_event_box(comment_display, edit_menu)
      comment_display_lalign.add(comment_display_evt_box)
    else:
      comment_display.set_selectable(True)
      comment_display_lalign.add(comment_display)

    comment_display_lalign.set_padding(0, 5, 2, 0)


    input_and_display_box = gtk.VBox()
    input_and_display_box.pack_start(comment_box, expand=False)
    input_and_display_box.pack_start(comment_display_lalign, expand=False)

    # enforce suggested width by putting it in an lalign:
    annotation_lalign = gtk.Alignment(0, 0, 0, 0)
    annotation_lalign.set_padding(2, 2, 8, 0)
    annotation_lalign.add(input_and_display_box)

    self.widget = annotation_lalign
    self.comment_input_text_buffer = ci.get_buffer()
    self.comment_box = comment_box
    self.comment_display = comment_display

    self.db_liaison = db_liaison
    self.saved_comment = self.db_liaison.load_annotation()

    show_all_local_widgets(locals())

    if self.saved_comment:
      self.comment_display.set_label(self.saved_comment)
      self.comment_input_text_buffer.set_text(self.saved_comment)
    else:
      self.show_empty_comment_display()

    self.comment_box.hide()


  def show_empty_comment_display(self):
    if self.display_when_empty:
      self.comment_display.set_label(self.display_when_empty)
      self.comment_display.show()
    else:
      self.comment_display.hide()


  def show_comment_box(self, *rest):
    self.comment_display.hide()
    self.comment_box.show()

  def post_comment(self, _ignore):
    self.comment_box.hide()

    # strip only trailing spaces
    self.saved_comment = self.get_comment_input_text().rstrip()

    if self.saved_comment:
      self.comment_display.set_label(self.saved_comment)
      self.comment_display.show()
      self.db_liaison.insert_annotation(self.saved_comment)
    else:
      self.show_empty_comment_display()
      self.db_liaison.delete_annotation()


  def cancel_comment(self, _ignore):
    self.comment_box.hide()
    if self.saved_comment:
      self.comment_display.show()
    else:
      self.show_empty_comment_display()


  def get_comment_input_text(self):
    return self.comment_input_text_buffer.get_text(*self.comment_input_text_buffer.get_bounds())

  def get_widget(self):
    return self.widget

  def get_saved_comment(self):
    return self.saved_comment


if __name__ == "__main__":
  window = gtk.Window(gtk.WINDOW_TOPLEVEL)
  window.connect("destroy", lambda w: gtk.main_quit())
  window.set_title("Annotator Component")
  window.set_border_width(8)

  c = Connection()
  annotation_test_collection = c.burrito_db.annotation_test

  a = AnnotationComponent(250, annotation_test_collection, 123)
  a.show_comment_box()

  window.add(a.get_widget())
  window.show()

  gtk.main()

