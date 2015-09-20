#!/usr/bin/python
#
#       Author: Rohit Sharma
#
#       ROLES OF THIS SCRIPT:
#       - Act as a local manager for migration of VMs.
#       - Set dynamic threshold of CPU and MEM in config file
#         for migration and scheduling decisions.
#

import ConfigParser
import os
import sys
import subprocess
import re
import socket
import time
import logging
import thread
import random
import numpy as nm
try:
    import psutil
except ImportError, e:
    print 'Error[ImportError]: %s' % e.message

CONF_DIR = '/etc/info-provider'
CONF_FILE = CONF_DIR + '/main.ini'
KEYSTONE_CREDS = '/root/keystone-rohit'

# Exit if config dir not present
if not os.path.isdir(CONF_DIR):
    print 'Error: Config directory not present'
    sys.exit(1)

config = ConfigParser.ConfigParser()
config.read(CONF_FILE)

HOSTNAME = socket.gethostname()
TOTAL_CPUS = psutil.NUM_CPUS
CPU_THRES = int(config.get('DEFAULT', 'CPU_THRES'))
MEM_THRES = int(config.get('DEFAULT', 'MEM_THRES'))
MAX_CPU_THRES = int(config.get('DEFAULT', 'MAX_CPU_THRES'))
MAX_MEM_THRES = int(config.get('DEFAULT', 'MAX_MEM_THRES'))
COMMANDS = {
        'set_env': 'source %s' % KEYSTONE_CREDS,
        'list_vms': 'nova list',
        'instance_detail' : 'nova show %s',
        'list_vms_names' : 'nova list --host %s --all-tenants --fields instance_name' % HOSTNAME,
        'top_vms_utilization' : 'top -n1 -p %s | grep qemu-kvm',
        'ps_vms_utilization' : 'ps aux | grep /usr/libexec/qemu-kvm | grep -v grep',
        'migrate_vm' : 'nova live-migration %s',
        'hypervisor-server' : 'nova hypervisor-servers %s',
        'vms_demand_ram' : "expr $(nova hypervisor-show %s | grep memory_mb_used | awk '{print $4;}') - 512",
        'vms_actual_used' : "echo $(smem -u qemu | grep ^qemu | awk '{print $5;}')/1024 | bc  -l",
        'running_vms_count' : 'virsh list --all | grep running | wc -l',
        'vm_ram_demand_mb' : "echo $(virsh dominfo %s | grep ^Max | awk '{print $3;}')/1024 | bc -l"
}

POLLING_INTERVAL = 60   # Seconds
WAIT_INTERVAL = 30 # Seconds (Wait interval for migration)
LOGFILE = config.get('DEFAULT', 'LOGFILE')
LOAD_INTERVAL = {'count' : 60, 'interval_sec' : 5 }
MACHINE_LOAD_DATA = []
MEM_LOAD_INTERVAL = {'count': 60, 'interval_sec': 5 }
MEM_LOAD_DATA = []
RUN = True      # for machine load thread
PREDICTION_ITERATIONS = 12 # Loop counter on the basis of which prediction will be done on CPU load
MIGRATIONS_COUNT = 0

logging.basicConfig(filename=LOGFILE, mode='a', level=logging.DEBUG)

# Sanity Check
if not os.path.isfile(KEYSTONE_CREDS):
    print 'Error: Keystone credentials file (%s) is not present.' % KEYSTONE_CREDS
    sys.exit(1)

def listVMS():
    """ Returns a list of ids of instances """
    cmd = COMMANDS['set_env'] + ';' + COMMANDS['list_vms']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out, err = proc.communicate()
    pattern = '\w+-\w+-\w+-\w+-\w+'
    return re.findall(pattern, out)

def getInstances():
    """ Returns a Dict of name:id of instances """
    instances = {}
    cmd = COMMANDS['set_env'] + ';' + COMMANDS['list_vms_names']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out, err = proc.communicate()
    for line in out.splitlines():
        pattern_id = '\w+-\w+-\w+-\w+-\w+'
        pattern_name = '\w+-\w+'
        if re.search(pattern_id, line):
            name = re.findall(pattern_name, line)[-1]
            id = re.findall(pattern_id, line)[0]
            instances[name] = id
    return instances

