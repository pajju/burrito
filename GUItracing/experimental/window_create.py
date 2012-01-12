import pyatspi

# get the Registry singleton
reg = pyatspi.Registry()

# get desktop
desktop = reg.getDesktop(0)
 
def foo(event):
  if event.source.getRole() != pyatspi.constants.ROLE_FRAME: return
  print event, event.source, event.source.getIndexInParent()

reg.registerEventListener(foo, 'window:create')

try:
   pyatspi.Registry.start()
except KeyboardInterrupt:
   pass

pyatspi.Registry.stop()

