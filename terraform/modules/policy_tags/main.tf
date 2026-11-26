# D9: taxonomy poc-pii with the tag pii_direct (names and emails), fine-grained access on, so a reader
# without fine-grained reader on the tag gets an error on tagged columns (or a hash, with masking).
#
# This module only creates the tags. Columns are tagged where their tables are defined:
#   raw_crm.account_landing  primary_contact_name/email   crm_landing module (POC B) uses output pii_direct_id
#   raw_g2.g2_users etc.     Datastream creates them       scripts/security/tag_raw_columns.py
# After tagging, check Datastream and poc-crm-loader still write (D9 step 4).

resource "google_data_catalog_taxonomy" "pii" {
  project                = var.project_id
  region                 = var.region
  display_name           = "poc-pii"
  description            = "Personal data in raw tables (D9). Fine-grained access control."
  activated_policy_types = ["FINE_GRAINED_ACCESS_CONTROL"]
}

resource "google_data_catalog_policy_tag" "pii_direct" {
  taxonomy     = google_data_catalog_taxonomy.pii.id
  display_name = "pii_direct"
  description  = "Values that identify a person on their own: names, email addresses."
}

resource "google_data_catalog_policy_tag" "pii_indirect" {
  count        = var.enable_pii_indirect ? 1 : 0
  taxonomy     = google_data_catalog_taxonomy.pii.id
  display_name = "pii_indirect"
  description  = "Ids that point to one person, e.g. user ids."
}

locals {
  tags = merge(
    { pii_direct = google_data_catalog_policy_tag.pii_direct.name },
    var.enable_pii_indirect ? { pii_indirect = google_data_catalog_policy_tag.pii_indirect[0].name } : {},
  )
  fine_grained = { for pair in setproduct(keys(local.tags), var.fine_grained_readers) : "${pair[0]}/${pair[1]}" => {
    tag = local.tags[pair[0]], member = pair[1]
  } }
}

resource "google_data_catalog_policy_tag_iam_member" "fine_grained_reader" {
  for_each   = local.fine_grained
  policy_tag = each.value.tag
  role       = "roles/datacatalog.categoryFineGrainedReader"
  member     = each.value.member
}

# Spike 3: data masking. Masked readers see SHA-256 hashes; everyone else without the tag gets an error.
resource "google_bigquery_datapolicy_data_policy" "pii_direct_sha256" {
  count            = var.enable_masking ? 1 : 0
  project          = var.project_id
  location         = var.region
  data_policy_id   = "pii_direct_sha256"
  policy_tag       = google_data_catalog_policy_tag.pii_direct.name
  data_policy_type = "DATA_MASKING_POLICY"

  data_masking_policy {
    predefined_expression = "SHA256"
  }
}

resource "google_bigquery_datapolicy_data_policy_iam_member" "masked_reader" {
  for_each       = var.enable_masking ? toset(var.masked_readers) : toset([])
  project        = var.project_id
  location       = var.region
  data_policy_id = google_bigquery_datapolicy_data_policy.pii_direct_sha256[0].data_policy_id
  role           = "roles/bigquerydatapolicy.maskedReader"
  member         = each.value
}
