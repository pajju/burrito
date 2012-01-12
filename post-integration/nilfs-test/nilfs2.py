# Code originally taken from the TimeBrowse project:
#   http://sourceforge.net/projects/timebrowse/
# and then adapted by Philip Guo

#!/usr/bin/env python
#
# copyright(c) 2011 - Jiro SEKIBA <jir@unicus.jp>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#

"""NILFS2 module"""

__author__    = "Jiro SEKIBA"
__copyright__ = "Copyright (c) 2011 - Jiro SEKIBA <jir@unicus.jp>"
__license__   = "LGPL"
__version__   = "0.6"

import commands
import re
import datetime

class NILFS2:
    # if you don't pass in a device name, nilfs tools will look in
    # /proc/mounts, so if there's exactly ONE nilfs FS mounted on
    # your machine, then you're fine!
    def __init__(self, device=''):
        self.cpinfo_regex = re.compile(
            r'^ +([1-9]|[1-9][0-9]+) +([^ ]+ [^ ]+) +(ss|cp) +([^ ]+) +.*$',
            re.M)
        self.device = device

    def __run_cmd__(self, line):
        result = commands.getstatusoutput(line)
        if result[0] != 0:
            raise Exception(result[1])
        return result[1]

    def __parse_lscp_output__(self, output):
        a = self.cpinfo_regex.findall(output)

        a = [ {'cno'  : int(e[0]),
               'date' : datetime.datetime.strptime(e[1], "%Y-%m-%d %H:%M:%S"),
               'ss'  : e[2] == 'ss'}
               for e in a if e[3] != 'i' ] # don't count internal ('i') checkpoints

        if not a:
            return []

        return a
        
        '''
        # Drop checkpoints that have the same timestamp with its
        # predecessor.  If a snapshot is present in the series of
        # coinstantaneous checkpoints, we leave it rather than plain
        # checkpoints.
        prev = a.pop(0)
        if not a:
            return [prev]

        ss = prev if prev['ss'] else None
        l = []
        for e in a:
            if e['date'] != prev['date']:
                l.append(ss if ss else prev)
                ss = None
            prev = e
            if prev['ss']:
                ss = prev
        l.append(ss if ss else a[-1])
        '''
        return l

    def lscp(self, index=1):
        result = self.__run_cmd__("lscp -i %d %s" % (index, self.device))
        return self.__parse_lscp_output__(result)

    def chcp(self, cno, ss=False):
        line = "chcp cp "
        if ss:
            line = "chcp ss "
        line += self.device + " %i" % cno
        return self.__run_cmd__(line)

    def mkcp(self, ss=False):
        line = "mkcp"
        if ss:
            line += " -s"
        line += " " + self.device
        return self.__run_cmd__(line)


if __name__ == '__main__':
  import sys
  nilfs = NILFS2()
  all_checkpoints = nilfs.lscp()

  prev = None
  for e in all_checkpoints:
    print e['cno'], e['date'],
    if prev and prev['date'] == e['date']:
      print "UGH!"
    else:
      print

    prev = e

