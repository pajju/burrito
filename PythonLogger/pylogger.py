# Installation instructions: Load as $PYTHONSTARTUP
# e.g., put this line in your .bashrc:
#   export PYTHONSTARTUP=~/burrito/PythonLogger/pylogger.py 


# TODO: this script only partially works ... we need to figure out a way
# for _history_print to run on every type of command invocation, NOT just
# on expression evaluation (which sys.displayhook does).
#
# we are also approximating the timestamp of each invoked command by
# using the timestamp of the last evaluated expression, which is
# imprecise but the best we can do considering we're using
# sys.displayhook!

# Maybe I should instead just instrument IPython to log timestamped
# history entries, since it already keeps user input history!

'''
From Fernando Perez:

  The user input is read through raw_input, or its lower-level partner,
  the read method of sys.stdin.

  IPython itself logs all that to an sqlite history database, so you
  have all user inputs always, with timestamps and more.
'''

LOGFILE = open('/var/log/burrito/current-session/python.log', 'a')


import os, sys, readline

# inlined from BurritoUtils.py ...
import time, json, datetime

def get_ms_since_epoch():
  milliseconds_since_epoch = int(time.time() * 1000)
  return milliseconds_since_epoch

def to_compact_json(obj):
  # use the most compact separators:
  return json.dumps(obj, separators=(',',':'))


PID = os.getpid()

LAST_PRINTED_ENTRY = 1

def _history_print(arg):
  global LAST_PRINTED_ENTRY, PID
  history_length = readline.get_current_history_length()
  for i in range(LAST_PRINTED_ENTRY, history_length + 1):
    # TODO: this isn't quite accurate since we're using the same
    # timestamp for all the history entries we're printing on this
    # round, but it's the best we can do for now :/
    print >> LOGFILE, to_compact_json(dict(timestamp=get_ms_since_epoch(),
                                           command=readline.get_history_item(i),
                                           pid=PID))
    LOGFILE.flush()
  print arg
  LAST_PRINTED_ENTRY = history_length + 1

sys.displayhook = _history_print

