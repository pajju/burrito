# Change all checkpoints into snapshots

# (this takes quite a while to run, so hopefully we only need to do it once)
import commands, sys

MAX_INDEX = 159496 # maximum index we're using in our USENIX experiments

for i in range(1, MAX_INDEX+1):
  (status, output) = commands.getstatusoutput('sudo chcp ss %d' % i)
  if i % 1000 == 0:
    print i

