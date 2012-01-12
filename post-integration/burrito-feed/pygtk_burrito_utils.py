import gtk, pango

g_handcursor = gtk.gdk.Cursor(gtk.gdk.HAND2)

# meta-hack to call '.show()' for all local variables representing
# GUI elements in one fell swoop:
# (remember, this doesn't pick up on instance vars)
def show_all_local_widgets(my_locals):
  for (varname, val) in my_locals.iteritems():
    if isinstance(val, gtk.Object) and hasattr(val, 'show'):
      val.show()

def set_white_background(elt):
  elt.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color('#ffffff'))

def show_tooltip(item, x, y, keyboard_mode, tooltip, text):
  tooltip.set_text(text)
  return True

def mouse_press_for_context_menu(widget, event):
  if event.type == gtk.gdk.BUTTON_PRESS:
    widget.popup(None, None, None, event.button, event.time)
    # Tell calling code that we have handled this event the buck stops here.
    return True
  # Tell calling code that we have not handled this event pass it on.
  return False


# wrapper for creating a Gtk Alignment object with specified padding
def create_alignment(child, ptop=0, pbottom=0, pleft=0, pright=0):
  ret = gtk.Alignment(0, 0, 0, 0)
  ret.add(child)
  ret.set_padding(ptop, pbottom, pleft, pright)
  return ret

# wrapper for packing children tightly in an hbox, with an optional
# padding parameter for each element of children
def create_hbox(children, padding=None):
  ret = gtk.HBox()
  if not padding:
    padding = [0 for e in children]
  for c, p in zip(children, padding):
    ret.pack_start(c, expand=False, padding=p)
  return ret

def create_vbox(children, padding=None):
  ret = gtk.VBox()
  if not padding:
    padding = [0 for e in children]
  for c, p in zip(children, padding):
    ret.pack_start(c, expand=False, padding=p)
  return ret


def create_clickable_event_box(child, context_menu):
  ret = gtk.EventBox()
  ret.add(child)
  set_white_background(ret)
  ret.connect_object("button_press_event",
                     mouse_press_for_context_menu,
                     context_menu)
  ret.connect('realize', lambda e: e.window.set_cursor(g_handcursor))
  return ret


def create_simple_text_view_widget(str_to_display, width, height):
  lab = gtk.Label()
  lab.modify_font(pango.FontDescription("monospace 9"))
  lab.set_label(str_to_display)
  lab.set_line_wrap(False)

  lab_lalign = create_alignment(lab, pleft=4, ptop=4)

  vp = gtk.Viewport()
  vp.add(lab_lalign)
  set_white_background(vp)

  lab_scroller = gtk.ScrolledWindow()
  lab_scroller.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
  lab_scroller.add(vp)
  lab_scroller.set_size_request(width, height)

  show_all_local_widgets(locals())

  return lab_scroller


def create_popup_error_dialog(msg):
  d = gtk.MessageDialog(None,
                        gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                        gtk.MESSAGE_ERROR,
                        gtk.BUTTONS_OK,
                        message_format=msg)
  d.run()
  d.destroy()

