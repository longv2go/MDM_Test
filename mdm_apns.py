""" This is a server like the APNs
    it should has a device token manager, and send apn to some device
    to mdm_agent to triger mdm_agent
    request mdm command from mdm server """

import thread
import time
import SimpleXMLRPCServer
import xmlrpclib
import inspect
import random
import sqlite3
import threadpool
from mdm_log import *
from config import *
from twisted.internet import reactor, ssl
from twisted.internet.protocol import Protocol, Factory
from twisted.protocols.basic import LineReceiver
import struct
import base64
import traceback

try:
    from config import MULTI_AGENTS
except Exception, e:
    MULTI_AGENTS = False

_MODULE_ID = "__APNS__"

# _AGENT_RPC_SERVER = '10.8.4.30'
# _AGENT_RPC_PORT = 4343
# _RPC_SERVER_PORT = 4342

_APNS_PORT = 2096

_agent_rpc_proxy = xmlrpclib.ServerProxy("http://%s:%d" % (AGENT_RPC_SERVER, AGENT_RPC_PORT))

#xmlrpc functions called by mdm_agent
#all functions xml rpc server suply are sync
class ApnsRPCServer:

    def register(self, udid):

        token64 = ""
        try:
            token64 =  ApnsManager().register(udid)
            logMsg(_MODULE_ID, LOG_INFO, "registed udid [%s] ---- token64 [%s]" % (udid, token64))
        except Exception, e:
            logMsg(_MODULE_ID, LOG_WARING, "register exc, %s" % traceback.format_exc())

        return token64

    def register_agent(self, udid_prefix, host, port):
        """ This xml rpc method is used to register more mdm_agnet, every agent can active some 
        ios mdm devices, and there is only one mdm_agent"""

        if len(udid_prefix) != UDID_PREFIX_LEN:
            raise Exception("UDID prefix length invalid.")

        if not ApnsManager().did_agent_registed(udid_prefix):
            raise Exception("UDID prefix already registed.")

        rpc_proxy = xmlrpclib.ServerProxy("http://%s:%d") % (host, port)
        agent = MdmAgent(udid_prefix, host, port)

        ApnsManager().add_agent_for_udidpre(udid_prefix, agent)

###################
# Tip: not use
# #################
class MdmAgent:
    def __init__(self, udid_prefix, host, port):
        self.udid_prefix = udid_prefix
        self.host = host
        self.port = port
        self.prefix_len = len(udid_prefix)
   
        self.rpc_proxy = xmlrpclib.ServerProxy("http://%s:%d" % (host, port))
    
    def __str__(self):
        return "<MdmAgent> udid prefix: [%s], host[%s:%d]" % (self.udid_prefix, self.host, self.port)

##################################################
# Apn worker
# ################################################

class ApnWorkerProtocol(object):

    def worker_dead(self):
        pass

class ApnSendWorker(object):

    _ALIVE , _DEAD = range(2)
    _status = _ALIVE

    def __init__(self, delegate, host, port, id='W-0'):   
        self.delegate = None
        if isinstance(delegate, ApnWorkerProtocol):
            self.delegate = delegate

        try:
            self.agent_proxy = xmlrpclib.ServerProxy("http://%s:%d" % (AGENT_RPC_SERVER, AGENT_RPC_PORT))
            self.host = host
            self.port = port
            self.id = id
            self._status = self._ALIVE

        except Exception, e:
            logMsg(_MODULE_ID, LOG_WARING, "create worker(%s) faild. wrong param" % self.id)
            raise e
        else:
            logMsg(_MODULE_ID, LOG_DEBUG, "worke (%s) created" % self.id)

    def send_apn(self, udid):
        if self._status != self._ALIVE:
            logMsg(_MODULE_ID, LOG_WARING, "worker (%s) already dead in thread(%s) " % (self.id, thread.get_ident()))
            return
        logMsg(_MODULE_ID, LOG_DEBUG, "Aha, I am worker(%s) , start working" % self.id)
        try:
            self.agent_proxy.receive_apn(udid)
        except Exception, e:
            logMsg(_MODULE_ID, LOG_WARING, "<xmlrpc> call agent receive_apn failed.\n %s " % traceback.format_exc())
            self._worker_dead()

    def _worker_dead(self):
        logMsg(_MODULE_ID, LOG_WARING, "dead worker (%s) in thread(%s) " % (self.id, thread.get_ident()))
        self._status = self._DEAD
        if self.delegate is not None:
                self.delegate.worker_dead(self)

    def _do_send_apn(self, udid):
        pass   

