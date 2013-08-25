import thread
import threading
import time
import SimpleXMLRPCServer
import xmlrpclib
import inspect
import uuid
import random
import httplib
import sqlite3
import threadpool
from config import *
from mdm_log import *
from plistlib import writePlistToString, readPlistFromString, Data
import base64
import traceback

_MODULE_ID = "__AGENT__"

# mdm server information
_MDM_PORT = 10000
#_MDM_HOST = '192.168.2.140'
_MDM_HOST = '10.8.4.36'
_MDM_CHECKIN_PATH = '/mdm/checkin'
_MDM_SERVER_PATH = '/mdm/server'

_MDM_CHECKIN_URL = 'http://%s:%d%s' % (_MDM_HOST, _MDM_PORT, _MDM_CHECKIN_PATH)
_MDM_SERVER_URL = 'http://%s:%d%s' % (_MDM_HOST, _MDM_PORT, _MDM_SERVER_PATH)
_MDM_TOPIC = '<some topic>'


_TEST_SITE_NAME = '<cookie>'

#notice that: the instance of ServerProxy should not shared between multithread
_apns_rpc_proxy = xmlrpclib.ServerProxy("http://%s:%d" % (APNS_RPC_SERVER, APNS_RPC_PORT))

def _init_module():
    """ init the agent module to register to mdm_apns"""
    pass

