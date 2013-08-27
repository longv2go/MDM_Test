#-*- coding:utf8-*-
import cmd
import os
import sys
import subprocess
import xmlrpclib
from config import *
import socket

def apns_rpc_proxy():
    return xmlrpclib.ServerProxy("http://%s:%d" % (APNS_RPC_SERVER, APNS_RPC_PORT))
def agent_rpc_proxy():
    return xmlrpclib.ServerProxy("http://%s:%d" % (AGENT_RPC_SERVER, AGENT_RPC_PORT))

class CLI(cmd.Cmd):
    def __init__(self):
        cmd.Cmd.__init__(self)
        self.prompt = "> "    # define command prompt
        self.intro = """Welcome to MDM test CLI, please make sure the agent and apns already running.\n\
    type ? to show more help information \n\
    type !<cmd> to run shell <cmd>\n\
    type q or quit to exit this CLI"""

    def do_add(self, num):
        agent = agent_rpc_proxy()
        try:
            for i in xrange(int(num)):
                agent.new_device()
        except socket.error, e:
            print  "the agent xmlrpc(%s:%d) not running" % (AGENT_RPC_SERVER, AGENT_RPC_PORT)
        

    def help_add(self):
        print "syntax: add count -- add <count> devices to mdm server"

    def do_feedback(self, num):
        try:
            apns_rpc_proxy().invalid_some_token(int(num))
        except socket.error, e:
            print "the apns xmlrpc(%s:%d) not running" % (APNS_RPC_SERVER, APNS_RPC_PORT)
            
    def help_feedback(self):
        print "syntax: feedback count -- invalide <count> devices token, and add them to feedback list"

    def do_uptoken(self, num):
        try:
            apns_rpc_proxy().update_some_token(int(num))
        except Exception, e:
            print "the apns xmlrpc(%s:%d) not running" % (APNS_RPC_SERVER, APNS_RPC_PORT)

    def help_uptoken(self):
        print "syntax: uptoken count -- update <count> devices token, so send update_token messgae to mdm server"

    def do_testmdm(self):
        pass
    def help_testmdm(self):
        print "syntax: testmdm -- just query mdm cmd directly to mdm server"


    def do_quit(self, arg):
        return True

    def help_quit(self):
        print "syntax: quit -- terminatesthe application"

    # define the shortcuts
    do_q = do_quit

    def do_shell(self, arg):
        "run a shell commad"
        print ">", arg
        sub_cmd = subprocess.Popen(arg,shell=True, stdout=subprocess.PIPE)
        print sub_cmd.communicate()[0]

if __name__ =="__main__":
    cli = CLI()
    try:
        cli.cmdloop()
    except KeyboardInterrupt, e:
        pass
    finally:
        print "\nexit CLI successful"