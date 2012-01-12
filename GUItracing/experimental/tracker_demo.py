# Adapted from:
#   http://developers-blog.org/blog/default/2010/08/21/Track-window-and-widget-events-with-AT-SPI

# TODO: can I get PIDs of controlling processes of each window?


'''
Notes about window events:

- When you drag to move a window, it first generates 'window:deactivate'
  when you start dragging, and then 'window:activate' when you release the
  mouse and finish dragging

- When you finish resizing a window, a 'window:activate' event fires

- 'window:minimize', 'window:maximize', and 'window:restore' are for
  minimizing, restoring, and maximizing windows, respectively

- 'window:create' is when a new window pops up.  Perhaps this is a good
  time to update the list of running applications?

- when a window is closed, it seems like only a 'window:deactivate'
  event fires (there's no window close event???)


Notes about object events:

- 'object:state-changed:active' fires on a 'frame' object whenever it
  comes into focus (with event.detail1 == 1)

- 'object:bounds-changed' fires on a 'frame' object whenever it's
  resized

- 'object:property-change:accessible-name' fires on a 'frame' object
  whenever its title changes ... good for detecting webpage and terminal
  title changes

'''


import pyatspi

# get the Registry singleton
reg = pyatspi.Registry()

# get desktop
desktop = reg.getDesktop(0)
 

def genericEventCallback(event):
  print "GENERIC:", event
  print


# SUPER hacky way of getting the current URL string from Google
# Chrome and Firefox ... there MUST be a better way :)
#
# use Accerciser to find the exact location of the URL bar ...
# note that this will BREAK if the user's Chrome/Firefox GUI even
# looks slightly different than my own GUI:
def getChromeUrlField(frameElt):
  return frameElt[0][0][2][0][0][1][0][1][1][0][0]

def getFirefoxUrlField(frameElt):
  return frameElt[11][6][1]


def windowEventCallback(event):
  print event
  print
  return # stent
  for app in desktop:
    if app:
      print app
      for child in app:
        if child.getRoleName() == 'frame':
          print '  window title:', child.name
          comp = child.queryComponent()
          print '    abs. position:', comp.getPosition(0)
          #print '    rel. position:', comp.getPosition(1)
          print '    size:', comp.getSize()

          urlField = None
          if app.name == 'google-chrome':
            urlField = getChromeUrlField(child)
          elif app.name == 'Firefox':
            urlField = getFirefoxUrlField(child)

          if urlField:
            urlTextField = urlField.queryEditableText()
            urlString = urlTextField.getText(0, urlTextField.characterCount)
            print '    URL bar:', urlString
  print '---'


def stateChangedEventCallback(event):

  if event.source.getRoleName() != 'frame': return

  print event
  print
  return # stent

  # filter to make it less inefficient:
  if event.source.getRoleName() != 'text':
    return

  evt_app = event.source.getApplication().name
  if evt_app != 'google-chrome' and evt_app != 'Firefox':
    return


  # TODO: this is really inefficient right now ... store these fields in
  # a local cache somewhere :)
  for app in desktop:
    if app:
      if app.name in ('google-chrome', 'Firefox'):
        for child in app:
          if child.getRoleName() == 'frame':
            if app.name == 'google-chrome':
              urlField = getChromeUrlField(child)
            else:
              urlField = getFirefoxUrlField(child)
            if event.source == urlField:
              urlTextField = urlField.queryEditableText()
              urlString = urlTextField.getText(0, urlTextField.characterCount)
              print '  CHANGED window URL bar:', urlString


#reg.registerEventListener(windowEventCallback, 'window')

#reg.registerEventListener(genericEventCallback, 'focus') # doesn't seem to work well


#reg.registerEventListener(stateChangedEventCallback, 'object:state-changed')



# Detects when a frame becomes 'active', which happens when it comes
# into focus or when it's finished being moved ... seems pretty robust
def frameActive(event):
  if event.source.getRoleName() != 'frame': return
  if event.detail1 == 1:
    print event
    print event.host_application
    print

reg.registerEventListener(frameActive, 'object:state-changed:active')


def frameTitleChange(event):
  if event.source.getRoleName() != 'frame': return
  print event

reg.registerEventListener(frameTitleChange, 'object:property-change:accessible-name')


#def windowEvent(event):
#  print event
#
#reg.registerEventListener(windowEvent, 'window')


try:
   pyatspi.Registry.start()
except KeyboardInterrupt:
   pass

pyatspi.Registry.stop()

