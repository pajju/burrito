# File version manager for NILFS
# Created on 2011-12-15 by Philip Guo

# Heavily inspired by nilfs2_ss_manager in the TimeBrowse project by
# Jiro SEKIBA <jir@unicus.jp>


# Change this to the exact name of your LVM home partition:
NILFS_DEV_NAME = '/dev/vg_burritofedora/lv_home'



# TODO: instead of using a pickle file, simply use a MongoDB collection
# to store the lscp cached data ;)


'''
Required setup to run nilfs commands with 'sudo' WITHOUT entering a password!

Add these lines to /etc/sudoers by editing it using "sudo visudo":

  researcher      ALL=(ALL)       ALL
  researcher      ALL=NOPASSWD: /bin/mount
  researcher      ALL=NOPASSWD: /bin/umount
  researcher      ALL=NOPASSWD: /sbin/mount.nilfs2
  researcher      ALL=NOPASSWD: /sbin/umount.nilfs2
  researcher      ALL=NOPASSWD: /usr/bin/chcp
  researcher      ALL=NOPASSWD: /usr/bin/mkcp
  researcher      ALL=NOPASSWD: /usr/bin/rmcp

The first line gives user 'researcher' full sudo access.  All subsequent
lines say that 'researcher' can run those commands as 'sudo' WITHOUT
TYPING A PASSWORD!  Note that those commands still must be run as
'sudo', but no password is required :)
'''

import nilfs2
import os, sys, datetime
import commands
import cPickle

import atexit
from signal import signal, SIGTERM


NILFS_SNAPSHOT_BASE = '/tmp/nilfs-snapshots'
assert os.path.isdir(NILFS_SNAPSHOT_BASE)

assert os.path.exists(NILFS_DEV_NAME)

# Note that this cached file might be outdated since the script might
# have changed some checkpoint ('cp') into a snapshot ('ss'), but that
# might not be reflected in the pickle file
CACHED_CHECKPOINTS_FILE = os.path.join(NILFS_SNAPSHOT_BASE, 'lscp.out.pickle')

HOMEDIR_PREFIX = '/home/'
ONE_SEC = datetime.timedelta(seconds=1)


