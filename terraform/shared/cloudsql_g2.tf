# A1: the G2 source database. Everything else on the CDC path (A2-A5) builds on it.
module "cloudsql_g2" {
  source     = "../modules/cloudsql_g2"
  project_id = var.project_id
  region     = var.region
}

output "g2_connection_name" {
  value = module.cloudsql_g2.connection_name
}

output "g2_public_ip" {
  value = module.cloudsql_g2.public_ip
}