def getVMsUtilization():
    """ Returns a Dict of {instances: {Dict of pid,cpu,mem}} """
    vm_info = {}
    proc = subprocess.Popen(COMMANDS['ps_vms_utilization'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out, err = proc.communicate()
    if out:
        for line in out.splitlines():
            instance_info = line.split()
            vm_info[instance_info[12]] = {'pid' : instance_info[1]}
        pidList = ','.join([ vm_info[x]['pid'] for x in vm_info ])
        cmd = COMMANDS['top_vms_utilization'] % pidList
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        out, err = proc.communicate()
        for line in out.splitlines():
            line = line.split()
            try:
                pid = str(int(line[1]))
                cpu_used = line[9]
                mem_used = line[10]
            except ValueError:
                pid = re.findall('\d+',line[0])[-1]
                cpu_used = line[8]
                mem_used = line[9]
            for instance in vm_info:
                if vm_info[instance]['pid'] == pid:
                    vm_info[instance] = {'cpu':float(cpu_used)/TOTAL_CPUS, 'memory':mem_used, 'pid' : pid}
    return vm_info


def migrateFreeMEM(limit):
    #
    # Function to migrate VMs to make memory consumption
    # below threshold.
    #
    vms_utilization = getVMsUtilization()
    vms_id = getInstances()
    best_vm = {'vm':'', 'reach' : 999} # It will have the uuid of VM to migrate
    for instance in vms_utilization:
        reach = (float(vms_utilization[instance]['memory']) - limit)
        print 'Reach of instance: ' + instance + ' ' + str(reach)
        if reach < 0:
            continue
        if reach < best_vm['reach']:
            best_vm['vm'] = vms_id[instance]
            best_vm['reach'] = reach
            if reach == 0:
                break
    print 'MEM Free - Best VM: ' + str(best_vm)
    cmd = COMMANDS['set_env'] + ';'  + (COMMANDS['migrate_vm'] % best_vm['vm'])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out, err = proc.communicate()
    if not out:
        print 'Started migration of vm: %s' % best_vm['vm']
        # Incrementing count of migrations
        global MIGRATIONS_COUNT
        MIGRATIONS_COUNT += 1

    else:
        print 'Migration Failed. . .'
        print 'Error: %s' % err

def returnY(m, x, c):
    """ Returns y for equation of line (y = mx + c) """
    return m*x + c

def migrateFreeCPU(limit):
    #
    # Function to migrate VMs to make cpu consumption
    # below threshold.
    #
    vms_utilization = getVMsUtilization()
    vms_id = getInstances()
    best_vm = {'vm':'', 'reach' : 999} # It will have the uuid of VM to migrate
    """
    while not len(MACHINE_LOAD_DATA) >= LOAD_INTERVAL['count']:
            print '. ',
            sys.stdout.flush()
            time.sleep(1)
    # Creating eq. y = mx + c
    n = LOAD_INTERVAL['count']
    sigma_xy = sum(map(lambda (util, load): util*load, MACHINE_LOAD_DATA))
    dot_sigmaXsigmaY = sum([util for util,load in MACHINE_LOAD_DATA]) *  sum([load for util,load in MACHINE_LOAD_DATA])
    sigma_xSquare = sum([util**2 for util,load in MACHINE_LOAD_DATA])
    sigmaX_square = sum([util for util,load in MACHINE_LOAD_DATA])**2
    m = (n*sigma_xy - dot_sigmaXsigmaY)/float(n*sigma_xSquare - sigmaX_square)
    mean_y = (sum([load for util,load in MACHINE_LOAD_DATA])/float(len([load for util,load in MACHINE_LOAD_DATA])))
    mean_x = (sum([util for util,load in MACHINE_LOAD_DATA])/float(len([util for util,load in MACHINE_LOAD_DATA])))
    c = mean_y - m*mean_x
    print 'Value of m: ' + str(m)
    print 'Value of c: ' + str(c)
    """
    negative_reach_vms = {}
    for instance in vms_utilization:
        #cpu_load = returnY(m, vms_utilization[instance]['cpu'], c)
        #reach = cpu_load - limit
        try:
            reach = vms_utilization[instance]['cpu'] - limit
        except KeyError:
            continue
        print 'Reach of instance: ' + instance + ' | ' + str(reach) + \
      ' Utilization : ' + str(vms_utilization[instance]['cpu'])
        if reach < 0:
            negative_reach_vms[reach] = vms_id[instance]
            continue
        else:
            if reach < best_vm['reach']:
                best_vm['vm'] = vms_id[instance]
                best_vm['reach'] = reach
                if reach == 0:
                    break
    # Checking if best VM should be taken from negative reach or not
    if not best_vm['vm']:
        print 'No Best VM Found. Picking VM from negative reach poll.'
        negative_best_vm = max(negative_reach_vms.keys())
        best_vm['vm'] = negative_reach_vms[negative_best_vm]
        best_vm['reach'] = negative_best_vm

    print 'CPU Free - Best VM: ' + str(best_vm)
    cmd = COMMANDS['set_env'] + ';'  + (COMMANDS['migrate_vm'] % best_vm['vm'])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out, err = proc.communicate()
    if not err:
        print 'Started migration of vm: %s' % best_vm['vm']

        # Incrementing count of migrations
        global MIGRATIONS_COUNT
        MIGRATIONS_COUNT += 1

        time.sleep(20)
    else:
        print 'Migration Failed. . .'
        print 'Error: %s' % err



def genMachineLoadData():
    #
    # Function to generate dataset of load on CPU.
    #
    global MACHINE_LOAD_DATA
    while RUN:
        current_cpu_utilization = psutil.cpu_percent(interval=LOAD_INTERVAL['interval_sec'])
        current_cpu_load = (os.getloadavg()[0]/TOTAL_CPUS) * 100
        MACHINE_LOAD_DATA.append((current_cpu_utilization, current_cpu_load))
        if len(MACHINE_LOAD_DATA) > LOAD_INTERVAL['count']:
            del MACHINE_LOAD_DATA[0]

def genMachineMemData():
    #
    # Function to generate dataset of (total_demand, actual_utilization)
    # of ram.
    #
    global MEM_LOAD_DATA
    while RUN:
        vms_info = getVMsUtilization()

        # Finding total VMs demand
        total_demand = 0
        for vm in vms_info:
            try:
                cmd = COMMANDS['vm_ram_demand_mb'] % vm
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
                out, err = proc.communicate()
                total_demand = total_demand + float(out)
            except ValueError:
                continue

        # Finding RAM actually used by VMs
        actually_used = 0
        proc = subprocess.Popen(COMMANDS['vms_actual_used'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        out, err= proc.communicate()
        try:
            actually_used = float(out)
        except ValueError:
            pass

        # Assigning data to list of mem data
        MEM_LOAD_DATA.append((total_demand, actually_used))
        if len(MEM_LOAD_DATA) > MEM_LOAD_INTERVAL['count']:
            del MEM_LOAD_DATA[0]
        time.sleep(MEM_LOAD_INTERVAL['interval_sec'])

def cpuThresholdUpdater():
    """ This function will update cpu threshold dynamically in config file. """
    while RUN:
        # Updating threshold in config file
        dynamic_thres = cpuDynamicThreshold()

        # If threshold lower than 80, set it to 80 only
        if dynamic_thres < 80:
            dynamic_thres = 80

        parser = ConfigParser.ConfigParser()
        parser.read(CONF_FILE)
        parser.set('DEFAULT', 'CPU_THRES', dynamic_thres)
        write_file = open(CONF_FILE, 'w')
        parser.write(write_file)
        write_file.flush()
        write_file.close()

        # Wait for next interval
        wait_seconds = LOAD_INTERVAL['count'] * LOAD_INTERVAL['interval_sec']
        time.sleep(wait_seconds)

def memThresholdUpdater():
    """ This function will update the memory threshold dynamically in config file """
    #print 'Started memory threshold updater'
    while RUN:
        # Updating threshold in config file
        dynamic_thres = memDynamicThreshold()

        # If threshold lower than 80, set it to 80 only
        if dynamic_thres < 80:
            dynamic_thres = 80

        #"""
        parser = ConfigParser.ConfigParser()
        parser.read(CONF_FILE)
        parser.set('DEFAULT', 'MEM_THRES', dynamic_thres)
        write_file = open(CONF_FILE, 'w')
        parser.write(write_file)
        write_file.flush()
        write_file.close()
        #"""

        # Wait for next interval
        wait_seconds = MEM_LOAD_INTERVAL['count'] * MEM_LOAD_INTERVAL['interval_sec']
        time.sleep(wait_seconds)

def cpuDynamicThreshold():
    """ Function for finding Dynamic threshold for CPU """
    length_of_interval = LOAD_INTERVAL['count']
    data_slice_interval = LOAD_INTERVAL['interval_sec']
    while len(MACHINE_LOAD_DATA) < length_of_interval:
        let_interval_complete = (length_of_interval - len(MACHINE_LOAD_DATA)) * data_slice_interval
        time.sleep(let_interval_complete)
    machine_data = MACHINE_LOAD_DATA

    # Finding MAD (Mean absolute deviation)
    sorted_cpu_load = sorted(map(lambda cpu: cpu[1], machine_data))
    if len(sorted_cpu_load) % 2:
        median = sorted_cpu_load[len(sorted_cpu_load)/2]
    else:
        mid = len(sorted_cpu_load)/2
        median = (sorted_cpu_load[mid] + sorted_cpu_load[mid-1])/2.0
    abs_sorted_load = sorted([ abs(val-median) for val in sorted_cpu_load ])
    if len(abs_sorted_load) % 2:
        median = abs_sorted_load[len(abs_sorted_load)/2]
    else:
        mid = len(abs_sorted_load)/2
        median = (abs_sorted_load[mid] + abs_sorted_load[mid-1])/2.0
    MAD = median

    # Finding Growth Factor
    present_load = machine_data[-1][1]
    past_load = machine_data[-2][1]
    try:
        growth_factor = abs((present_load - past_load)/float(past_load))
    except ZeroDivisionError:
        growth_factor = 0.001

    # Finding count of running vms
    proc = subprocess.Popen(COMMANDS['running_vms_count'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out, err = proc.communicate()
    running_vms_count = int(out)

    # Calculating threshold
    dynamic_thres = int((1 - abs(MAD*growth_factor*running_vms_count)) * 100)

    # Print for debugging
    #print 'THRES: %d | (1 - (%f * %f * %d)) * 100' % (dynamic_thres, MAD, growth_factor, running_vms_count)

    """
    # Updating threshold in config file
    write_file = open(CONF_FILE, 'w')
    parser = ConfigParser.ConfigParser()
    parser.read(CONF_FILE)
    parser.set('DEFAULT', 'CPU_THRES', dynamic_thres)
    parser.write(write_file)
    write_file.flush()
    write_file.close()
    """
    return dynamic_thres


def memDynamicThreshold():
    """ Function for finding dynamic threshold for memory """
    mem_in_hypervisor = (psutil.virtual_memory()[0]/1024.0)/1024.0

    # Finding K which will be the reserved area not going to be used for VMs
    reserve = 400 # Size in MB to extra reserve in host
    K = round(reserve / mem_in_hypervisor, 4)

    # Wait for memory interval if not complete
    length_of_interval = MEM_LOAD_INTERVAL['count']
    each_slice_interval = MEM_LOAD_INTERVAL['interval_sec']
    while len(MEM_LOAD_DATA) < length_of_interval:
        wait_seconds = (length_of_interval - len(MEM_LOAD_DATA)) * each_slice_interval
        time.sleep(wait_seconds)
    mem_data =  MEM_LOAD_DATA

    # Finding maximum demand which currently running VMs can make
    demand_total_vms = mem_data[-1][0]
    used_total_vms = mem_data[-1][1]
    demand_total_vms = demand_total_vms / mem_in_hypervisor
    used_total_vms = used_total_vms / mem_in_hypervisor
    maximum_demand = round(abs(demand_total_vms - used_total_vms), 4)

    # Finding growth factor
    present_mem_used = mem_data[-1][1]
    past_mem_used = mem_data[-2][1]
    try:
        growth_factor = round((present_mem_used - past_mem_used)/float(past_mem_used), 4)
    except ZeroDivisionError:
        growth_factor = 0
    #if growth_factor == 0:
    growth_factor = 0.1

    # Finding count of running vms
    proc = subprocess.Popen(COMMANDS['running_vms_count'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out, err = proc.communicate()
    running_vms_count = int(out)

    # Calculating threshold
    dynamic_thres = int((1 - (K + (maximum_demand * abs(growth_factor) * running_vms_count))) * 100.0)
    #dynamic_thres = int((1 - (K + (maximum_demand * running_vms_count))) * 100.0)

    # Print to debug
    #print '%f | (1 - (%f + (%f * %f * %d))) * 100.0' % (dynamic_thres, K, maximum_demand, growth_factor, running_vms_count)
    #print '%f | (1 - (%f + (%f * %d))) * 100.0' % (dynamic_thres, K, maximum_demand, running_vms_count)

    return dynamic_thres

# Load prediction function
def perdictLoad(machine_load_data):
    #
    # Funtion to predict future load on the basis on which migrations
    # will stop if load will decrease.
    # Prediction is done to decrease count of migrations.
    #

    K = 8
    #N = LOAD_INTERVAL['count']
    N = len(machine_load_data)
    R = []

    mean_of_load = sum([load for util,load in machine_load_data])/N
    # Finding Rk
    divide = sum([ (load - mean_of_load)**2 for util, load in machine_load_data ])
    loads = [load for util, load in machine_load_data]
    for k in xrange(K):
        sigma = 0
        sigma_k = k+1
        for index in xrange(N-sigma_k):
            calc = (loads[index] - mean_of_load)*(loads[index+sigma_k] - mean_of_load)
            sigma = sigma+calc
        R.append(float(sigma/float(divide)))
    rows = []
    R_rev = R[-1::-1]
    for i in range(K):
        rows.append(R_rev[K-i:] + [1.0] + R[:(K-1)-i])
    matrix = nm.matrix(rows)
    phi_matrix = nm.matrix([ [val] for val in R ])
    final_mul_matrix = matrix.I * phi_matrix        # Actual phi
    C = (1 - sum(final_mul_matrix)) * mean_of_load
    sm = 0
    index = LOAD_INTERVAL['count'] - 1
    for i in range(K):
        sm = sm + (final_mul_matrix[i]*loads[index-i])
    return C + sm

def return_power_consumption(cpu_util):
    """ Function to return present machine power consumption on the basis of cpu utilization """
    fixed_machine_power_cons = 175  # watts
    max_usage_power_cons = 75       # watts

    # Finding power consumption by CPU at runtime
    current_power_cons = (max_usage_power_cons / 100.0) * cpu_util
    if current_power_cons > max_usage_power_cons:
        current_power_cons = max_usage_power_cons
    total_consumption = fixed_machine_power_cons + current_power_cons
    return total_consumption

def main():

    # For our scheduler dataset
    # file = open('Power-Dataset-%s.csv' % time.asctime().replace(' ','_'), 'w', 0)
    # file.write('CPU Util, CPU Load, Ram %, Power Cons, Migrations\n')
    print 'CPU Util, CPU Load, Ram %, Power Cons, Migrations'

    while True:
        current_cpu_util = psutil.cpu_percent(interval=POLLING_INTERVAL)
        current_cpu_load = (os.getloadavg()[0]/TOTAL_CPUS) * 100
        total_ram = psutil.virtual_memory()[0]
        ram_usage_percent = psutil.virtual_memory()[2]
        used_ram = (total_ram/100.0) * ram_usage_percent
        used_ram_mb = round((used_ram/1024)/1024,0)
        if ram_usage_percent > MAX_MEM_THRES:
            logging.info('WARNING: MEMORY Threshold UP!!')
            print 'MEM Threshold up'
            #time.sleep(WAIT_INTERVAL)
            #ram_usage_percent = psutil.virtual_memory()[2]

            # Waiting for Memory Load Data to fill
            while len(MEM_LOAD_DATA) < MEM_LOAD_INTERVAL['count']:
                print 'Wait for Machine Load Data to be filled. . .'
                wait_seconds = (MEM_LOAD_INTERVAL['count'] - len(MEM_LOAD_DATA)) * MEM_LOAD_INTERVAL['interval_sec']
                time.sleep(wait_seconds)

            # Load Prediction
            mem_load = MEM_LOAD_DATA
            predicted_loads = []
            for iteration in xrange(PREDICTION_ITERATIONS):
                predicted_load = perdictLoad(mem_load)
                predicted_loads.append(predicted_load)
                mem_load.append((iteration, predicted_load))
            avg_predicted_load = sum(predicted_loads) / float(len(predicted_loads))
            print 'Predicted MEMORY Load : %f After Seconds : %d' % (avg_predicted_load, PREDICTION_ITERATIONS*MEM_LOAD_INTERVAL['interval_sec'])

            if avg_predicted_load > MAX_MEM_THRES:
                extra_ram_used = avg_predicted_load - MAX_MEM_THRES
                migrateFreeMEM(extra_ram_used)

        elif current_cpu_load > MAX_CPU_THRES:
            logging.info('WARNING: CPU Threshold UP!!')
            print 'CPU Threshold up'
            #time.sleep(WAIT_INTERVAL)

            # Waiting for Machine Load Data to fill
            while len(MACHINE_LOAD_DATA) < LOAD_INTERVAL['count']:
                print 'Wait for Machine Load Data to be filled. . .'
                wait_seconds = (LOAD_INTERVAL['count'] - len(MACHINE_LOAD_DATA)) * LOAD_INTERVAL['interval_sec']
                time.sleep(wait_seconds)

            # Load Prediction
            machine_load = MACHINE_LOAD_DATA
            predicted_loads = []
            for iteration in xrange(PREDICTION_ITERATIONS):
                predicted_load = perdictLoad(machine_load)
                predicted_loads.append(predicted_load)
                machine_load.append((iteration, predicted_load))
            avg_predicted_load = sum(predicted_loads) / float(len(predicted_loads))
            print 'Predicted CPU Load : %f After Seconds : %d' % (avg_predicted_load, PREDICTION_ITERATIONS*LOAD_INTERVAL['interval_sec'])

            #current_cpu_load = (os.getloadavg()[0]/TOTAL_CPUS) * 100
            #if current_cpu_load > MAX_CPU_THRES:
            if avg_predicted_load > MAX_CPU_THRES:
                extra_used_cpu = current_cpu_load - MAX_CPU_THRES
                migrateFreeCPU(extra_used_cpu)
        #else:
            #print 'Usage: CPU - %f \t MEM - %f' % (current_cpu_load, ram_usage_percent)

        # Data to write in power dataset file
        txt = "%f, %f, %f, %f, %d" % (current_cpu_util, current_cpu_load, ram_usage_percent, return_power_consumption(current_cpu_util), \
                                                        MIGRATIONS_COUNT)
        #file.write(txt + '\n')
        print txt
        #time.sleep(POLLING_INTERVAL)


if __name__ == '__main__':
    thread.start_new_thread(genMachineLoadData, ())
    thread.start_new_thread(genMachineMemData, ())
    thread.start_new_thread(cpuThresholdUpdater, ())
    thread.start_new_thread(memThresholdUpdater, ())
    main()
    #memThresholdUpdater()