class DeviceManager(object):


    def __new__(cls, *args, **kwargs):

        ''' A pythonic singleton '''
        if '_inst' not in vars(cls):
            cls._inst = super(DeviceManager, cls).__new__(cls, *args, **kwargs)
            cls._inst._single_init()

        return cls._inst

    def _single_init(self):
        self.devices = {}
        try:
            #the db, curs should not shared between multithreads
            self.db = sqlite3.connect(AGENT_DB_FILE)
            self.curs = self.db.cursor()
            self.lock_curs = threading.Lock()

            self._create_db()
            self._loads_devices()

            self.pool = threadpool.ThreadPool(MDM_AGNET_POOL_THREAD_NUM)
            #pool.wait()
        except Exception, e:
            logMsg(_MODULE_ID,LOG_INFO, "init device manager failed, %s" % e)
            raise e
        else:
            logMsg(_MODULE_ID,LOG_INFO, "init device manager success")

    def __init__(self):
        pass

    def _create_db(self):
        self.curs.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY,
                udid TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL UNIQUE,
                push_magic TEXT NOT NULL,
                devid TEXT NOT NULL
            )""")


    def _loads_devices(self):
        """ load all device from database"""
        if self.curs is not None:
            self.curs.execute('select id, udid, token, devid from devices')
            for row in self.curs.fetchall():
                self.devices[row[1]] = Device(row[1], base64.decodestring(row[2]), row[3], row[0])
        else:
            self.devices = {}
        logMsg(_MODULE_ID, LOG_DEBUG, "all devices %d" % len(self.devices))

    def update_device(self, dev):
        if not isinstance(dev, Device):
             return
        try:
            #if self.lock_curs.acquire():
            self.curs.execute("insert into devices values (NULL, '%s', '%s', '%s', '%s')" % (dev.udid, base64.encodestring(dev.token), dev.push_magic, dev.devid))
             #   self.lock_curs.relese()

        except sqlite3.OperationalError, e:
            logMsg(_MODULE_ID,LOG_INFO, "insert into error: %s" % e)
        else:
            self.db.commit()

    def update_all_devices(self):
        for dev in self.devices:
            self.update_device(dev)

    def token_update(self, udid, token):
        dev = self.devices.get(udid)
        if isinstance(dev, Device):
            dev.token = token
            dev.token_update()

    def receive_apn(self, udid):
        logMsg(_MODULE_ID, LOG_DEBUG, "receive apn for udid [ %s ]" % udid)

        dev = self.devices.get(udid)
        if isinstance(dev, Device):
            requests = threadpool.makeRequests(mdm_worker, (dev,))
            [self.pool.putRequest(req) for req in requests]
        else:
            logMsg(_MODULE_ID, LOG_WARING, "receive apn, udid [%s] not found." % udid)

    def test_mdm(self):

        devs = self.devices.values()

        try:
            dev = devs.pop()
            while True:
                logMsg(_MODULE_ID,LOG_INFO, "test mdm udid [%s]" % dev.udid)
                requests = threadpool.makeRequests(mdm_worker, (dev,))
                [self.pool.putRequest(req) for req in requests]
                dev = devs.pop()
        except IndexError, e:
            pass 


    #run in xml server thread
    def new_device(self): 
        new_dev = Device()

        new_dev.register() #got the token from apns, use the global xml rpc
        new_dev.checkin()
        new_dev.token_update()

        self.devices[new_dev.udid] = new_dev
        self.update_device(new_dev) #use the self.curs 

_WORKER_DEV = {}
def mdm_worker(dev):
    tid = thread.get_ident()

    tid2 = _WORKER_DEV.get(dev.udid, None)
    if tid2:
        logMsg(_MODULE_ID, LOG_DEBUG, "got a error udid[%s] work in the deferent thread [%s <> %s]" % (dev.udid, tid, tid2))
    else:
        _WORKER_DEV[dev.udid] = tid

    logMsg(_MODULE_ID, LOG_DEBUG, "mdm worker start working at [%s], udid [%s] " % (thread.get_ident(), dev.udid))
    if not isinstance(dev, Device):
        logMsg(_MODULE_ID, LOG_WARING, "Kao! you give me none Device object, %s" % dev)
        return

    try:
        dev.process_mdm()
    except Exception, e:
        logMsg(_MODULE_ID, LOG_WARING, "mdm_worker error %s\n" % traceback.format_exc())

    logMsg(_MODULE_ID, LOG_INFO, "udid [%s] execute cmds finished.\n" % dev.udid)

 
MDM_RET_SUCCESS, MDM_RET_ERROR, MDM_RET_NOTNOW = range(3)


class Device:
    """ This class representing the iOS or iPad devices"""

    def __init__(self, udid=None, token=None, devid=None, id=0):
        self.id = id
        # if udid is None:
        #     self.udid = self._generate_udid()
        # else:
        #     self.udid = udid

        # if devid is None:
        #     self.devid = self._generate_devid()
        # else:
        #     self.devid = devid
        self.udid = udid or self._generate_udid()
        self.devid = devid or self._generate_devid() 

        self.token = token
        self.push_magic = self._generate_push_magic()

        self.commands = []

        #cmd: this would be a dict,
        #'cmd':'<mdm-RequestType>'
        #'cmd_uuid':'<uuid> (generate by mdm server)'
        #'body':<the whole plist come from mdm server>
        self.current_cmd = ''
        self.init_cmd_processer();

    def _generate_udid(self):
        a = random.getrandbits(MOBILE_UDID_BITS)
        return "%x" % a

    def _generate_push_magic(self):
        return "%s" % uuid.uuid1()

    def _generate_devid(self):
        a = random.getrandbits(64)
        return "%x" % a

    def load(self):
        """ load information from database (device), every colum in this table is a device
        instance"""
        pass

    def save(self):
        pass

    def register(self):
        """ register to apns server, this would be call a xmlrpc method in 
        apns server and would generate colume in database <udid -- token>"""

        #logMsg(_MODULE_ID, "register udid [%s] " % self.udid)
        token64 = _apns_rpc_proxy.register(self.udid)
        self.token = base64.decodestring(token64)

    def unregister(self):
        pass

    def checkin(self):
        """ process mdm checkin protocol """
        ck = dict(
            MessageType="Authenticate",
            Topic="<some topic>",
            UDID=self.udid)

        conn = httplib.HTTPConnection(_MDM_HOST, _MDM_PORT)
        path = "%s?user=mdm_agent&devid=%s" % (_MDM_CHECKIN_PATH, self.devid)
        self._set_http_request(conn, path, ck)
        rep = conn.getresponse()
        rep.read()

        if rep.status != 200:
            raise Exception("Checkin failed, http code (%s)" % rep.status)

    def token_update(self):

        tu = dict(MessageType='TokenUpdate',
            Topic=_MDM_TOPIC,
            UDID=self.udid,
            Token=Data(self.token),
            PushMagic=self.push_magic,
            UnLockToken="unlock_token")

        conn = httplib.HTTPConnection(_MDM_HOST, _MDM_PORT)
        conn.request('PUT',_MDM_CHECKIN_PATH, body=writePlistToString(tu), headers=dict(Cookie="__somecookie__=" + _TEST_SITE_NAME))
        #self._set_http_request(conn, _MDM_CHECKIN_PATH, tu)
        rep = conn.getresponse()
        rep.read()
        if rep.status != 200:
            raise Exception("token update failed, http code (%s)" % rep.status)

    def _set_http_request(self, conn, path, body_dict):

        try:
            conn.request('PUT',path, body=writePlistToString(body_dict), headers=dict(Cookie="__somecookie__=" + _TEST_SITE_NAME))
        except Exception, e:
            logMsg(_MODULE_ID, LOG_WARING, "set_http_rquest error, %s" % e)

    def checkout(self):
        pass

################################################
# These method would process mdm protocol
################################################

    def process_mdm(self):
        logMsg(_MODULE_ID, LOG_INFO, "\nstart process mdm, udid(%s)" % self.udid)

        conn = httplib.HTTPConnection(_MDM_HOST, _MDM_PORT)

        self.current_cmd, resp = self.query_cmd(conn)
        while self.current_cmd:
            #parse xml
            result =  self._execute_cmd(self.current_cmd, resp)
            self.current_cmd, resp = self.query_cmd(conn, result)

        # logMsg(_MODULE_ID, LOG_INFO, "udid [%s] execute cmds finished.\n" % self.udid)

    def query_cmd(self, conn, response=None):
        """ when got an apn, apn server triger the device to request the mdm 
        server a cmd, this method would called by apns server through xmlrpc"""

        if not isinstance(conn, httplib.HTTPConnection):
            return None
        if response is None:
            response = dict(Status="Idle", UDID=self.udid)

        #logMsg(_MODULE_ID, "body dict : %s " % response)
        conn.request('PUT', _MDM_SERVER_PATH, body=writePlistToString(response), headers=dict(Cookie="__somecookie__=" + _TEST_SITE_NAME))
        
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 300:
            logMsg(_MODULE_ID, LOG_WARING, "cmd request failed, http code (%d) , udid [%s]" % (resp.status, self.udid))
            raise Exception("cmd request failed , udid [%s]" % self.udid)

        request_type = None
        pl = None

        try:
            #when the last command executed, the mdm server would send a empty response,
            #this line code would raise a ExpatError 
            pl = readPlistFromString(data) 

            request_type = pl["Command"]["RequestType"]
            #request_type = pl.get("Command").get("command")
            logMsg(_MODULE_ID, LOG_DEBUG, "query cmd, [%s], udid [%s]" % (request_type, self.udid))
        except Exception, e:
            # logMsg(_MODULE_ID, LOG_INFO, "udid [%s] execute cmds finished.\n" % self.udid)
            pass

        return (request_type, pl)


    def random_cmd_result(self):
        # results = dict(
        #     MDM_RET_NOTNOW="NotNow",
        #     MDM_RET_ERROR="Error",
        #     MDM_RET_SUCCESS="Acknowledged")
        # MDM_RET_SUCCESS, MDM_RET_ERROR, MDM_RET_NOTNOW = range(3)

        results = ("Acknowledged","Error", "NotNow")

        ret = random.randint(0, 1)
        return  (ret, results[ret])

    def process_cmd_DL(self, pl):
        cmd_uuid = pl.get("CommandUUID")
        logMsg(_MODULE_ID, LOG_INFO, "processing [DeviceLock], cmd [%s], udid[%s]" % (cmd_uuid, self.udid))

        ret, status = self.random_cmd_result()
        result = dict(Status=status,
            UDID=self.udid,
            CommandUUID=cmd_uuid)

        if ret == MDM_RET_ERROR:
            result["ErrorChain"] = list("sorrorrrry")
        elif ret == MDM_RET_NOTNOW:
            pass
        else:
            pass

        return result

    def process_cmd_CP(self, pl):
        cmd_uuid = pl.get("CommandUUID")
        logMsg(_MODULE_ID, LOG_INFO, "processing [ClearPasscode], cmd [%s], udid[%s]" % (cmd_uuid, self.udid))
        
        ret, status = self.random_cmd_result()
        result = dict(Status=status,
            UDID=self.udid,
            CommandUUID=pl.get("CommandUUID"))

        if ret == MDM_RET_ERROR:
            result["ErrorChain"]=list("sorrorrrry")
        elif ret == MDM_RET_NOTNOW:
            pass
        else:
            pass

        return result

    def process_cmd_IAL(self, pl):
        cmd_uuid = pl.get("CommandUUID")
        logMsg(_MODULE_ID, LOG_INFO, "processing [InstalledApplicationList], cmd [%s], udid[%s]" % (cmd_uuid, self.udid))

        ret, status = self.random_cmd_result()
        result = dict(Status=status,
            UDID=self.udid,
            CommandUUID=pl.get("CommandUUID"))
    
        ret = MDM_RET_SUCCESS
        if ret == MDM_RET_ERROR:
            result["ErrorChain"] = list("sorrorrrry")
        elif ret == MDM_RET_NOTNOW:
            pass
        elif ret == MDM_RET_SUCCESS:
            result["InstalledApplicationList"]=[
                dict(Identifier="motionpro.arraynetworks.com.cn",
                    Version="1.0",
                    ShortVersion="0.9",
                    Name="MotionPro",
                    BundleSize=19*1024,
                    DynamicSize=0),
                
                dict(Identifier="goodapp.arraynetworks.com.cn",
                    Version="1.0",
                    ShortVersion="0.9",
                    Name="GoodApp",
                    BundleSize=2*1024,
                    DynamicSize=1)]
                
        return result

    def process_mdm_RTR(self, pl):
        cmd_uuid = pl.get("CommandUUID")
        logMsg(_MODULE_ID, LOG_INFO, "processing [Restrictions], cmd [%s], udid[%s]" % (cmd_uuid, self.udid))

        ret, status = self.random_cmd_result()
        result = dict(Status=status,
            UDID=self.udid,
            CommandUUID=pl.get("CommandUUID"))

        if ret == MDM_RET_ERROR:
            result["ErrorChain"]=list("sorrorrrry")
        elif ret == MDM_RET_NOTNOW:
            pass
        elif ret == MDM_RET_SUCCESS:
            result["ManagedApplicationList"]=dict(
                restrictedBool=dict(
                        allowSimple=dict(
                                value=False
                            )
                    ),

                # restrictedValue=dict(
                #     )
            )

        return result

    def process_mdm_MAL(self, pl):
        cmd_uuid = pl.get("CommandUUID")
        logMsg(_MODULE_ID, LOG_INFO, "processing [ManagedApplicationList], cmd [%s], udid[%s]" % (cmd_uuid, self.udid))
        ret, status = self.random_cmd_result()
        result = dict(Status=status,
            UDID=self.udid,
            CommandUUID=pl.get("CommandUUID"))

        if ret == MDM_RET_ERROR:
            result["ErrorChain"]=list("sorrorrrry")
        elif ret == MDM_RET_NOTNOW:
            pass
        elif ret == MDM_RET_SUCCESS:
            result["GlobalRestrictions"]={
                "motionpro.arraynetworks.com.cn":dict(
                    status="Managed",
                    ManagementFlags=1,
                    UnusedRedemptionCode="good")
            }
        return result

    def default_cmd_processer(self, pl):
        logMsg(_MODULE_ID, LOG_DEBUG, "what!!!!!!, not implment [%s] yet" % pl.get("Command").get("RequestType"))

        result = dict(Status="Error", 
            UDID=self.udid,
            CommandUUID=pl.get("CommandUUID"),
            ErrorChain=["Reason", "I am so so sooooooooo sorrrrrrrrrrrrrrry!"])

        return result

    def init_cmd_processer(self):

        self._cmd_processer_map = { 
            "DeviceLock":self.process_cmd_DL,
            "ClearPasscode":self.process_cmd_CP,
            "InstalledApplicationList":self.process_cmd_IAL,
            "Restrictions":self.process_mdm_RTR,
            "ManagedApplicationList":self.process_mdm_MAL
        }

    def _execute_cmd(self, request_type, pl):
        """ according to ReqestType just return a random result, and do some log thing"""
        return self._cmd_processer_map.get(request_type, self.default_cmd_processer)(pl)


    def _send_mdm_msg(self, url, plist_data):
        if not isinstance(plist_data, dict):
            raise TypeError("Not a plist object")
        else:
            conn = httplib.HTTPConnection(url)
            conn.request('PUT', url, writePlistToString(plist_data))
            return readPlistFromString(conn.getresponse())
            
    def __str__(self):
        return "<Device> udid=%s" % self.udid


#These function all xmlrpc called by apns server

class AgentRPCServer:

    #xmlrpc method must has a return
    def token_update(self, udid, token):
        DeviceManager().token_update(udid, token)
        return "Done"
        

    def receive_apn(self, udid):
        #logMsg(_MODULE_ID, LOG_DEBUG, "receive_apn, udid [ %s ] \n" % udid)

        DeviceManager().receive_apn(udid)   
        return "Done"

    def new_device(self):
        DeviceManager().new_device()
        return "Done"

    def test_mdm(self):
        DeviceManager().test_mdm()
        return "Done"

def start_xmlrpc():
    """ start a new thread to run xmlrpc server"""
    server = SimpleXMLRPCServer.SimpleXMLRPCServer((AGENT_RPC_SERVER, AGENT_RPC_PORT))
    server.register_instance(AgentRPCServer())
    print "Listening on port [%d], thread [%d]" % (AGENT_RPC_PORT, thread.get_ident())
    server.serve_forever()

def create_device_worker(a):
    logMsg(_MODULE_ID, LOG_DEBUG, " start create new devices")
    dm = DeviceManager()
    dm.new_device()

def create_devices(num):
    dm = DeviceManager()
    for i in xrange(num):
    #     requests = threadpool.makeRequests(create_device_worker, ("a",))
    #     [dm.pool.putRequest(req) for req in requests]
        dm.new_device()

if __name__ == '__main__': 
    thread.start_new(start_xmlrpc, ())

    if TEST_MDM:
        #stack here, should C-c to cancel, before test_mdm, it should add some a lot of devices and add lots of tasks
        DeviceManager().test_mdm()
    else:
        create_devices(AGENT_INIT_DEVICES_NUM)

    time.sleep(20000)
