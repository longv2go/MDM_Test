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
from pprint import pprint

try:
    from config import MULTI_AGENTS
except Exception, e:
    MULTI_AGENTS = False

_MODULE_ID = "__APNS__"

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
        return "Done"

    def invalid_some_token(self, num):
        ApnsManager()._invalid_some_token(num)
        return "Done" #xmlrpc call method must give a return value

    def update_some_token(self, num):
        ApnsManager()._update_some_token(num)
        return "Done"

###################
# Tip: not use
# #################
class MdmAgent:
    def __init__(self, udid_prefix, host, port):
        self.udid_prefix = udid_prefix
        self.host = host
        self.port = port
        self.prefix_len = len(udid_prefix)
    
    def __str__(self):
        return "<MdmAgent> udid prefix: [%s], host[%s:%d]" % (self.udid_prefix, self.host, self.port)


class ApnsManager(object):

    def __new__(cls, *args, **kwargs):

        ''' A pythonic singleton '''
        if '_inst' not in vars(cls):
            cls._inst = super(ApnsManager, cls).__new__(cls, *args, **kwargs)
            cls._inst._single_init()
        return cls._inst

    def _single_init(self):
        #the devices: base64toekn --> dev_UDID
        self.devices = {}
        self.invalid_devices = {} #device which is already invalid but not send to feedback list
        self.feedbacked_devices = {}  #which send to feedback list device

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

    def _invalid_some_token(self, num):
        """ this method would random choose some device to invalid,
        and add this to feedback list"""

        keys = self.devices.keys()
        if num >= len(keys):
            fbkeys = keys
        else:
            fbkeys = random.sample(keys, num)

        for key in fbkeys: 
            logMsg(_MODULE_ID, LOG_DEBUG, "key: %s" % key) 
            d = self.devices.pop(key)
            self.invalid_devices.update(d)
            logMsg(_MODULE_ID, LOG_DEBUG, "add %s to feedback list" % d)

    def _update_some_token(self, num):
        """this method would random choose some device and change it's 
        token, and call agent token_update"""
        keys = self.devices.keys()
        if num >= len(keys):
            upkeys = keys
        else:
            upkeys = random.sample(keys, num)

        for key in upkeys:
            d = self.devices.pop(key)
            newtk = self._generate_token64()

            self.devices.newtk = d(key) #update the new token
            logMsg(_MODULE_ID, LOG_DEBUG, "update token %s --> %s" % (key, newtk))

            proxy = make_xmlproxy(AGENT_RPC_SERVER, AGENT_RPC_PORT)
            proxy.token_update(d(key), newtk)


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

#End class apns mananger

def make_xmlproxy(host, port):
    return xmlrpclib.ServerProxy("http://%s:%d" % (host, port))

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

    reactor.listenSSL(APNS_PORT, factory, ssl.DefaultOpenSSLContextFactory(
                'apns.key', 'apns.crt'))

    fbfactory = Factory()
    fbfactory.protocol = APNFeedbackServer

    reactor.listenSSL(APN_FEEDBACK_PORT, factory, ssl.DefaultOpenSSLContextFactory(
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

#######################
#APN Feedback Server
#######################

class APNFeedbackServer(Protocol):
    """docstring for APNFeedbackServer"""
    def __init__(self):
        pass

    def connectionMade(self):
        print "apn feedback get a connect from " , self.transport.client

        #make the feedback list
        mgr = ApnsManager()

        fblist = []
        for tk in mgr.invalid_devices.keys():
            fblist += self.make_fb_item(base64.decodestring(tk))

        mgr.feedbacked_devices.update(mgr.invalid_devices)
        mgr.invalid_devices = {}

        self.transport.write(fblist)
        self.transport.loseConnection()

    def make_fb_item(self, tk):
        logMsg(_MODULE_ID, LOG_DEBUG, "make feedback list item for token [%s]" % tk)
        t = time.mktime(time.gmtime())
        length = len(tk)
        item = struct.pack("!fH32s", t, length, tk)
        return item

    def connectionLost(self, reason):
        print "apn feedback lose a connect from " , self.transport.client

    def dataReceived(self, data):
        pass 

if __name__ == '__main__':
    thread.start_new(start_xmlrpc, ())
    start_apns_server() #must on main thread
    time.sleep(20000)
