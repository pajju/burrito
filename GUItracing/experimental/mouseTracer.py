import time
import pyatspi

reg = pyatspi.Registry()    # get the Registry singleton

def get_ms_since_epoch():
  milliseconds_since_epoch = int(time.time() * 1000)
  return milliseconds_since_epoch

def mouseEventHandler(event):
  xCoord = int(event.detail1)
  yCoord = int(event.detail2)
  print xCoord, yCoord, dir(event)

reg.registerEventListener(mouseEventHandler, 'mouse:button:2p')

try:
   pyatspi.Registry.start()
except KeyboardInterrupt:
   pass
finally:
  pyatspi.Registry.stop()

