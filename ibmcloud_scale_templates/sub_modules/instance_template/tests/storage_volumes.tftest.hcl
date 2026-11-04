# Storage volumes must survive every change to the node count, and any input
# that would delete one must fail at plan time. Runs against a mocked provider.

mock_provider "ibm" {
  # A mocked instance otherwise has no address for its DNS records.
  mock_resource "ibm_is_instance" {
    defaults = {
      primary_network_attachment = {
        primary_ip = [{ address = "10.0.0.1" }]
      }
    }
  }

  mock_data "ibm_is_volumes" {
    defaults = {
      volumes = []
    }
  }
}

variables {
  resource_prefix                          = "scale"
  vpc_id                                   = "r014-aaaa-bbbb"
  vpc_region                               = "us-east"
  vpc_availability_zones                   = ["us-east-2"]
  vpc_storage_cluster_private_subnets      = ["subnet-1"]
  vpc_storage_cluster_dns_domain           = "storage.example.com"
  cluster_type                             = "Storage-only"
  storage_cluster_image_id                 = "image"
  storage_cluster_public_key               = "ssh-rsa AAAA"
  total_storage_cluster_instances          = 4
  total_storage_volumes                    = 24
  ibmcloud_api_key                         = "test"
  resource_group_id                        = "rg"
  bastion_security_group_id                = null
  storage_cluster_instance_type            = "bx2d-8x32"
  airgap                                   = false
  orchestrator_server                      = "10.0.0.1"
  orchestrator_port                        = "31018"
  orchestrator_workload_secret             = "test"
  storage_cluster_tiebreaker_instance_type = "bx2-2x8"
  dns_service_instance_id                  = "dns"
  vpc_storage_cluster_dns_zone_id          = "zone"
  vpc_compute_cluster_dns_zone_id          = "zone"
}

run "create_4_nodes_24_volumes" {
  assert {
    condition     = length(ibm_is_volume.storage_data) == 24
    error_message = "expected 24 volumes"
  }
  assert {
    condition     = contains(ibm_is_volume.storage_data["scale-storage-volume-1"].tags, local.scale_volume_tag)
    error_message = "volumes must carry the tag the operator discovers them by"
  }
}

# The reported failure: this used to delete 12 volumes and create 12 empty ones.
run "scale_out_to_10_nodes_keeps_every_volume" {
  variables {
    total_storage_cluster_instances = 10
  }
  assert {
    condition     = output.storage_cluster_volume_ids == run.create_4_nodes_24_volumes.storage_cluster_volume_ids
    error_message = "changing the node count must not touch any volume"
  }
}

run "scale_in_nodes_keeps_every_volume" {
  variables {
    total_storage_cluster_instances = 3
  }
  assert {
    condition     = output.storage_cluster_volume_ids == run.create_4_nodes_24_volumes.storage_cluster_volume_ids
    error_message = "changing the node count must not touch any volume"
  }
}

run "adding_volumes_only_adds" {
  variables {
    total_storage_cluster_instances = 5
    total_storage_volumes           = 30
  }
  assert {
    condition     = length(ibm_is_volume.storage_data) == 30
    error_message = "expected 30 volumes"
  }
  assert {
    condition = alltrue([
      for name, id in run.create_4_nodes_24_volumes.storage_cluster_volume_ids : output.storage_cluster_volume_ids[name] == id
    ])
    error_message = "existing volumes must keep their identity"
  }
}

run "lowering_volume_count_is_rejected" {
  command = plan
  variables {
    total_storage_volumes = 23
  }
  override_data {
    target = data.ibm_is_volumes.existing
    values = {
      volumes = [{ name = "scale-storage-volume-24" }]
    }
  }
  expect_failures = [terraform_data.storage_volume_guard]
}

run "node_tied_volumes_are_rejected" {
  command = plan
  override_data {
    target = data.ibm_is_volumes.existing
    values = {
      volumes = [{ name = "scale-storage-1-disk-4" }]
    }
  }
  expect_failures = [terraform_data.storage_volume_guard]
}

run "other_deployments_volumes_are_ignored" {
  command = plan
  override_data {
    target = data.ibm_is_volumes.existing
    values = {
      volumes = [
        { name = "other-storage-1-disk-4" },
        { name = "other-storage-volume-99" },
        { name = "scale-storage-1-boot-abc" },
      ]
    }
  }
}

run "more_zones_than_nodes_is_rejected" {
  command = plan
  variables {
    vpc_availability_zones              = ["us-east-1", "us-east-2", "us-east-3"]
    vpc_storage_cluster_private_subnets = ["subnet-1", "subnet-2", "subnet-3"]
    total_storage_cluster_instances     = 1
  }
  expect_failures = [terraform_data.storage_volume_guard]
}

run "volumes_spread_over_two_zones" {
  command = plan
  variables {
    vpc_availability_zones              = ["us-east-1", "us-east-2", "us-east-3"]
    vpc_storage_cluster_private_subnets = ["subnet-1", "subnet-2", "subnet-3"]
    total_storage_cluster_instances     = 2
    total_storage_volumes               = 4
  }
  assert {
    condition = (
      ibm_is_volume.storage_data["scale-storage-volume-1"].zone == "us-east-1" &&
      ibm_is_volume.storage_data["scale-storage-volume-2"].zone == "us-east-2" &&
      ibm_is_volume.storage_data["scale-storage-volume-3"].zone == "us-east-1"
    )
    error_message = "volumes must alternate over the zones"
  }
}
