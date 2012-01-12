import pyatspi

# get the Registry singleton
reg = pyatspi.Registry()

# get desktop
desktop = reg.getDesktop(0)
 
def foo(event):
  if event.source.getRole() != pyatspi.constants.ROLE_FRAME: return

  print dir(event)
  if event.detail1 == 0:
    print event

reg.registerEventListener(foo, 'window')
reg.registerEventListener(foo, 'object:state-changed:visible')

try:
   pyatspi.Registry.start()
except KeyboardInterrupt:
   pass

pyatspi.Registry.stop()

