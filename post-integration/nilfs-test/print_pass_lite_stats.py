import os

for i in range(494, 2000):
  try:
    print i, os.path.getmtime('/tmp/test-tmpfs/nilfs-%d/researcher/BurritoBook/SystemTap/pass-lite.stp' % (i,))
  except:
    print i, "WTF???"

