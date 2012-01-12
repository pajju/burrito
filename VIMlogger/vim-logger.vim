" When you make a visual selection in vim and then press the 'm' key,
" this script will "bookmark" the line number range of your selection to
" LOGFILE, so that if you make annotations, they can be linked to your
" current selection context.
"
" To include this file, add the following line to the end of your .vimrc:
"
" so /home/researcher/BurritoBook/VIMlogger/vim-logger.vim

" vmap means only activate this command in visual mode
vmap m :python log_bookmark()<CR>


" Auto-commands for triggering actions based on text editor events:
" http://vimdoc.sourceforge.net/htmldoc/autocmd.html
au BufEnter * :python log_buf_enter()

python << EOF

import os, vim, time, json

LOGFILE = '/var/log/BurritoBook/current-session/vim-trace.log'

def get_ms_since_epoch():
  milliseconds_since_epoch = int(time.time() * 1000)
  return milliseconds_since_epoch


def log_json(dat):
  f = open(LOGFILE, 'a')
  # use the most compact separators:
  compactJSON = json.dumps(dat, separators=(',',':'))
  f.write(compactJSON)
  f.write('\n')
  f.close()


def log_buf_enter():
  curFilename = vim.eval('expand("%")')
  # punt when you have a "fake" buffer like a help file ...
  if not curFilename: return

  # VERY IMPORTANT: get the absolute path so that we can uniquely identify the file!
  fnAbspath = os.path.abspath(curFilename)

  dat = dict(event='BufEnter', timestamp=get_ms_since_epoch(), filename=fnAbspath, pid=os.getpid())
  log_json(dat)


def reset_visual_mode_settings():
  # resets original highlight colors:
  vim.command(":highlight Visual ctermfg=NONE guifg=NONE ctermbg=NONE guibg=NONE")
  # reset 'v' key mapping:
  vim.command('vunmap v')


def log_bookmark():
  s = vim.current.buffer.mark('<')
  vStartLine = s[0]
  vStartCol  = s[1] + 1 # Python is 0-indexed, so inc to make it 1-indexed

  e = vim.current.buffer.mark('>')
  vEndLine   = e[0]
  vEndCol    = e[1] + 1 # Python is 0-indexed, so inc to make it 1-indexed

  curFilename = vim.eval('expand("%")')
  # punt when you have a "fake" buffer like a help file ...
  if not curFilename: return

  # VERY IMPORTANT: get the absolute path so that we can uniquely identify the file!
  fnAbspath = os.path.abspath(curFilename)

  # Highlight the marked selection in red
  # (NB: I've only tested in a terminal so far, not in a GUI version of VIM)
  vim.command(":highlight Visual ctermfg=Red guifg=Red ctermbg=White guibg=White")

  # the 'gv' command restores the last selection!
  vim.eval('feedkeys("gv")')

  # remap 'v' key to reset_visual_mode_settings()
  # so that when the user hits 'v' again, everything goes back to normal :)
  vim.command('vmap v :python reset_visual_mode_settings()<CR>')


  f = open(LOGFILE, 'a')

  dat = dict(event='mark', timestamp=get_ms_since_epoch(), filename=fnAbspath,
             start_line=vStartLine, start_col=vStartCol,
             end_line=vEndLine, end_col=vEndCol, pid=os.getpid())
  log_json(dat)

EOF
