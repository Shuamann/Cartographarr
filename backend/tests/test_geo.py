from app.geo.lookup import _is_hosting, is_private


def test_residential_isps_are_not_hosting():
    # The regression that mattered: "google" matched Google Fiber and flagged
    # 122 of 130 IPs on a real dataset. Residential markers win.
    assert _is_hosting("Google Fiber Inc.") is False
    assert _is_hosting("Comcast Cable Communications, LLC") is False
    assert _is_hosting("AT&T Internet Services") is False
    assert _is_hosting("Charter Communications") is False


def test_real_hosts_and_vpns_still_flagged():
    assert _is_hosting("DataCamp Limited") is True
    assert _is_hosting("M247 Europe SRL") is True
    assert _is_hosting("Amazon.com, Inc.") is True
    assert _is_hosting("DigitalOcean, LLC") is True
    assert _is_hosting("Mullvad VPN AB") is True


def test_unknown_org_is_not_hosting():
    assert _is_hosting(None) is False
    assert _is_hosting("") is False
    assert _is_hosting("Some Regional Co-op") is False


def test_private_ranges():
    assert is_private("192.168.1.10") is True
    assert is_private("10.0.0.5") is True
    assert is_private("127.0.0.1") is True
    assert is_private("not-an-ip") is True  # unparseable is never mappable
    assert is_private("8.8.8.8") is False
