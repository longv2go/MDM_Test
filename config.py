
######## Test flags ########
AGENT_INIT_DEVICES_NUM = 0

TEST_MDM = True #if this flag set true, the AGENT_INIT_DEVICES_NUM would be disabled

PERFORMANCE_TEST = False #not use
MULTI_AGENTS = False #not use

MDM_AGNET_POOL_THREAD_NUM = 100 
APNS_POOL_THREAD_NUM = 50

###### APN server ###########
APNS_SERVER = "0.0.0.0"
APNS_PORT = 2096

APN_FEEDBACK_SERVER = "0.0.0.0"
APN_FEEDBACK_PORT = 2097

########## MDM server ###########
MDM_SERVER_HOST = '10.8.4.36'
MDM_SERVER_PORT =  10000

MDM_SERVER_PATH = '/mdm/server'
MDM_CHCEKIN_PATH = '/mdm/checkin'

##################################
TOKEN_BITS = 256
MOBILE_UDID_BITS = 160
PUSH_MAGIC_BITS = 12

AGENT_DB_FILE = 'devices.db'
APNS_DB_FILE = 'apns.db'


AGENT_RPC_SERVER = '127.0.0.1'
AGENT_RPC_PORT = 4343

APNS_RPC_SERVER = '127.0.0.1'
APNS_RPC_PORT = 4342

UDID_STRING_LEN = 40 
UDID_PREFIX_LEN = 20 #range 1 - UDID_STRING_LEN