#!/usr/bin/env python3
"""
Copyright IBM Corporation 2018

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import json
import pathlib
import re

# Note: Don't use socket for FQDN resolution.
CLUSTER_DEFINITION_JSON = {'node_details': []}

def read_tf_inv_file(tf_inv_path):
    """ Read the terraform inventory json file """
    with open(tf_inv_path) as json_handler:
        tf_inv = json.load(json_handler)
    return tf_inv

def initialize_cluster_details(cluster_name, scale_profile_file, scale_replica_config):
    """ Initialize cluster details.
    :args: cluster_name (string), scale_profile_file (string), scale_replica_config (bool)
    """
    CLUSTER_DEFINITION_JSON['scale_cluster'] = {}
    CLUSTER_DEFINITION_JSON['scale_cluster']['scale_cluster_name'] = cluster_name
    CLUSTER_DEFINITION_JSON['scale_cluster']['scale_service_gui_start'] = "False"
    CLUSTER_DEFINITION_JSON['scale_cluster']['scale_sync_replication_config'] = scale_replica_config
    CLUSTER_DEFINITION_JSON['scale_cluster']['scale_cluster_profile_name'] = str(pathlib.PurePath(scale_profile_file).stem)
    CLUSTER_DEFINITION_JSON['scale_cluster']['scale_cluster_profile_dir_path'] = str(pathlib.PurePath(scale_profile_file).parent)


def initialize_scale_config_details(node_class, param_key, param_value):
    """ Initialize cluster details.
    :args: node_class (string), param_key (string), param_value (string)
    """
    CLUSTER_DEFINITION_JSON['scale_config'] = []
    CLUSTER_DEFINITION_JSON['scale_config'].append({"nodeclass": node_class,
                                                    "params": [{param_key: param_value}]})


def initialize_node_details(fqdn, ip_address, node_class, is_nsd_server=False,
                            is_quorum_node=False, is_manager_node=False,
                            is_collector_node=False, is_gui_server=False, is_admin_node=True):
    """ Initialize node details for cluster definition.
    :args: json_data (json), fqdn (string), ip_address (string), node_class (string),
           is_nsd_server (bool), is_quorum_node (bool),
           is_manager_node (bool), is_collector_node (bool), is_gui_server (bool),
           is_admin_node (bool)
    """
    CLUSTER_DEFINITION_JSON['node_details'].append({'fqdn': fqdn,
                                                    'ip_address': ip_address,
                                                    'state': 'present',
                                                    'is_nsd_server': is_nsd_server,
                                                    'is_quorum_node': is_quorum_node,
                                                    'is_manager_node': is_manager_node,
                                                    'is_collector_node': is_collector_node,
                                                    'is_gui_server': is_gui_server,
                                                    'is_admin_node': is_admin_node,
                                                    'scale_nodeclass': [node_class]})


if __name__ == "__main__":
    PARSER = argparse.ArgumentParser(description='Convert terraform inventory '
                                                 'to ansible inventory format '
                                                 'install and configuration.')
    PARSER.add_argument('--tf_inv_path', required=True,
                        help='Terraform inventory file path')
    PARSER.add_argument('--scale_cluster_def_path', required=True,
                        help='Spectrum Scale cluster definition json path')
    PARSER.add_argument('--scale_tuning_profile_file', required=True,
                        help='IBM Spectrum Scale SNC tuning profile file path')
    PARSER.add_argument('--verbose', action='store_true',
                        help='print log messages')
    ARGUMENTS = PARSER.parse_args()

    TF_INV = read_tf_inv_file(ARGUMENTS.tf_inv_path)
    if ARGUMENTS.verbose:
        print("Parsed terraform output: %s" % json.dumps(TF_INV, indent=4))
    if len(TF_INV['availability_zones']) > 1:
        total_node_count = len(TF_INV['compute_instances_by_ip']) + \
                len(TF_INV['compute_instance_desc_map'].keys()) + \
                len(TF_INV['storage_instance_disk_map'].keys())
    else:
        total_node_count = len(TF_INV['compute_instances_by_ip']) + \
                len(TF_INV['storage_instance_disk_map'].keys())

    if ARGUMENTS.verbose:
        print("Total node count: ", total_node_count)

    # Determine total number of quorum, manager nodes to be in the cluster
    # manager designates the node as part of the pool of nodes from which
    # file system managers and token managers are selected.
    quorum_count, manager_count = 0, 2
    if total_node_count < 4:
        quorum_count = total_node_count
    elif 4 <= total_node_count < 10:
        quorum_count = 3
    elif 10 <= total_node_count < 19:
        quorum_count = 5
    else:
        quorum_count = 7

    if ARGUMENTS.verbose:
        print("Total quorum count: ", quorum_count)

    # Define cluster name
    if len(TF_INV['availability_zones']) > 1:
        initialize_cluster_details(TF_INV['stack_name'],
                                   ARGUMENTS.scale_tuning_profile_file,
                                   "True")
    else:
        initialize_cluster_details(TF_INV['stack_name'],
                                   ARGUMENTS.scale_tuning_profile_file,
                                   "False")

    if len(TF_INV['availability_zones']) > 1:
        # Compute desc node to be a quorum node (quorum = 1, manager = 0)
        for each_ip in TF_INV['compute_instance_desc_map']:
            initialize_node_details(each_ip, each_ip,
                                    is_gui_server=False, is_collector_node=False, is_nsd_server=True,
                                    is_quorum_node=True, is_manager_node=False, is_admin_node=False,
                                    node_class="computedescnodegrp")

    if len(TF_INV['availability_zones']) > 1:
        # Storage/NSD nodes to be quorum nodes (quorum_count - 2 as index starts from 0)
        start_quorum_assign = quorum_count - 2
    else:
        # Storage/NSD nodes to be quorum nodes (quorum_count - 1 as index starts from 0)
        start_quorum_assign = quorum_count - 1

    # Map storage nodes to failure groups based on AZ and subnet variations
    failure_group1, failure_group2 = [], []
    if len(TF_INV['availability_zones']) == 1:
        # Single AZ, just split list equally
        num_storage_nodes = len(list(TF_INV['storage_instance_disk_map']))
        mid_index = num_storage_nodes//2
        failure_group1 = list(TF_INV['storage_instance_disk_map'])[:mid_index]
        failure_group2 = list(TF_INV['storage_instance_disk_map'])[mid_index:]
    else:
        # Multi AZ, split based on subnet match
        subnet_pattern = re.compile(r'\d{1,3}\.\d{1,3}\.(\d{1,3})\.\d{1,3}')
        subnet1A = subnet_pattern.findall(list(TF_INV['storage_instance_disk_map'])[0])
        for each_ip in TF_INV['storage_instance_disk_map']:
            current_subnet = subnet_pattern.findall(each_ip)
            if current_subnet[0] == subnet1A[0]:
                failure_group1.append(each_ip)
            else:
                failure_group2.append(each_ip)

    if ARGUMENTS.verbose:
        print("Storage Nodes in Failure Group 1 : {0}".format(failure_group1))
        print("Storage Nodes in Failure Group 2 : {0}".format(failure_group2))

    storage_instances = []
    max_len = max(len(failure_group1), len(failure_group2))
    idx = 0
    while idx < max_len:
        if idx < len(failure_group1):
            storage_instances.append(failure_group1[idx])

        if idx < len(failure_group2):
            storage_instances.append(failure_group2[idx])

        idx = idx + 1

    if ARGUMENTS.verbose:
        print("Merged Storage Nodes(alternating by FG) : {0}".format(storage_instances))

    for each_ip in storage_instances:
        if storage_instances.index(each_ip) <= (start_quorum_assign) and \
           storage_instances.index(each_ip) <= (manager_count - 1):
            if storage_instances.index(each_ip) == 0:
                initialize_node_details(each_ip, each_ip,
                                        is_gui_server=True, is_collector_node=True, is_nsd_server=True,
                                        is_quorum_node=True, is_manager_node=True, is_admin_node=True,
                                        node_class="storagenodegrp")
            elif storage_instances.index(each_ip) == 1:
                initialize_node_details(each_ip, each_ip,
                                        is_gui_server=False, is_collector_node=True, is_nsd_server=True,
                                        is_quorum_node=True, is_manager_node=True, is_admin_node=True,
                                        node_class="storagenodegrp")
            else:
                initialize_node_details(each_ip, each_ip,
                                        is_gui_server=False, is_collector_node=False, is_nsd_server=True,
                                        is_quorum_node=True, is_manager_node=True, is_admin_node=True,
                                        node_class="storagenodegrp")
        elif storage_instances.index(each_ip) <= (start_quorum_assign) and \
             storage_instances.index(each_ip) > (manager_count - 1):
            initialize_node_details(each_ip, each_ip,
                                    is_gui_server=False, is_collector_node=False, is_nsd_server=True,
                                    is_quorum_node=True, is_manager_node=False, is_admin_node=True,
                                    node_class="storagenodegrp")
        else:
            initialize_node_details(each_ip, each_ip,
                                    is_gui_server=False, is_collector_node=False, is_nsd_server=True,
                                    is_quorum_node=False, is_manager_node=False, is_admin_node=False,
                                    node_class="storagenodegrp")

    if len(TF_INV['availability_zones']) > 1:
        if len(storage_instances) - len(TF_INV['compute_instance_desc_map'].keys()) >= quorum_count:
            quorums_left = 0
        else:
            quorums_left = quorum_count - len(storage_instances) - \
                    len(TF_INV['compute_instance_desc_map'].keys())
    else:
        if len(TF_INV['storage_instance_disk_map'].keys()) > quorum_count:
            quorums_left = 0
        else:
            quorums_left = quorum_count - len(storage_instances)

    if ARGUMENTS.verbose:
        print("Total quorums left and to be assigned to compute nodes: ", quorums_left)

    # Additional quorums assign to compute nodes
    if quorums_left > 0:
        for each_ip in TF_INV['compute_instances_by_ip'][0:quorums_left]:
            if len(TF_INV['storage_instance_disk_map'].keys()) == 0:
                initialize_node_details(each_ip, each_ip,
                                     is_gui_server=True, is_collector_node=False, is_nsd_server=False,
                                     is_quorum_node=True, is_manager_node=False, is_admin_node=True,
                                     node_class="computenodegrp")
            else:
                initialize_node_details(each_ip, each_ip,
                                        is_gui_server=False, is_collector_node=False, is_nsd_server=False,
                                        is_quorum_node=True, is_manager_node=False, is_admin_node=True,
                                        node_class="computenodegrp")

        for each_ip in TF_INV['compute_instances_by_ip'][quorums_left:]:
            initialize_node_details(each_ip, each_ip,
                                    is_gui_server=False, is_collector_node=False, is_nsd_server=False,
                                    is_quorum_node=False, is_manager_node=False, is_admin_node=False,
                                    node_class="computenodegrp")

    if quorums_left == 0:
        for each_ip in TF_INV['compute_instances_by_ip']:
            initialize_node_details(each_ip, each_ip,
                                    is_gui_server=False, is_collector_node=False, is_nsd_server=False,
                                    is_quorum_node=False, is_manager_node=False, is_admin_node=False,
                                    node_class="computenodegrp")

    # Define nodeclass specific GPFS config
    if len(TF_INV['compute_instances_by_ip']):
        initialize_scale_config_details("computenodegrp", "pagepool", "1G")
    if len(TF_INV['storage_instance_disk_map'].keys()):
        initialize_scale_config_details("storagenodegrp", "pagepool", "1G")
    if len(TF_INV['availability_zones']) > 1:
        initialize_scale_config_details("computedescnodegrp", "unmountOnDiskFail", "yes")

    # Prepare dict of disks / NSD list
    disks_list = []
    for each_ip, disk_per_ip in TF_INV['storage_instance_disk_map'].items():
        if each_ip in failure_group1:
            for each_disk in disk_per_ip:
                disks_list.append({"device": each_disk,
                                   "failureGroup": 1, "servers": each_ip,
                                   "usage": "dataAndMetadata", "pool": "system"})
        if each_ip in failure_group2:
            for each_disk in disk_per_ip:
                disks_list.append({"device": each_disk,
                                   "failureGroup": 2, "servers": each_ip,
                                   "usage": "dataAndMetadata", "pool": "system"})

    # Append "descOnly" disk details
    if len(TF_INV['availability_zones']) > 1:
        disks_list.append({"device": list(TF_INV['compute_instance_desc_map'].values())[0],
                           "failureGroup": 3,
                           "servers": list(TF_INV['compute_instance_desc_map'].keys())[0],
                           "usage": "descOnly", "pool": "system"})

    # Populate "scale_storage" list
    if len(TF_INV['availability_zones']) == 3:
        DATA_REPLICAS = len(TF_INV['availability_zones']) - 1
    else:
        DATA_REPLICAS = len(TF_INV['availability_zones'])

    if len(TF_INV['storage_instance_disk_map'].keys()):
        CLUSTER_DEFINITION_JSON['scale_storage'] = []
        CLUSTER_DEFINITION_JSON["scale_storage"].append({"filesystem": pathlib.PurePath(TF_INV['filesystem_mountpoint']).name,
                                                         "blockSize": TF_INV['filesystem_block_size'],
                                                         "defaultDataReplicas": DATA_REPLICAS,
                                                         "defaultMetadataReplicas": 2,
                                                         "automaticMountOption": "true",
                                                         "defaultMountPoint": TF_INV['filesystem_mountpoint'],
                                                         "disks": disks_list})

    if ARGUMENTS.verbose:
        print("Content of scale_clusterdefinition.json: ",
              json.dumps(CLUSTER_DEFINITION_JSON, indent=4))

    # Write json content
    if ARGUMENTS.verbose:
        print("Writing cloud infrastructure details to: ", ARGUMENTS.scale_cluster_def_path)
    with open(ARGUMENTS.scale_cluster_def_path, 'w') as json_fh:
        json.dump(CLUSTER_DEFINITION_JSON, json_fh, indent=4)
    if ARGUMENTS.verbose:
        print("Completed writing cloud infrastructure details to: ",
              ARGUMENTS.scale_cluster_def_path)