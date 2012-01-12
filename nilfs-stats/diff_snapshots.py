# Parses snapshot summary pickle files in SNAPSHOT_DIR

import os, cPickle

SNAPSHOT_DIR = '/tmp/nilfs-snapshots/pickles-backup/'

MIN_INDEX = 21     # the first snapshot where shit doesn't appear whacked
MAX_INDEX = 159496 # maximum index we're using in our USENIX experiments


# Returns a dict with:
#   'only_left':  list of files that are only in left
#   'only_right': list of files that are only in right
#   'diffs':      list of files that differed between left and right
def diff_snapshots(idx1, idx2):
  ret = {}

  pickle1 = SNAPSHOT_DIR + str(idx1) + '.pickle'
  pickle2 = SNAPSHOT_DIR + str(idx2) + '.pickle'

  assert os.path.isfile(pickle1)
  assert os.path.isfile(pickle2)

  snapshot1 = cPickle.load(open(pickle1))
  snapshot2 = cPickle.load(open(pickle2))

  # sanity checks
  assert snapshot1['index'] == idx1
  assert snapshot2['index'] == idx2

  snapshot1_files = set(snapshot1['files'].iterkeys())
  snapshot2_files = set(snapshot2['files'].iterkeys())

  only_in_1 = snapshot1_files - snapshot2_files
  ret['only_left'] = sorted(only_in_1)

  only_in_2 = snapshot2_files - snapshot1_files
  ret['only_right'] = sorted(only_in_2)

  ret['diffs'] = []

  # check files in common for diffs based on md5 checksum:
  for f in snapshot1_files.intersection(snapshot2_files):
    if snapshot1['files'][f] != snapshot2['files'][f]:
      ret['diffs'].append(f)
  
  return ret


# return the files changed that AREN'T part of dot directories and
# aren't dotfiles
def non_dotfiles_changed(diff_dict):
  ret = []
  for f in (diff_dict['only_left'] + diff_dict['only_right'] + diff_dict['diffs']):
    # dot directory!!!
    if f.startswith('.'): continue

    bn = os.path.basename(f)
    if bn.startswith('.'): continue

    ret.append(f)

  return ret


for i in range(MIN_INDEX, MAX_INDEX+1):
  diffs = diff_snapshots(i, i+1)
  real_diffs = non_dotfiles_changed(diffs)
  if len(real_diffs):
    print i+1

