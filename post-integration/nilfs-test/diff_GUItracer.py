import os

cur_modtime = None
cur_snapshot = None

significant_snapshots = []

BASE_PATH = '/tmp/test-tmpfs/nilfs-%d/researcher/BurritoBook/GUItracing/GUItracer.py'

for cno in range(4373, 20000):
  try:
    mtime = os.path.getmtime(BASE_PATH % (cno,))
    if cur_modtime and (mtime > cur_modtime):
      significant_snapshots.append((cur_snapshot, cur_modtime))
      print significant_snapshots[-1]

      if len(significant_snapshots) > 1:
        os.system(('diff -u ' + BASE_PATH + ' ' + BASE_PATH + ' >> guitracer.diff') % (significant_snapshots[-2][0], significant_snapshots[-1][0]))


    cur_modtime = mtime
    cur_snapshot = cno

  except OSError:
    pass

