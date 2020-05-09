# Optimus Scheduler - OpenStack Havana
A scheduler for OpenStack to optimize resource utilization in heterogeneous nova-compute nodes.
- Developed a resource manager for compute nodes (local-manager-compute-node.py) which performs:
  1. Node's future load prediction
  2. Making resources available on the node for the predicted future load by performing VMs' live migration
- Developed an agent (compute-node-info-provider.py) which runs in compute nodes which provides resource utilization information to the scheduler
- Developed a new filter and modified the default host manager of OpenStack to provide extra information to the filter for host passes

# Scheduling Algorithm
- The scheduler divides the OpenStack cluster into 3 host categories:
  1. **CGR: CPU class machines** - where CPU is greater than available memory
  2. **RGC: Memory class machines** - where available memory is greater than CPU
  3. **CRE: General class machines** - where CPU and memory is equal in percentage
- When the scheduler starts, it detects the maximum available Memory node and CPU node in the cluster
- When a new VM creation request is raised, the VM's resource request is compared against the maximum available memory node and maximum available CPU node in the cluster for assigning host-category to the VM
- According to the category of the VM, the scheduler then searches nodes belonging to the same host-category 
- A weight function is applied on the host-category nodes to find the best host-category node where the VM finally gets spawned