class ApnsManager(ApnWorkerProtocol):

    def __new__(cls, *args, **kwargs):

        ''' A pythonic singleton '''
        if '_inst' not in vars(cls):
            cls._inst = super(ApnsManager, cls).__new__(cls, *args, **kwargs)
            cls._inst._single_init()
        return cls._inst

    def _single_init(self):
        self.devices = {}
        self.invalid_list = []

        #This value store the information about agents registed by mdm_agent, 
        #{"<udid_prefix>":<instance of class MdmAgent>}
        self.mdm_agents = {}

        try:
            self.db = sqlite3.connect(APNS_DB_FILE)
            self.curs = self.db.cursor()

            self._create_db()   
            self._loads_from_db()

            self.pool = threadpool.ThreadPool(APNS_POOL_THREAD_NUM)

            self.workers = []
            for i in xrange(APNS_POOL_THREAD_NUM):
                pass
                #self.workers.append(self.make_worker("W-%d" % i))
        except Exception, e:
            logMsg(_MODULE_ID, LOG_ERROR, "init apns device manager failed")
            raise e
        else:
            logMsg(_MODULE_ID, LOG_INFO, "init apns manager success, %s" % self)

    def __init__(self):
        pass

#manage the mdm agent which registe by mdm_agent.py
    def did_agent_registed(self, udid):
        return self.mdm_agents.has_key(udid)

    def add_agent_for_udidpre(self, udid, agent):
        self.mdm_agents[udid] = agent
        logMsg(_MODULE_ID, LOG_INFO, "registed mdm agent, %s" % agent)

    def remove_agent_for_udid(self, udid):
        pass 

        # udidpre = udid[:UDID_PREFIX_LEN - 1]
        # try:
        #     del self.mdm_agents[udidpre]
        # except KeyError, e:
        #     pass

    def _validate_agents(self):
        """ this method would check the self.mdm_agents"""
        return True

    def _create_db(self):
        self.curs.execute("""
            CREATE TABLE IF NOT EXISTS apns_devices (
                id INTEGER PRIMARY KEY,
                udid TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL UNIQUE
            )""")

    def _loads_from_db(self):
        if self.curs is not None:
            self.curs.execute('select id, udid, token from apns_devices')
            for row in self.curs.fetchall():
                self.devices[row[2]] = row[1]
        else:
            self.devices = {}
            #logMsg(_MODULE_ID, "db curs null")
            raise Exception("db curs null")

    def _update_device(self, token, udid, update=False):
        try:
            if update:
                self.curs.execute("update apns_devices set token='%s' where udid='%s' " % (token, udid))
            else:
                self.curs.execute("insert into apns_devices values (NULL, '%s', '%s')" % (udid, token))
        except Exception, e:
            logMsg(_MODULE_ID, LOG_INFO, "insert into error: %s" % e)

        self.db.commit()

    def _invalid_some_token(self):
        """ this method would random choose some device to invalid,
        and add this to feedback list"""
        pass

    def _update_some_token(self):
        """this method would random choose some device and change it's 
        token, and call agent token_update"""
        pass

    def register(self, udid):
        """ This method would remote called by mdm_agent, so remember decode the token in mdm_agent"""

        token64 = self._generate_token64()
        #I/O 
        self.devices[token64] = udid
        self._update_device(token64, udid)

        return token64

    def _generate_token64(self):
        t = random.getrandbits(TOKEN_BITS)
        hexstr = "%064x" % t
        #logMsg(_MODULE_ID, LOG_DEBUG, "token hexstr %s, %d, %c" % (hexstr, len(hexstr), hexstr[62]))
        bytes = bytearray.fromhex(hexstr)
        return base64.encodestring(str(bytes))

    def send_apn(self, token):

        token64 = base64.encodestring(token)
        udid = self.devices.get(token64)
        if udid is None:
            logMsg(_MODULE_ID, LOG_WARING, "mdmapn invalid token, [%s]" % token64)
        else:
            #this is user the worker to send 
            #
            # apn_worker = self.choose_worker()
            # req = threadpool.WorkRequest(apn_worker.send_apn, (udid,))
            # self.pool.putRequest(req)

            #THis is just use the function to send apn
            req = threadpool.WorkRequest(send_apn_worker, (udid,))
            self.pool.putRequest(req)


    def choose_worker(self):
        try:
            self.worker_index += 1
        except AttributeError, e:
            self.worker_index = 0

        self.worker_index = self.worker_index % len(self.workers)
        return self.workers[self.worker_index]

    def worker_dead(self, worker):
        logMsg(_MODULE_ID, LOG_DEBUG, "apn worker(%s) dead" % worker.id)
        if worker in self.workers:
            self.workers.remove(worker)
            self.make_worker("%s+" % worker.id)

    def make_worker(self, ident):
        try:
            worker = ApnSendWorker(self, AGENT_RPC_SERVER, AGENT_RPC_PORT, ident)
            self.workers.append(worker)
        except Exception, e:
            logMsg(_MODULE_ID, LOG_WARING, "make_work error, %s" % traceback.format_exc())
            raise

        return worker

    def make_worker2(self):
        proxy = xmlrpclib.ServerProxy("http://%s:%d" % (AGENT_RPC_SERVER, AGENT_RPC_PORT))
        def send_apn_worker(udid):
            logMsg(_MODULE_ID, LOG_INFO, "apns would send apn for udid [%s]\n" % udid)
            try:
                proxy.receive_apn(udid)
            except Exception, e:
                logMsg(_MODULE_ID, LOG_INFO, "<xmlrpc> call agent receive_apn failed.\n %s " % traceback.format_exc())
                ApnsManager().remove_agent_for_udid(udid)

        return send_apn_worker

