# Installation instructions: Load as $PYTHONSTARTUP
# e.g., put this line in your .bashrc:
#   export PYTHONSTARTUP=~/BurritoBook/PythonLogger/pylogger.py 

# TODO: this is currently incomplete ... we need to figure out a way for
# _history_print to run on every type of command invocation, NOT just an
# expression evaluation (which sys.displayhook) does.

import sys, readline

def _history_print(arg):
  print 'history:'
  for i in range(1, readline.get_current_history_length() + 1):
    print readline.get_history_item(i)

sys.displayhook = _history_print

