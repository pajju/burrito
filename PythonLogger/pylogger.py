# Installation instructions: Load as $PYTHONSTARTUP
# e.g., put this line in your .bashrc:
#   export PYTHONSTARTUP=~/BurritoBook/PythonLogger/pylogger.py 

# TODO: this is currently incomplete ... we need to figure out a way for
# _history_print to run on every type of command invocation, NOT just an
# expression evaluation (which sys.displayhook) does.

'''
From Fernando Perez:

  The user input is read through raw_input, or its lower-level partner,
  the read method of sys.stdin.

  IPython itself logs all that to an sqlite history database, so you
  have all user inputs always, with timestamps and more.
'''

# Maybe I should instead just use IPython to keep the user input history!


import sys, readline

def my_read(s):
  global _orig_stdin_read
  _orig_stdin_read(s)

_orig_stdin_read = sys.stdin.read
sys.stdin.read = my_read


def _history_print(arg):
  print 'history:'
  for i in range(1, readline.get_current_history_length() + 1):
    print readline.get_history_item(i)

sys.displayhook = _history_print

