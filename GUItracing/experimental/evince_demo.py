import pyatspi

# get the Registry singleton
reg = pyatspi.Registry()

# get desktop
desktop = reg.getDesktop(0)
 
def foo(event):
  if event.host_application.name != 'evince': return
  print event

reg.registerEventListener(foo, 'object')
reg.registerEventListener(foo, 'window')
reg.registerEventListener(foo, 'focus')

try:
   pyatspi.Registry.start()
except KeyboardInterrupt:
   pass

pyatspi.Registry.stop()

