import datetime

n = datetime.datetime.now()

for i in range(10):
  f = open('output-%d.txt' % i, 'w')
  f.write('HAHAHA\n')
  f.write(str(n))
  f.write('\n')
  f.close()

