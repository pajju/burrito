# This command runs before EVERY bash command, as dictated by bash_burrito.sh

import os, sys, time, json

LOGFILE = '/var/log/burrito/current-session/bash-history.log'

def get_ms_since_epoch():
  milliseconds_since_epoch = int(time.time() * 1000)
  return milliseconds_since_epoch


# Parse arguments:
bash_pid = int(sys.argv[1])
pwd      = sys.argv[2]
command  = sys.argv[3:] # note that this is a list!

result = dict(command=command, bash_pid=bash_pid, pwd=pwd,timestamp=get_ms_since_epoch())

assert os.path.isdir(pwd) # sanity check

# If you want to remove symlinks in pwd, use ...
#   os.path.realpath(pwd) # canonicalize the path to remove symlinks

# use the most compact separators:
compactJSON = json.dumps(result, separators=(',',':'))

f = open(LOGFILE, 'a')
print >> f, compactJSON
f.close()
