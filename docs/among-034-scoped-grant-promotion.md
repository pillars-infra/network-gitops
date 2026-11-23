# Among 0.3.34 scoped grant promotion

Reuse the unique successful release run `45094412760`, signed tag `v0.3.34`,
source `07fe355511ab9f41f06a5a1a941a144b9ecab35a`. The immutable image is
`sha256:27288e43138c052e9804600c512f296832b2037ea9a016e04a08adb4bb024629`.
Hub chart OCI is
`sha256:e84543b77175300991faef7cc2baa32e0a56aec87ed0494d4ef70354b6560e26`,
archive SHA256
`02f1f7fefc18fe1b132cb6296e6d2565f53af1649e0fa681f914b1131a1ea6be`.

The image and all four chart OCI digests have verified Cosign certificates for
this exact tag's release workflow and GitHub issuer. Both architecture
provenance/SBOM statements match their image subject digests; provenance VCS
source/revision match this source exactly. Every OCI chart archive matches the
GitHub release asset byte for byte. No artifact is rebuilt for promotion.

Promote the existing Hub runtime cohort first. After actual Hub readiness, promote
the main Agent/gateway cohort to the same verified digest. Its existing chart
shares one image value for both binaries. Keep the broker image, cluster identity,
grants and managedAccess setting unchanged. Bootstrap additive resourceNames and the reviewed
Kubernetes-native set schemas from this chart; the previous uniqueItems=true
schema was rejected by server dry-run and must not be reapplied. Upgrade the
actual Atlantic Agent after the Hub. The new Agent requires grant.poll.v2;
legacy Agents receive named grants only as revocation cleanup, never broadened
rules. Existing grants without resourceNames retain their original semantics.

Only after both versions and schemas are verified may the separate scoped
release grant and exact generation owner approval be bootstrapped. Read its
actual UID into the Cloud execution binding; do not lend the interactive Admin
wildcard grant to Actions. Verify actual remote identity, named SSA canary and
cleanup. Hub Ready and import Ready alone are not that acceptance.
