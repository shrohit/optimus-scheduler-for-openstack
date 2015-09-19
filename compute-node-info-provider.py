#!/usr/bin/python

import socket
import thread 
import logging
import sys
import os
import ConfigParser
try:
	import psutil
	import json
except ImportError, detail:
	print 'Import Error: ' + detail.args[0]
	print 'INFO: Install the proper packages to fulfil dependencies'
	sys.exit(1)

CONFIGDIR = '/etc/info-provider'
CONFIGFILE = CONFIGDIR + '/main.ini'
DEFAULT_CONFIG = { 
	'IP':'',
	'PORT':'9999',
	'LOGFILE':'/var/log/info-provider.log',
	'CPU_THRES':'80',
	'MEM_THRES':'70',
	'MAX_CPU_THRES':'100',
	'MAX_MEM_THRES':'90'
}

# Variables for CPU Utilization Data
CPU_UTIL = psutil.cpu_percent()
UPDATE_INTERVAL = 60    # Seconds 

# Calculating MAX_MEM_THRES 
total_memory = (psutil.virtual_memory()[0]/1024.0)/1024.0
reserve_mb = 400	# Memory to reserve for other computer-node tasks.
reserve_perc = (reserve_mb/total_memory) * 100
max_threshold = int(100 - reserve_perc)
DEFAULT_CONFIG['MAX_MEM_THRES'] = str(max_threshold)

# Create config dir if not present
if not os.path.isdir(CONFIGDIR):
	os.mkdir(CONFIGDIR)

# Creating config file.
# NOTE: Everytime a new config file will be created to discard any previous config
config = open(CONFIGFILE, 'w')
section = '[DEFAULT]\n'
for key in DEFAULT_CONFIG.keys():
	section = section + key + ' = ' + DEFAULT_CONFIG[key] + '\n'
config.write(section)
config.close()

# Reading configurations
config = ConfigParser.ConfigParser()
config.read(CONFIGFILE)
LOGFILE = config.get('DEFAULT', 'LOGFILE')
IP = config.get('DEFAULT', 'IP')
PORT = int(config.get('DEFAULT', 'PORT'))

# Configuring Logger
logger = logging.getLogger()
hndlr = logging.FileHandler(LOGFILE)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hndlr.setFormatter(formatter)
logger.addHandler(hndlr)
logger.setLevel(logging.DEBUG)

def client_thread(conn, addr):
	data = conn.recv(1024)
	if data == 'usage':
		logger.info('Got USAGE request from %s' % addr[0])
		conn.send(json.dumps(machine_usage()))
	conn.close()

def update_cpu_util():
        """ Function to update cpu utilization data """
        global CPU_UTIL
        while True:
                CPU_UTIL = psutil.cpu_percent(interval=UPDATE_INTERVAL)

def return_power_consumption(cpu_util):
        """ Function to return currenct machine power consumption on the basis of cpu utilization """
        fixed_machine_power_cons = 175  # watts (Assumed for testing)
        max_usage_power_cons = 75       # watts (Assumed for testing)

        # Finding power consumption by CPU at runtime
        current_power_cons = (max_usage_power_cons / 100.0) * cpu_util
        if current_power_cons > max_usage_power_cons:
                current_power_cons = max_usage_power_cons
        total_consumption = fixed_machine_power_cons + current_power_cons
        return total_consumption


def machine_usage():
	# Reading values of parameters from config file.
	config = ConfigParser.ConfigParser()
	config.read(CONFIGFILE)
	CPU_THRES = config.get('DEFAULT', 'CPU_THRES')
	MEM_THRES = config.get('DEFAULT', 'MEM_THRES')
	used = {}

	# Calculating RAM usage
	total_ram = psutil.virtual_memory()[0]
	usage_percent = psutil.virtual_memory()[2]
	used_ram = (total_ram/100.0) * usage_percent
	used_ram_mb = round((used_ram/1024)/1024,0)
	total_ram = round((psutil.virtual_memory()[0]/1024)/1024,0)

        # Calculating RAM usage Percentage
        ram_usage_perc = (used_ram_mb / total_ram) * 100.0

	# Calculating CPU load
	loadavg = open('/proc/loadavg', 'r')
	min_1 = float(loadavg.read().split()[0])
	num_cpus = psutil.NUM_CPUS
	cpu_load_percent = round(((min_1/num_cpus) * 100),0)

        # Calculating CPU power consumption 
        cpu_power_consump = return_power_consumption(CPU_UTIL)

	# Creating dictionary of current utilization info
	used['ram_mb'] = float(used_ram_mb)
	used['ram_perc'] = ram_usage_perc
	used['cpu_load'] = float(cpu_load_percent)
	used['cpu_threshold'] = float(CPU_THRES)
	used['memory_threshold'] = float(MEM_THRES)
	used['cpu_util'] = CPU_UTIL	# CPU Utilization
	used['power_consumption'] = cpu_power_consump
	return used
	
	
def main():
	# Create socket to listen for requests
	server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	try:
		server.bind((IP, PORT))
	except socket.error as msg:
		logger.critical('Unable to create Socket | CODE : %s MSG : %s' % (msg[0], msg[1]))
		sys.exit(1)
	else: 
		server.listen(5)
		logger.info('Started listening for clients to connect')
	# Handle Requests
	try:
		while True:
			conn, addr = server.accept()
			logger.info('Connected with %s' % ':'.join(map(str,addr)))
			thread.start_new_thread(client_thread, (conn, addr))
	except:
		server.close()
		print sys.exc_info()

if __name__ == '__main__':
	thread.start_new_thread(update_cpu_util, ())
	main()
