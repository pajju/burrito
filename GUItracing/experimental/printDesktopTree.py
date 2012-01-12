# Prints the entire f***ing desktop tree

import pyatspi

# get the Registry singleton
reg = pyatspi.Registry()

# get desktop
desktop = reg.getDesktop(0)
 
def printAndRecurse(elt, indents=2):
  for (i, child) in enumerate(elt):
    print (' ' * (indents+2)), i, child
    printAndRecurse(child, indents+2)


for app in desktop:
  if app:
    print app
    printAndRecurse(app)

