"""Failed sign-ins are counted per caller, which behind a proxy means the
forwarded address rather than the proxy everyone shares."""

from tests.test_auth import claim

PASSWORD = "correct horse battery staple"


def attempt(client, username="admin", password="wrong", headers=None):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=headers or {})


def test_the_header_is_ignored_from_an_untrusted_caller(client):
    from app.auth.deps import client_address

    claim(client)
    # Anyone can write this header, so it counts for nothing until a proxy we
    # named is the one calling.
    for _ in range(30):
        attempt(client, headers={"X-Forwarded-For": "203.0.113.9"})
    assert attempt(client, headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 429
    assert client_address is not None


def test_behind_a_trusted_proxy_each_caller_is_counted_alone(client):
    claim(client)
    client.put("/api/settings", json={"trusted_proxy_ips": "127.0.0.0/8"})

    # One caller burns through the per address limit.
    for _ in range(30):
        attempt(client, headers={"X-Forwarded-For": "203.0.113.9"})
    assert attempt(client, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 429
    # Somebody else behind the same proxy is not locked out by them.
    assert attempt(client, username="someone", headers={"X-Forwarded-For": "198.51.100.4"}).status_code == 401


def test_the_chain_is_read_past_our_own_proxies(client):
    from app.auth.deps import client_address

    claim(client)
    client.put("/api/settings", json={"trusted_proxy_ips": "127.0.0.0/8, 10.0.0.0/8"})

    class Request:
        def __init__(self, peer, chain):
            self.client = type("C", (), {"host": peer})()
            self.headers = {"x-forwarded-for": chain}

    # The caller, then our edge proxy, then the app: read from the right, past
    # anything we trust.
    assert client_address(Request("127.0.0.1", "203.0.113.9, 10.1.2.3")) == "203.0.113.9"
    assert client_address(Request("127.0.0.1", "203.0.113.9")) == "203.0.113.9"
    # Nothing but our own proxies in the chain: nobody else to blame.
    assert client_address(Request("127.0.0.1", "10.1.2.3")) == "127.0.0.1"
    # An untrusted caller is taken at face value.
    assert client_address(Request("198.51.100.7", "203.0.113.9")) == "198.51.100.7"
