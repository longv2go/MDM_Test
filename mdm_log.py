import os, time
from config import PERFORMANCE_TEST 

on = True
off = False

LOG_DEBUG, LOG_INFO, LOG_WARING, LOG_ERROR = range(4)
LOG_LEVEL = LOG_DEBUG

_LOG_ID = ["debug", "info", "waring", "error"]


_LOG_FILE = '%s/log.txt' % os.path.abspath(os.curdir)
_fno = file(_LOG_FILE, 'a')

__LOGS = []

def logMsg(id, level=LOG_INFO, msg=None):
    if LOG_LEVEL <= level:
        log_str = "[%s]---[%s] <%s> %s\n" % (time.ctime(), id, _LOG_ID[level], msg)
        if PERFORMANCE_TEST:
            __LOGS.append(log_str)
        else:
            _fno.write("[%s]---[%s] <%s> %s\n" % (time.ctime(), id, _LOG_ID[level], msg))
            _fno.flush()
    else:
        pass

def flushLogs():
    for log in __LOGS:
        _fno.write(log)

    _fno.flush()
