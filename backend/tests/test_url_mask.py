"""URLs with credentials: masked to show, restored on save, one line editable
without retyping the rest."""

from app.url_mask import MASK, mask, mask_url, restore
from tests.test_auth import claim


def test_secrets_are_masked_and_shape_kept():
    assert "abcdef-secret-token" not in mask_url("discord://123456789012345678/abcdef-secret-token")
    assert mask_url("mailtos://me:hunter22@smtp.example.com?to={email}&from=me@example.com") == \
        f"mailtos://{MASK}@smtp.example.com?to={{email}}&from={MASK}"
    assert mask_url("https://ntfy.sh/my-private-topic").startswith("https://ntfy.sh/my-")
    both = mask("discord://111/aaaaaaaaaaaaaa, tgram://bot1234567:bbbbbbbbbbbbbb/99999999")
    assert "aaaaaaaaaaaaaa" not in both and "bbbbbbbbbbbbbb" not in both and ", " in both


def test_restore_keeps_unchanged_urls_and_takes_new_ones():
    stored = "discord://111/aaaaaaaaaaaaaa, ntfy://ntfy.sh/topic-one"
    shown = mask(stored)
    assert restore(shown, stored) == stored
    edited = shown.split(", ")[0] + ", ntfy://ntfy.sh/topic-two"
    assert restore(edited, stored) == "discord://111/aaaaaaaaaaaaaa, ntfy://ntfy.sh/topic-two"
    try:
        restore(shown.replace("discord://", "slack://"), stored)
    except ValueError:
        pass
    else:
        raise AssertionError("an edited masked URL must be refused")


def test_settings_round_trip(client):
    claim(client)
    secret = "discord://1234567/very-secret-token-value, gotify://host.example/Atoken123456"
    client.put("/api/settings", json={"apprise_urls": secret})
    shown = {s["key"]: s["value"] for s in client.get("/api/settings").json()}["apprise_urls"]
    assert "very-secret-token-value" not in shown and MASK in shown
    # Saving the page untouched keeps the real values.
    assert client.put("/api/settings", json={"apprise_urls": shown}).status_code == 200
    from app.settings_store import current

    assert current().apprise_urls == secret
    # Adding a URL keeps the others without retyping them.
    client.put("/api/settings", json={"apprise_urls": shown + ", ntfy://ntfy.sh/new"})
    assert current().apprise_urls == secret + ", ntfy://ntfy.sh/new"
    log = client.get("/api/log?kind=changes").json()
    assert all("very-secret-token-value" not in str(e) for e in log)



def test_lookalike_urls_are_not_guessed():
    stored = "ntfy://ntfy.sh/topic-one, ntfy://ntfy.sh/topic-two"
    shown = mask(stored)
    assert shown.split(", ")[0] == shown.split(", ")[1]
    assert restore(shown, stored) == stored
    try:
        restore(shown.split(", ")[0], stored)
    except ValueError as exc:
        assert "look the same" in str(exc)
    else:
        raise AssertionError("dropping one of two lookalikes must ask, not guess")
