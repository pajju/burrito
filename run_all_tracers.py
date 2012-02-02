#!/usr/bin/env python

# Top-level burrito start-up script
#
# Make this script executable and run at start-up time to run ALL tracer scripts!
#
# Go to System -> Preferences -> Startup Applications in the Fedora 14
# GNOME menu.  And create a new entry to execute:
#   <path to this script>

import os, time
from BurritoUtils import *

# Pause a bit before running incremental_integrator.py since that relies
# on the MongoDB database service already being up and running, and
# sometimes MongoDB might start slower than expected.
time.sleep(3)

LOG_BASEDIR = '/var/log/burrito'

PASS_LITE   = '/home/researcher/burrito/SystemTap/pass-lite.stp'

GUI_TRACER_BASE = "GUItracer"
GUI_TRACER  = '/home/researcher/burrito/GUItracing/%s.py' % (GUI_TRACER_BASE,)

INTEGRATOR_BASE = 'incremental_integrator'
INTEGRATOR  = '/home/researcher/burrito/%s.py' % (INTEGRATOR_BASE,)


assert os.path.isdir(LOG_BASEDIR)
assert os.path.isfile(PASS_LITE)
assert os.path.isfile(GUI_TRACER)
assert os.path.isfile(INTEGRATOR)


# Create a unique subdirectory session name consisting of the user's
# name and current time

SESSION_NAME = '%s-%d' % (os.getenv('USER'), get_ms_since_epoch())
d = os.path.join(LOG_BASEDIR, SESSION_NAME)
assert not os.path.isdir(d)
os.mkdir(d)


# rename the existing current-session/ symlink and add a new link to SESSION_NAME
cs = os.path.join(LOG_BASEDIR, 'current-session')
if os.path.exists(cs):
  os.rename(cs, os.path.join(LOG_BASEDIR, 'previous-session'))
os.symlink(SESSION_NAME, cs)


# kill old instances of GUItracer and run this first in the background ...
os.system("pkill -f %s" % (GUI_TRACER_BASE,))
os.system("python %s 2> %s/GUITracer.err &" % (GUI_TRACER, d))

# same with the integrator
os.system("pkill -f %s" % (INTEGRATOR_BASE,))
os.system("python %s %s -s %s 2> %s/integrator.err &" % (INTEGRATOR, d, SESSION_NAME,  d))

# Execute SystemTap
# (to prevent multiple simultaneous stap sessions from running, kill all
# other stap instances before launching ... otherwise if the user logs
# out and logs back in without first rebooting, MULTIPLE stap instances
# will be running, which is undesirable)
os.system("killall stap; stap -o %s/pass-lite.out -S 10 %s 2> %s/stap.err" % (d, PASS_LITE, d))
