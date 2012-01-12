# print stats for the current snapshot

# assumes that chcp_ss_all.py has already been run

MIN_INDEX = 6      # the first snapshot where "/home/researcher" exists
MAX_INDEX = 159496 # maximum index we're using in our USENIX experiments

import commands, sys, os, md5, cPickle


# From: http://www.joelverhagen.com/blog/2011/02/md5-hash-of-file-in-python/
import hashlib
def md5Checksum(filePath):
    fh = open(filePath, 'rb')
    m = hashlib.md5()
    while True:
        data = fh.read(8192)
        if not data:
            break
        m.update(data)
    return m.hexdigest()


def mount_snapshot(index):
  assert 1 <= index < MAX_INDEX
  mountpoint = '/tmp/nilfs-snapshots/%d' % index
  assert not os.path.isdir(mountpoint)
  os.mkdir(mountpoint)
  mount_cmd = 'sudo mount -t nilfs2 -n -o ro,cp=%d /dev/dm-3 %s' % (index, mountpoint)
  (status, output) = commands.getstatusoutput(mount_cmd)
  assert status == 0


def unmount_snapshot(index):
  assert 1 <= index < MAX_INDEX
  mountpoint = '/tmp/nilfs-snapshots/%d' % index
  assert os.path.isdir(mountpoint)
  umount_cmd = 'sudo umount ' + mountpoint
  (status, output) = commands.getstatusoutput(umount_cmd)
  assert status == 0
  os.rmdir(mountpoint)


# returns a dict
def get_stats(index):
  ret = {}

  ret['omitted_dotfiles'] = True # we're gonna omit dotfiles and dotdirectories

  assert 1 <= index < MAX_INDEX
  mountpoint = '/tmp/nilfs-snapshots/%d' % index
  homedir = mountpoint + '/researcher/'
  assert os.path.isdir(homedir)

  ret['index'] = index
  (status, output) = commands.getstatusoutput('du -sb ' + homedir)
  assert status == 0
  ret['total_bytes'] = int(output.split()[0])

  filesDict = {}
  ret['files'] = filesDict

  for (d, sd, files) in os.walk(homedir):
    for f in files:
      path = os.path.join(d, f)

      pretty_path = path[len(homedir):]

      # SKIP THESE to GREATLY GREATLY speed things up!!!
      if pretty_path.startswith('.'): continue # dot directory within $HOME
      if f.startswith('.'): continue # dotfile!

      # sometimes 'path' isn't a real file, so DON'T count those
      try:
        filesDict[pretty_path] = md5Checksum(path)
      except:
        print 'md5sum error on', path

  return ret


if __name__ == '__main__':
  #mount_snapshot(25585)
  #get_stats_fast(25585)
  #unmount_snapshot(25585)
  #sys.exit(0)

  #for i in range(149000, MAX_INDEX+1):
  for i in range(MAX_INDEX, MAX_INDEX+1):
    try:
      mount_snapshot(i)
      cPickle.dump(get_stats(i), open('/tmp/nilfs-snapshots/%d.pickle' % i, 'w'), -1)
      unmount_snapshot(i)
    except:
      print 'Uncaught exception at index', i
      continue

    if i % 100 == 0:
      print i