def send_apn_worker(udid):
    logMsg(_MODULE_ID, LOG_INFO, "apns would send apn for udid [%s]\n" % udid)
    try:
        agent_proxy = xmlrpclib.ServerProxy("http://%s:%d" % (AGENT_RPC_SERVER, AGENT_RPC_PORT))
        ret = agent_proxy.receive_apn(udid)
        #logMsg(_MODULE_ID, "agent rpc return: %s\n" % ret)
    except Exception, e:
        logMsg(_MODULE_ID, LOG_INFO, "<xmlrpc> call agent receive_apn failed in thread(%s).\n %s " % (traceback.format_exc(), thread.get_ident()))
        #ApnsManager().remove_agent_for_udid(udid)


def start_apns_server():
    """ would be listen 2096 port, while got a apn from mdm server then 
    it should call the mdm_agent`s recevie_apn()"""

    factory = Factory()
    factory.protocol = APNSServer

    reactor.listenSSL(_APNS_PORT, factory, ssl.DefaultOpenSSLContextFactory(
                'apns.key', 'apns.crt'))
    reactor.run()
    

def start_xmlrpc():
    """ start a new thread to run xmlrpc server"""
    server = SimpleXMLRPCServer.SimpleXMLRPCServer((APNS_RPC_SERVER, APNS_RPC_PORT))
    server.register_instance(ApnsRPCServer())
    print "Listening on port [%d], thread [%d]" % (APNS_RPC_PORT, thread.get_ident())
    server.serve_forever()



###################################################################
# APNS server 
###################################################################


class APNSServer(Protocol):

    _APN_HEADER_LEN = 1 + 2 + 32 + 2 #cmd(1)+token_len(2)+token(32)+payload_len(2)
    
    def __init__(self):
        self.data = []

    def connectionMade(self):
        #logMsg(_MODULE_ID, "apns server get a connect from %r" % self.transport.client)
         print "apns server get a connect from " , self.transport.client
        

    def connectionLost(self, reason):
      #  logMsg(_MODULE_ID, "apns server disconnect from %r" % self.transport.client)
        pass

    def dataReceived(self, data):
       # print "apns server got data: %s" % data
        self.data += data

        if len(self.data) < self._APN_HEADER_LEN:
            return

        cmd, token_len, token, payload_len = struct.unpack_from("!BH32sH", data)

        if self._APN_HEADER_LEN + payload_len > len(self.data):
            return 

        #self.data at least has one complete apn
        offset = 0
        while offset < len(self.data):
            cmd, token_len, token, payload_len = struct.unpack_from("!BH32sH", data, offset)
            #cmd, ident, expiry, token_len, token = struct.unpack_from("!HiiH32s", data)
            if offset + self._APN_HEADER_LEN + payload_len > len(self.data):
                self.data = self.data[offset:]
                return 

            #logMsg(_MODULE_ID, LOG_DEBUG, "cmd:%d, token_len:%d, token:%s ---" % (cmd, token_len, base64.encodestring(token)))

            if cmd != 0 and cmd != 1:
                logMsg(_MODULE_ID, LOG_WARING, "Got an invalid mdm apn, %x" % data)
                self.data = []
            else:
                #process apn
                ApnsManager().send_apn(token)
                offset += self._APN_HEADER_LEN + payload_len

        if offset == len(self.data):
            self.data = []


if __name__ == '__main__':
    thread.start_new(start_xmlrpc, ())
    start_apns_server() #must on main thread
    time.sleep(20000)