class FileVersionManager:
  def __init__(self):
    self.unmount_all_snapshots() # RESET EVERYTHING UP FRONT!!!

    self.nilfs = nilfs2.NILFS2()
    self.checkpoints = []

    if os.path.isfile(CACHED_CHECKPOINTS_FILE):
      self.checkpoints = cPickle.load(open(CACHED_CHECKPOINTS_FILE))
      print >> sys.stderr, "Loaded %d cached checkpoints from %s" % (len(self.checkpoints), CACHED_CHECKPOINTS_FILE)

    self.update_checkpoints() # always do an incremental update!

    # Key: checkpoint ID
    # Value: mountpoint of snapshot
    self.active_snapshots = {}


  def memoize_checkpoints(self):
    print >> sys.stderr, "Saving %d cached checkpoints in %s" % (len(self.checkpoints), CACHED_CHECKPOINTS_FILE)
    cPickle.dump(self.checkpoints, open(CACHED_CHECKPOINTS_FILE, 'w'))


  # perform fast incremental updates using the lscp '-i' option
  def update_checkpoints(self):
    if not self.checkpoints:
      self.checkpoints = self.nilfs.lscp()
    else:
      last_checkpoint_id = self.checkpoints[-1]['cno']
      # start a 1 beyond last_checkpoint_id to prevent dups!!!
      new_checkpoints = self.nilfs.lscp(index=last_checkpoint_id+1)
      self.checkpoints.extend(new_checkpoints)

    # sanity check
    lst = [e['cno'] for e in self.checkpoints]
    assert lst == sorted(lst)


  # returns the checked-out mountpoint on success (or None on failure)
  # which represents the last mountpoint occurring BEFORE timestamp
  #
  # however, this isn't totally accurate, because NILFS timestamps only
  # have second-level granularity, but timestamps issued by client
  # applications could have microsecond granularity.  e.g., if the
  # actual timestamp of a snapshot is at 1:15.90, then NILFS stores it
  # as 1:15.  So checkout_snapshot(self, 1:15.10) will return that 1:15
  # snapshot, even though its ACTUAL timestamp (1:15.90) is after the
  # timestamp argument.  to be more safe, subtact 1 second from timestamp
  # BEFORE passing it into this function.
  def checkout_snapshot(self, timestamp):
    self.update_checkpoints() # make sure we're up-to-date!

    # TODO: optimize to binary search if necessary
    prev = None
    for e in self.checkpoints:
      if e['date'] > timestamp:
        break
      prev = e

    # prev stores the latest checkpoint with time <= timestamp
    target_checkpoint_num = prev['cno']
    target_checkpoint_date = prev['date']

    mountpoint = os.path.join(NILFS_SNAPSHOT_BASE, target_checkpoint_date.strftime("%Y.%m.%d-%H.%M.%S"))

    # fast path ...
    if target_checkpoint_num in self.active_snapshots:
      assert os.path.isdir(mountpoint)
      return mountpoint # already mounted (presumably)

    os.mkdir(mountpoint)

    # first make sure it's a snapshot, so we can mount it:
    if not prev['ss']:
      self.nilfs.chcp(target_checkpoint_num, True)
      prev['ss'] = True

    mount_cmd = 'sudo mount -t nilfs2 -n -o ro,cp=%d "%s" "%s"' % (target_checkpoint_num, NILFS_DEV_NAME, mountpoint)
    (status, output) = commands.getstatusoutput(mount_cmd)
    if output:
      print output

    if (status == 0):
      self.active_snapshots[target_checkpoint_num] = mountpoint
      return mountpoint
    else:
      return None


  # returns the path of the checked-out file
  def checkout_file(self, filename, timestamp):
    snapshot_dir = self.checkout_snapshot(timestamp)

    # find the version of filename within snapshot_dir
    # strip HOMEDIR_PREFIX off of filename ...
    assert filename.startswith(HOMEDIR_PREFIX)
    decapitated_fn = filename[len(HOMEDIR_PREFIX):]

    old_version_path = os.path.join(snapshot_dir, decapitated_fn)
    return old_version_path


  # This is kinda kludgy because it depends on event_fetcher.py
  def checkout_file_before_next_write(self, write_evt, sorted_write_events_lst):
    # Complex pre-conditions:
    # (TODO: eliminate checks if too slow)
    assert write_evt in sorted_write_events_lst
    assert sorted(sorted_write_events_lst, key=lambda e:e.timestamp) == sorted_write_events_lst
    for e in sorted_write_events_lst: assert write_evt.filename == e.filename

    # Retrieves the timestamp RIGHT BEFORE the next write to filename.  The
    # reason why we need to do this is due to pass-lite's write coalescing
    # optimization.  If we just get the snapshot at evt.timestamp, that might
    # not be the timestamp of the LAST write in a series of writes to the same
    # file descriptor.  Consider the case where it takes 10 seconds to
    # completely save a file foo.txt.  If the first write occurred at time t,
    # then evt.timestamp will be t, but the version at time t isn't the
    # complete foo.txt.  In order to get the complete foo.txt, we need to get
    # the version at time t+10.  However, we don't know that it took 10
    # seconds to write the file, since pass-lite coalesced all of the (tons
    # of) writes into ONE write at time t.  So the best we can do is to find
    # the NEXT time that this file was written to and return a timestamp right
    # before its timestamp.
    #
    # return None if this is the most recent write, so there's NO successor
    def get_before_next_write_timestamp():
      # TODO: optimize with a sub-linear search if necessary
      idx = sorted_write_events_lst.index(write_evt)
      num_writes = len(sorted_write_events_lst)

      assert 0 <= idx < num_writes

      # if we're the LAST one, then return None
      if idx == num_writes - 1:
        return None
      else:
        next_evt = sorted_write_events_lst[idx + 1]

        assert next_evt.timestamp - write_evt.timestamp >= ONE_SEC

        # subtract one second to get the "epsilon" before the next write
        ret = next_evt.timestamp - ONE_SEC
        return ret

    event_time = get_before_next_write_timestamp()
    if event_time:
      return self.checkout_file(write_evt.filename, event_time)
    else:
      # eee, the current working version IS what we want!
      return write_evt.filename


  def unmount_all_snapshots(self):
    for d in os.listdir(NILFS_SNAPSHOT_BASE):
      fullpath = os.path.join(NILFS_SNAPSHOT_BASE, d)
      if os.path.isdir(fullpath):
        commands.getstatusoutput('sudo umount ' + fullpath)
        os.rmdir(fullpath)


def exit_handler():
  global fvm
  fvm.memoize_checkpoints()
  fvm.unmount_all_snapshots()


if __name__ == '__main__':
  fvm = FileVersionManager()
  print fvm.checkout_snapshot(datetime.datetime(2011, 12, 15, 9, 0, 0))
  print fvm.checkout_snapshot(datetime.datetime(2011, 12, 15, 10, 0, 0))
  print fvm.checkout_snapshot(datetime.datetime(2011, 12, 15, 11, 0, 0))
  print fvm.checkout_snapshot(datetime.datetime(2011, 12, 15, 12, 0, 0))
  print fvm.checkout_snapshot(datetime.datetime(2011, 12, 15, 13, 0, 0))
  print fvm.checkout_snapshot(datetime.datetime(2011, 12, 15, 14, 0, 0))
  print fvm.checkout_snapshot(datetime.datetime(2011, 12, 15, 15, 0, 0))
  print fvm.checkout_snapshot(datetime.datetime(2011, 12, 15, 16, 0, 0))
  #fvm.unmount_all_snapshots()

  atexit.register(exit_handler)
  signal(SIGTERM, lambda signum,frame: exit(1)) # trigger the atexit function to run

  sys.exit(0)

  import time

  print 'updating ...',
  sys.stdout.flush()
  fvm.update_checkpoints()
  print len(fvm.checkpoints)
  time.sleep(5)

  print 'updating ...',
  sys.stdout.flush()
  fvm.update_checkpoints()
  print len(fvm.checkpoints)
  time.sleep(5)

  print 'updating ...',
  sys.stdout.flush()
  fvm.update_checkpoints()
  print len(fvm.checkpoints)

