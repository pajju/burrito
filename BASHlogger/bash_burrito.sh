# To use, add the following line in ~/.bashrc:
# source /home/researcher/BurritoBook/BASHlogger/bash_burrito.sh

# Trick to run a Python hook BEFORE executing the bash command.
# Source: http://www.davidpashley.com/articles/xterm-titles-with-bash.html

# Note: This hack will only work in bash 3.1 or greater due to an
# interaction between $BASH_COMMAND and DEBUG traps in earlier versions.

# Don't quote $BASH_COMMAND so that it can take up as many argv spots as it needs
#
# Also don't execute the Python logger for 'printf' commands, since bash
# calls printf after *every* command to pretty-print the new prompt,
# so those calls are useless to track!
trap 'if [[ ${BASH_COMMAND%% *} != "printf" ]]; then python /home/researcher/BurritoBook/BASHlogger/bash_burrito_to_json.py "$BASHPID" "$PWD" $BASH_COMMAND; fi' DEBUG


# Note that setting $PROMPT_COMMAND like they do here ...
#   http://stackoverflow.com/questions/945288/saving-current-directory-to-bash-history
# is an inferior choice since PROMPT_COMMAND runs AFTER the command
# finishes running.
