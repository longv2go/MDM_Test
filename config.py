TOKEN_BITS = 256
MOBILE_UDID_BITS = 160
PUSH_MAGIC_BITS = 12

AGENT_DB_FILE = 'devices.db'
APNS_DB_FILE = 'apns.db'


AGENT_RPC_SERVER = '127.0.0.1'
AGENT_RPC_PORT = 4343

APNS_RPC_SERVER = '127.0.0.1'
APNS_RPC_PORT = 4342

AGENT_INIT_DEVICES_NUM = 2000
##############################
MULTI_AGENTS = False

UDID_STRING_LEN = 40 
UDID_PREFIX_LEN = 20 #range 1 - UDID_STRING_LEN

MDM_AGNET_POOL_THREAD_NUM = 100 
APNS_POOL_THREAD_NUM = 50

########## MDM server ###########
MDM_SERVER_HOST = '10.8.4.36'
MDM_SERVER_PORT =  10000
######## Test flags ########
TEST_MDM = True #if this flag set true, the AGENT_INIT_DEVICES_NUM would be disabled

PERFORMANCE_TEST = False 