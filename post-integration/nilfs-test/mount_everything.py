# Crazy idea ... mount ALL snapshots and see whether my VM explodes

# Run as 'sudo'


def create_dir(path):
    "Check if @path is present, and make the directory if not."
    if os.path.exists(path):
        if not os.path.isdir(path):
             info = "path is not directory: %s" % path
             raise Exception(info)
    else:
        os.mkdir(path)


import os
import commands

MOUNTDIR_BASE = '/tmp/test-tmpfs'
assert os.path.isdir(MOUNTDIR_BASE)

commands.getstatusoutput('umount %s' % (MOUNTDIR_BASE,))
result = commands.getstatusoutput('mount -t tmpfs none %s' % (MOUNTDIR_BASE,))
assert result[0] == 0

import nilfs2
n = nilfs2.NILFS2()

for e in n.lscp():
  if e['ss']:
    cno = e['cno']
    subdir_name = os.path.join(MOUNTDIR_BASE, 'nilfs-' + str(cno))
    create_dir(subdir_name)
    print "Mount", subdir_name
    commands.getstatusoutput('sudo mount -t nilfs2 -n -o ro,cp=%d /dev/dm-3 %s' % (cno, subdir_name))

