# Trust anchors and intermediates bundled with PDF Sign Verifier
#
# Roots: CCA India (official RCAI) from https://cca.gov.in/root_certificate.html
# Licensed CA intermediates (RCAI 2022 / SPL): https://cca.gov.in/display_cert2022.php
#
# These intermediates are NOT trust anchors. They help build chains from
# end-entity Indian DSCs up to CCA India roots so verification does not
# fail as UNTRUSTED when the PDF omits intermediate certificates.
#
# Re-download periodically from CCA when new CAs are licensed.
