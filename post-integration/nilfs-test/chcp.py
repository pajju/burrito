# Change ALL checkpoints to snapshots (and vice versa)

import nilfs2
n = nilfs2.NILFS2()

for e in n.lscp():
  if not e['ss']:
    n.chcp(e['cno'], True)

