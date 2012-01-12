import time, json, datetime

def get_ms_since_epoch():
  milliseconds_since_epoch = int(time.time() * 1000)
  return milliseconds_since_epoch

def to_compact_json(obj):
  # use the most compact separators:
  return json.dumps(obj, separators=(',',':'))

# this is dumb since mongodb stores datetimes internally as int64s!!!
def encode_datetime(t):
  return datetime.datetime.fromtimestamp(float(t) / 1000)


import os

HOMEDIR = os.environ['HOME']
assert HOMEDIR

def prettify_filename(fn):
  # abbreviate home directory:
  if fn.startswith(HOMEDIR):
    fn = '~' + fn[len(HOMEDIR):]
  return fn

