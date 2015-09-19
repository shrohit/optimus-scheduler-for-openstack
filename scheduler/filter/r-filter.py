#!/usr/bin/python
#
# Hosts filter written by Rohit 
#
#

from oslo.config import cfg
from nova.scheduler import filters
from nova import servicegroup
import json
import socket
import logging

CONN_PORT = 9999
LOGFILE = "/var/lib/nova/r-filter.log"

ram_allocation_ration_opt = cfg.FloatOpt("ram_allocatio_ration",
	default=1.5,
	help="Virtual RAM to Physical RAM allocation ratio")

cpu_allocation_ration_opt = cfg.FloatOpt("cpu_allocation_ration",
	default=16.0,
	help="Virtual CPU to Physical CPU allocation_ration")

CONF = cfg.CONF
CONF.register_opt(ram_allocation_ration_opt)
CONF.register_opt(cpu_allocation_ration_opt)

logger = logging.getLogger()
hndlr = logging.FileHandler(LOGFILE)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hndlr.setFormatter(formatter)
logger.addHandler(hndlr)
logger.setLevel(logging.DEBUG)

class RFilter(filters.BaseHostFilter):
	"""
	Categories of Hosts to which same type of VMs will be assigned:
		- CRE = CPU RAM Equal
		- CGR = CPU greater than RAM
		- RGC = RAM greater than CPU

	NOTE: Categories are created on the basis of VM's demand of resources.
	"""
	def host_passes(self, host_state, filter_properties):
		""" Short Description of Filteration Procedure """ 

		# Return False if host is down
		service = host_state.service
		check = servicegroup.API()
		alive = check.service_is_up(service)
		if service['disabled'] or not alive:
			return False

		instance_type = filter_properties['instance_type']
		vm_category = instance_type['category']
		total_host_ram = host_state.total_usable_ram_mb

		# Get current status of resources in host
		host_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			host_conn.connect((host_state.nodename, CONN_PORT))
			host_conn.send('usage')
			data = host_conn.recv(1024)
			host_used = json.loads(data)
			host_conn.close()
		except socket.error:
			logger.error('Resource Info Provider Daemon not up in %s' % host_state.nodename)
			return False

		host_category = 'CRE'
		host_ram_used_perc = host_used['ram_mb']/(total_host_ram/100)
		host_ram_free_perc = 100 - host_ram_used_perc 
		host_cpu_free_perc = 100 - host_used['cpu_load']

		# Check Threshold
		if host_ram_used_perc >= host_used['memory_threshold'] or \
		   host_used['cpu_load'] >= host_used['cpu_threshold']:
			logger.debug('Host %s crossed Threshold [CPU_LOAD - %f | MEMORY_LOAD - %f]' % 
				(host_state.nodename, host_used['cpu_load'], host_ram_used_perc))
			return False

		# Check host category
		if host_cpu_free_perc > host_ram_free_perc:
			host_category = 'CGR'
		elif host_ram_free_perc > host_cpu_free_perc:
			host_category = 'RGC'

		if host_category == vm_category:
			logger.debug('host_used : %s' % str(host_used))
			logger.debug('Host Category : %s \t VM category : %s' % (host_category, vm_category))
			logger.debug('HostName : %s \n host_ram_free_perc %% : %f \n host_cpu_free_perc %% : %f' % 
				(host_state.nodename, host_ram_free_perc, host_cpu_free_perc))
			host_ram_free = total_host_ram - host_used['ram_mb'] 
			if instance_type['memory_mb'] > host_ram_free:
				logger.debug('Instance Requirement : ' + str(instance_type['memory_mb']))
				logger.debug('Host RAM free : ' + str(host_ram_free))
				logger.debug('Rejecting Host -> %s' % host_state.nodename)
				return False
			logger.debug('Instance Requirement : ' + str(instance_type['memory_mb']))
			logger.debug('Host RAM free : ' + str(host_ram_free))
			return True
		else:
			logger.debug("Host (%s) does not belong to VM's Category" % host_state.nodename)
			logger.debug('host_used : %s' % str(host_used))
			logger.debug('Host Category : %s \t VM category : %s' % (host_category, vm_category))
			logger.debug('HostName : %s \n host_ram_free_perc %% : %f \n host_cpu_free_perc %% : %f' % 
				(host_state.nodename, host_ram_free_perc, host_cpu_free_perc))
			return False
		
