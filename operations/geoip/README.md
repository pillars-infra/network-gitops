# Pinned country data for authoritative DNS

The existing PowerDNS image includes November 2020 legacy databases. Live
probes proved a Finnish source was classified as US and a Malaysian source as
DE. The existing backend supports MMDB, so use current country data rather than
special-case the probes' addresses.

The only source declaration is `geoip-source.json` inside the existing
`regional-routing/powerdns-cloud-authorities` ConfigMap. It pins upstream and
retained artifact URLs, compressed and uncompressed SHA-256, version and license.
The November 2026 uncompressed bytes also match DB-IP's published SHA-1 and MD5.

Native capability gap: the stock image cannot supply current country data and
monthly upstream downloads are not a durable cold-start dependency. A signed
`geoip-dbip-country-*` tag runs the small native Actions publication workflow.
It downloads the reviewed bytes once, verifies both hashes, retains the gzip in
GitHub Releases, and attaches provenance and attribution. Retries reuse an
existing exact asset; no image build or new reconciliation service is added.

After that release exists, the normal reviewed native static-release deploys
it. A bounded init container fetches only the retained public artifact, checks
compressed/uncompressed hashes and size bounds, then atomically writes the
read-only MMDB volume. It has no service-account token, host mount or privileges.
The old 2020 database is not a silent fallback. RollingUpdate retains the other
frontends if the new artifact cannot initialize.

The DNS proxy binds its upstream sockets to its declared node overlay address,
so ECS trust uses a stable local relay identity rather than whichever transit
interface a route selected. No host route or public authority is changed.

Data attribution: IP Geolocation by DB-IP, https://db-ip.com. Unmodified DB-IP
Lite country data, November 2026. License: CC BY 4.0,
https://creativecommons.org/licenses/by/4.0/.
The same attribution ships in the ConfigMap, release notes and NOTICE asset.

Sources:
- https://db-ip.com/db/download/ip-to-country-lite
- https://db-ip.com/db/format/ip-to-country-lite/mmdb.html
- https://doc.powerdns.com/authoritative/backends/geoip.html
