"""GeoIP: MaxMind GeoLite2 City + ASN, read locally.

City gives the pin. ASN gives the credential-sharing signal — a stream from a
hosting/VPN ASN explains most "impossible travel" hits better than distance
does, and it's free under the same licence key.

No mmdb files, or no licence key, is a normal state: lookups return None and
the map simply has fewer pins. Nothing here raises into the sync path.
"""

from __future__ import annotations

import ipaddress
import logging
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import geoip2.database
import geoip2.errors
import httpx

log = logging.getLogger(__name__)

EDITIONS = {"GeoLite2-City": "city.mmdb", "GeoLite2-ASN": "asn.mmdb"}
DOWNLOAD = "https://download.maxmind.com/geoip/databases/{edition}/download"
"""The modern endpoint, which takes account id + licence key as basic auth.
Not /app/geoip_download — that one only accepts the key as a query parameter
and answers 401 to an Authorization header, which puts the secret in every URL
and log line."""

# ponytail: substring match on the ASN org name. Feeds a review flag, not a
# ban, so a heuristic is enough. Upgrade path if it stops being enough:
# MaxMind's paid Anonymous IP database.
HOSTING_HINTS = frozenset(
    """amazon aws googlecloud cloud microsoft azure digitalocean linode vultr
    choopa ovh hetzner contabo leaseweb m247 datacamp oracle scaleway upcloud
    mullvad nordvpn expressvpn surfshark privateinternetaccess protonvpn
    cyberghost ipvanish torguard windscribe datacenter hosting colocation
    vpn""".split()
)

# Checked FIRST, and it matters: "Google Fiber Inc." is a residential ISP that
# matched `google` and made 94% of flagged IPs false positives. Consumer ISPs
# love borrowing cloud-sounding words, so the residential marker wins.
RESIDENTIAL_HINTS = frozenset(
    """fiber fibre broadband cable telecom telecommunication communications
    wireless dsl cablevision internet services isp networks-inc""".split()
)


def _is_hosting(org: str | None) -> bool:
    if not org:
        return False
    lowered = org.lower()
    if any(hint in lowered for hint in RESIDENTIAL_HINTS):
        return False
    return any(hint in lowered for hint in HOSTING_HINTS)


def is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local


def ensure_databases(
    geoip_dir: Path, account_id: str, license_key: str, max_age_days: int = 7
) -> None:
    """Download or refresh the mmdb files. Never raises — logs and moves on."""
    geoip_dir.mkdir(parents=True, exist_ok=True)
    if not (account_id and license_key):
        log.info("No MaxMind credentials; skipping GeoIP download")
        return

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    for edition, filename in EDITIONS.items():
        target = geoip_dir / filename
        if target.exists():
            mtime = datetime.fromtimestamp(target.stat().st_mtime, UTC)
            if mtime > cutoff:
                continue
        try:
            _download(edition, target, account_id, license_key)
            log.info("GeoIP updated: %s", filename)
        except Exception as exc:  # noqa: BLE001 - a stale/missing db is survivable
            log.warning("GeoIP download failed for %s: %s", edition, exc)


def _download(edition: str, target: Path, account_id: str, license_key: str) -> None:
    url = DOWNLOAD.format(edition=edition)
    auth = (account_id, license_key)
    with httpx.stream(
        "GET", url, params={"suffix": "tar.gz"}, auth=auth, timeout=120, follow_redirects=True
    ) as resp:
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            for chunk in resp.iter_bytes():
                tmp.write(chunk)
            archive = Path(tmp.name)

    try:
        with tarfile.open(archive) as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith(".mmdb"))
            extracted = tar.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"no mmdb inside {edition} archive")
            target.write_bytes(extracted.read())
    finally:
        archive.unlink(missing_ok=True)


class GeoResolver:
    """Opens the mmdb readers once and answers lookups.

    Readers are memory-mapped, so holding them open is the cheap way; a lookup
    is microseconds and never touches the network.
    """

    def __init__(self, geoip_dir: Path) -> None:
        self._city = self._open(geoip_dir / EDITIONS["GeoLite2-City"])
        self._asn = self._open(geoip_dir / EDITIONS["GeoLite2-ASN"])

    @staticmethod
    def _open(path: Path):
        if not path.exists():
            log.warning("GeoIP database missing: %s", path)
            return None
        try:
            return geoip2.database.Reader(str(path))
        except Exception as exc:  # noqa: BLE001
            log.warning("GeoIP database unreadable (%s): %s", path, exc)
            return None

    @property
    def available(self) -> bool:
        return self._city is not None

    def lookup(self, ip: str) -> dict | None:
        """Return location fields for an IP, or None if it can't be placed."""
        if is_private(ip):
            return {"ip": ip, "is_private": True}

        result: dict = {"ip": ip, "is_private": False}

        if self._city is not None:
            try:
                city = self._city.city(ip)
                result.update(
                    lat=city.location.latitude,
                    lon=city.location.longitude,
                    accuracy_radius=city.location.accuracy_radius,
                    timezone=city.location.time_zone,
                    city=city.city.name,
                    region=city.subdivisions.most_specific.name,
                    country=city.country.name,
                    country_code=city.country.iso_code,
                    postal=city.postal.code,
                )
            except geoip2.errors.AddressNotFoundError:
                pass
            except Exception as exc:  # noqa: BLE001
                log.warning("City lookup failed for %s: %s", ip, exc)

        if self._asn is not None:
            try:
                asn = self._asn.asn(ip)
                org = asn.autonomous_system_organization
                result.update(
                    asn=asn.autonomous_system_number,
                    asn_org=org,
                    is_hosting=_is_hosting(org),
                )
            except geoip2.errors.AddressNotFoundError:
                pass
            except Exception as exc:  # noqa: BLE001
                log.warning("ASN lookup failed for %s: %s", ip, exc)

        return result if len(result) > 2 else None

    def close(self) -> None:
        for reader in (self._city, self._asn):
            if reader is not None:
                reader.close()
