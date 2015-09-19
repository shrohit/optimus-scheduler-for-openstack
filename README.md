# optimus-scheduler-for-openstack
A scheduler of virtual machines for openstack to optimise utilization of resources in nova-compute nodes.

- Created a filter and made some changes to the default host manager of OpenStack to provide some extra information to filter for host passes.

Scheduling Approach
-------------------
- The cluster of hosts is divided into 3 categories:
    1. CRE: Hosts in which utilization of cpu and ram is equal.
    2. CGR: Hosts in which utilization of ram is higher than cpu.
    3. RGC: Hosts in which utilization of cpu is higher than ram.
- When scheduler starts it detects the maximum available ram and cpu in cluster.
- When a new virtual machine is created it compares the resource demand of vm with maximum available for deciding and assigning a category(among the 3 categories discussed above) to it.
- According to category of vm the scheduler then searches hosts belong to set of same category. 
- A weighting function is applied on the set of hosts of same category to find the best machine to which the vm can be assigned. 
