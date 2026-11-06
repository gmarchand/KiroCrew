"""Settings -> Advanced: which config keys the page lists, and the generic PATCH rule."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.config.schema import SCHEMA_REGISTRY
from kiro_crew.dashboard.handlers import config_all_settings as all_settings
from kiro_crew.dashboard.handlers.core_config_schema import _EDITABLE_CONFIG, _editable_config_spec

_BY_PATH = {e.path: e for e in SCHEMA_REGISTRY}

pytestmark = pytest.mark.asyncio


@web.middleware
async def _owner_identity(request, handler):
    request["user"] = "local-app"
    request["app"] = ""
    request.app["state"].owner_id = ""
    return await handler(request)


def _make_app() -> web.Application:
    from kiro_crew.dashboard.handlers import api_config_schema, api_kirocrew_config_patch

    app = web.Application(middlewares=[_owner_identity])
    app["state"] = MagicMock()
    app.router.add_patch("/api/config/kirocrew", api_kirocrew_config_patch)
    app.router.add_get("/api/config/schema", api_config_schema)
    return app


@pytest.fixture
def tmp_config(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"mcp_gateway": {"idle_timeout_secs": 120}}), encoding="utf-8")
    with patch("kiro_crew.config.loader.config_path", return_value=cfg_path):
        yield cfg_path


def _stored(cfg_path) -> dict:
    return json.loads(cfg_path.read_text(encoding="utf-8"))


async def _send(body: dict) -> tuple[int, dict]:
    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.patch("/api/config/kirocrew", json=body)
        return resp.status, await resp.json()


# ── Which keys are listed, and how ──


def test_a_secret_a_section_and_a_map_are_not_listed() -> None:
    sensitive = next(e for e in SCHEMA_REGISTRY if e.sensitive)
    assert all_settings.descriptor(sensitive) is None
    assert all_settings.descriptor(_BY_PATH["mcp_gateway"]) is None
    assert all_settings.descriptor(_BY_PATH["agent.env"]) is None


def test_the_motivating_list_key_is_editable_and_resettable() -> None:
    record = all_settings.descriptor(_BY_PATH["mcp_gateway.keep_alive_servers"])
    assert record is not None
    assert record["mode"] == "edit"
    assert record["control"] == "str_list"
    assert record["resettable"] is True


@pytest.mark.parametrize(
    "path",
    [
        "agent.dangerously_skip_permissions",
        "agent.sandbox",
        "tunnel.enabled",
        "slack.show_thinking",
    ],
)
def test_a_security_or_channel_key_is_never_edited_here(path: str) -> None:
    assert all_settings.descriptor(_BY_PATH[path])["mode"] in ("readonly", "control")
    assert _editable_config_spec(path) == _EDITABLE_CONFIG.get(path)


@pytest.mark.parametrize(
    "path,page",
    [
        ("agent.sandbox", {"tab": "developer", "sub": "config"}),
        ("slack.show_thinking", {"tab": "channels", "sub": "slack"}),
        ("slack.command", {"tab": "channels", "sub": "slack"}),
        ("memory.embedding_dim", {"tab": "developer", "sub": "memory"}),
        ("stt.transcribe_region", {"tab": "voice", "highlight": "voice.aws-region-transcribe"}),
    ],
)
def test_a_key_with_its_own_control_elsewhere_links_there(path: str, page: dict) -> None:
    assert all_settings.descriptor(_BY_PATH[path]) == {"mode": "control", "page": page}


def test_a_key_with_no_control_says_why_it_is_read_only() -> None:
    assert all_settings.descriptor(_BY_PATH["agent.kas_persist_mcp_sign_in"]) == {
        "mode": "readonly",
        "reason": all_settings.WHY_SIGN_IN,
    }
    reasons = {
        all_settings.WHY_SAFETY, all_settings.WHY_SIGN_IN, all_settings.WHY_REACH,
        all_settings.WHY_SHARE, all_settings.WHY_OWNED, all_settings.WHY_MARKER,
        all_settings.WHY_ALIAS, all_settings.WHY_TEXT, all_settings.WHY_LOCKED,
        all_settings.WHY_COMPOUND,
    }  # fmt: skip
    for entry in SCHEMA_REGISTRY:
        record = all_settings.descriptor(entry)
        if record and record["mode"] == "readonly":
            assert record.get("reason") in reasons, entry.path


def test_every_owning_page_link_names_a_real_tab_and_control() -> None:
    import json
    from pathlib import Path

    import kiro_crew

    registry = Path(kiro_crew.__file__).parent / "docs" / "settings-registry.generated.json"
    rows = json.loads(registry.read_text(encoding="utf-8"))["settings"]
    tabs = {r["tab"] for r in rows} | {"agent", "people", "developer"}
    ids = {r["id"] for r in rows}
    for path, page in all_settings._OWNING_PAGES.items():
        assert path in _BY_PATH, path
        assert page["tab"] in tabs, path
        if "highlight" in page:
            assert page["highlight"] in ids, path


def test_a_registry_configkey_is_a_link_row_never_read_only() -> None:
    """Every key a Settings control names (its configKey) links to that control."""
    for path in all_settings._registry_setting_ids():
        entry = _BY_PATH.get(path)
        record = all_settings.descriptor(entry) if entry else None
        assert record is None or record["mode"] == "control", path


def test_free_text_stays_read_only_unless_named() -> None:
    assert all_settings.descriptor(_BY_PATH["agent.kas_bundle_url"]) == {
        "mode": "readonly",
        "reason": all_settings.WHY_TEXT,
    }
    assert _editable_config_spec("agent.kas_bundle_url") is None


def test_every_readonly_and_text_path_names_a_real_key() -> None:
    for path in all_settings.READONLY_PATHS | all_settings.TEXT_EDIT_PATHS:
        assert path in _BY_PATH, path


def test_no_generic_rule_reaches_the_change_card_table() -> None:
    from kiro_crew.change_card_catalog import CardCatalogError
    from kiro_crew.dashboard.change_cards_settings import resolve_setting

    assert "mcp_gateway.keep_alive_servers" not in _EDITABLE_CONFIG
    with pytest.raises(CardCatalogError):
        resolve_setting({"path": "mcp_gateway.keep_alive_servers"})


#: Words that suggest a key decides who may reach the agent or what it may do.
_SECURITY_WORDS = (
    "sandbox", "jail", "approv", "permission", "trust", "allow", "auth", "exec",
    "danger", "unsafe", "insecure", "verify", "tls", "bind", "public", "expose",
    "token", "secret", "credential", "egress", "relay", "tunnel", "tailscale",
    "tailnet", "admission", "governance", "security", "redact", "hook", "skip",
    "isolation", "origin", "quarantine", "policy", "sign_in", "owner", "share",
    "sharing", "forward", "plain_http", "shell", "command",
)  # fmt: skip

#: Keys whose names match a word above, read and judged safe to edit here.
_REVIEWED_EDITABLE = frozenset(
    {
        "agent.mcp_quarantine_after_failures",
        "agent.tool_search_min_tokens",
        "agent.max_stop_hook_nudges",
        "agent.admission_gate",
        "agent.tool_approval_timeout_secs",
        "mcp_gateway.host_budget_max_procs",
        "mcp_gateway.host_budget_max_rss_mb",
        "mcp_gateway.host_budget_max_fds",
        "instances.tunnel_base_port",
        "dashboard.tailscale.keep_awake",
        "dashboard.shared_crew.principal_concurrency",
        "dashboard.shared_crew.crew_concurrency",
        "dashboard.shared_crew.typing_idle_seconds",
        # Which tier a lesson from a turn no person sent lands in; an enum whose
        # opt-in values only tighten that, so it is not a reach or run boundary.
        "memory.lesson_origin_gate",
        # Which tier a lesson from consolidation is stored in, and the order the
        # session-start rule block lists rules in: memory previews, not a reach or
        # run boundary.
        "memory.lesson_tier_policy",
        "memory.rule_authority_order",
        # How many chat sessions one shared agent process serves before another
        # starts: a pooling size, not sharing with another person.
        "agent.chat_runtime_sharing_max_sessions",
    }
)


def test_a_security_sounding_key_is_editable_only_after_review() -> None:
    """A new key whose name sounds like security fails here until someone decides."""
    unreviewed = []
    for entry in SCHEMA_REGISTRY:
        record = all_settings.descriptor(entry)
        if not record or record["mode"] != "edit":
            continue
        if any(word in entry.path.lower() for word in _SECURITY_WORDS):
            if entry.path not in _REVIEWED_EDITABLE:
                unreviewed.append(entry.path)
    assert unreviewed == [], (
        "add each to READONLY_PATHS, or to _REVIEWED_EDITABLE after checking it: " f"{unreviewed}"
    )


def test_every_reviewed_editable_key_is_a_real_key() -> None:
    assert sorted(_REVIEWED_EDITABLE - set(_BY_PATH)) == []


@pytest.mark.parametrize(
    "path",
    ["agent.conductor_own_child_verbs", "browser.live.mask_passwords", "messaging.dm_scope"],
)
async def test_an_approval_or_reach_key_is_read_only_on_the_page(tmp_config, path) -> None:
    """Approval skips, the password cover and DM sharing keep their own pages or none.

    `mask_passwords` has a curated rule, so the page's read-only list has to win over it.
    """
    record = all_settings.descriptor(_BY_PATH[path])
    assert record is not None and record["mode"] == "readonly", record
    if _editable_config_spec(path) is None:
        status, body = await _send({"path": path, "value": True})
        assert status == 400, body


def test_a_security_bounded_key_takes_only_the_loader_range() -> None:
    """A save the loader would clamp also logs possible tampering, so none may pass."""
    from kiro_crew.config.loader_builders import _SECURITY_BOUNDED_FIELDS

    checked = 0
    for section, key, lo, hi in _SECURITY_BOUNDED_FIELDS:
        path = f"{section}.{key}"
        spec = _editable_config_spec(path)
        record = all_settings.descriptor(_BY_PATH[path])
        for rule in (spec, record if record and record.get("mode") == "edit" else None):
            if rule is None or "min" not in rule:
                continue
            checked += 1
            assert lo <= rule["min"] and rule["max"] <= hi, (path, rule, (lo, hi))
    assert checked, "no bounded key has a write rule, so this test checks nothing"


async def test_patch_refuses_a_security_bounded_value_outside_the_loader_range(tmp_config) -> None:
    status, body = await _send({"path": "session.reconcile_max_kills", "value": 8})
    assert status == 400, body
    assert "reconcile_max_kills" not in _stored(tmp_config).get("session", {})

    status, body = await _send({"path": "session.reconcile_max_kills", "value": 5})
    assert status == 200, body
    assert _stored(tmp_config)["session"]["reconcile_max_kills"] == 5


async def test_patch_refuses_an_unset_that_is_not_a_boolean(tmp_config) -> None:
    status, body = await _send({"path": "mcp_gateway.keep_alive_servers", "unset": "yes"})
    assert (status, body.get("error")) == (400, "unset must be a boolean")


async def test_patch_refuses_unset_together_with_if_unset(tmp_config) -> None:
    status, body = await _send(
        {"path": "mcp_gateway.keep_alive_servers", "unset": True, "if_unset": True}
    )
    assert status == 400, body
    assert "unset is not allowed" in body["error"]


def _bare_entry(path: str, tags: tuple[str, ...] = ()) -> SimpleNamespace:
    """A schema entry no table names, so only the clause under test can block it."""
    return SimpleNamespace(path=path, tags=tags, type="boolean")


def test_a_tagged_key_gets_no_generic_rule() -> None:
    """Every tagged key also links to its channel page today; the tag alone must block too."""
    assert not all_settings._blocked(_bare_entry("zzq.plain"))
    assert all_settings._blocked(_bare_entry("zzq.plain", tags=("channel",)))


def test_a_moved_key_gets_no_generic_rule(monkeypatch) -> None:
    from kiro_crew.dashboard.handlers.core import _MOVED_CONFIG_FIELDS

    monkeypatch.setitem(_MOVED_CONFIG_FIELDS, "zzq.moved", "use its own endpoint")
    assert all_settings._blocked(_bare_entry("zzq.moved"))


def test_a_key_an_edition_locks_is_read_only_and_says_so(monkeypatch) -> None:
    import kiro_crew.edition_locks as edition_locks

    monkeypatch.setattr(edition_locks, "config_path_locked", lambda path: path == "zzq.locked")
    entry = _bare_entry("zzq.locked")
    assert all_settings._blocked(entry)
    assert all_settings._readonly_reason(entry) == all_settings.WHY_LOCKED


# ── The PATCH route ──


async def test_patch_writes_and_unsets_a_generic_list(tmp_config) -> None:
    status, _ = await _send({"path": "mcp_gateway.keep_alive_servers", "value": ["github"]})
    assert status == 200
    assert _stored(tmp_config)["mcp_gateway"]["keep_alive_servers"] == ["github"]

    status, _ = await _send({"path": "mcp_gateway.keep_alive_servers", "unset": True})
    assert status == 200
    stored = _stored(tmp_config)["mcp_gateway"]
    assert "keep_alive_servers" not in stored
    assert stored["idle_timeout_secs"] == 120


async def test_a_generic_write_reports_what_the_file_held_before(tmp_config) -> None:
    """The Advanced page undoes to this, since the masked view fills defaults in."""
    status, body = await _send({"path": "mcp_gateway.keep_alive_servers", "value": ["github"]})
    assert status == 200
    assert body["previous"] == {"stored": False}

    status, body = await _send({"path": "mcp_gateway.keep_alive_servers", "unset": True})
    assert status == 200
    assert body["previous"] == {"stored": True, "value": ["github"]}

    status, body = await _send({"path": "mcp_gateway.idle_timeout_secs", "value": 300})
    assert status == 200
    assert body["previous"] == {"stored": True, "value": 120}


@pytest.mark.parametrize(
    "path", ["resource_limits.max_open_files", "session.archive_retention_days"]
)
async def test_undo_puts_a_stored_null_back_on_a_nullable_int(tmp_config, path) -> None:
    """A config saved from the defaults stores null here; Undo resends exactly that.

    The retention key is the case an unset would get wrong: its default is 30 days,
    so removing the key would not restore the stored null.
    """
    section, leaf = path.split(".")
    tmp_config.write_text(json.dumps({section: {leaf: None}}), encoding="utf-8")

    status, body = await _send({"path": path, "value": 7})
    assert status == 200, body
    assert body["previous"] == {"stored": True, "value": None}

    status, body = await _send({"path": path, "value": body["previous"]["value"]})
    assert status == 200, body
    assert _stored(tmp_config)[section][leaf] is None


async def test_undo_puts_a_stored_numeric_string_back_as_its_number(tmp_config) -> None:
    """The loader reads "120" as 120, and the generic check refuses the string itself."""
    tmp_config.write_text(
        json.dumps({"mcp_gateway": {"idle_timeout_secs": "120"}}), encoding="utf-8"
    )

    status, body = await _send({"path": "mcp_gateway.idle_timeout_secs", "value": 300})
    assert status == 200, body
    assert body["previous"] == {"stored": True, "value": 120}

    status, body = await _send(
        {"path": "mcp_gateway.idle_timeout_secs", "value": body["previous"]["value"]}
    )
    assert status == 200, body
    assert _stored(tmp_config)["mcp_gateway"]["idle_timeout_secs"] == 120


async def test_undo_puts_a_stored_whole_float_back_as_an_integer(tmp_config) -> None:
    """The loader reads 120.0 on an integer key as 120; Undo must not drop it to the default."""
    tmp_config.write_text(
        json.dumps({"mcp_gateway": {"idle_timeout_secs": 120.0}}), encoding="utf-8"
    )

    status, body = await _send({"path": "mcp_gateway.idle_timeout_secs", "value": 600})
    assert status == 200, body
    assert body["previous"] == {"stored": True, "value": 120}

    status, body = await _send(
        {"path": "mcp_gateway.idle_timeout_secs", "value": body["previous"]["value"]}
    )
    assert status == 200, body
    assert _stored(tmp_config)["mcp_gateway"]["idle_timeout_secs"] == 120


@pytest.mark.parametrize(
    ("path", "stored", "new"),
    [
        ("mcp_gateway.idle_timeout_secs", "nope", 300),
        ("mcp_gateway.idle_timeout_secs", -5, 300),
        ("mcp_gateway.idle_timeout_secs", 10**13, 300),
        ("mcp_gateway.idle_timeout_secs", 10**400, 300),
        ("agent.log_level", "LOUD", "INFO"),
        ("agent.spawn_min_memory_gb", "inf", 3.0),
        ("agent.spawn_min_memory_gb", float("nan"), 3.0),
        ("mcp_gateway.keep_alive_servers", ["s"] * (all_settings._LIST_MAX_ITEMS + 1), ["a"]),
    ],
    ids=[
        "not-a-number",
        "below-min",
        "above-max",
        "too-big-for-a-float",
        "not-a-member",
        "not-finite-string",
        "not-finite-number",
        "too-many",
    ],
)
async def test_a_stored_value_the_route_refuses_is_reported_as_not_stored(
    tmp_config, path, stored, new
) -> None:
    """The loader reads the default for it, and Undo removing the key keeps that.

    Offering it back instead would make Undo fail every time with the route's own 400.
    """
    section, leaf = path.split(".")
    tmp_config.write_text(json.dumps({section: {leaf: stored}}), encoding="utf-8")

    status, body = await _send({"path": path, "value": new})
    assert status == 200, body
    assert body["previous"] == {"stored": False}


def test_every_generic_rule_field_is_one_undo_judges() -> None:
    """``_generic_rule_error`` mirrors the route for these fields only; a new one needs it too."""
    judged = {"generic", "type", "values", "min", "max", "max_len", "max_items", "max_item_len"}
    fields: set[str] = set()
    for path in all_settings._entries():
        spec = _editable_config_spec(path)
        if spec and spec.get("generic"):
            fields.update(spec)
    assert fields and fields <= judged, sorted(fields - judged)


async def test_patch_writes_a_generic_enum_and_refuses_a_value_outside_it(tmp_config) -> None:
    assert _editable_config_spec("agent.log_level")["generic"] is True
    status, body = await _send({"path": "agent.log_level", "value": "INFO"})
    assert status == 200, body
    assert _stored(tmp_config)["agent"]["log_level"] == "INFO"

    status, body = await _send({"path": "agent.log_level", "value": "LOUD"})
    assert status == 400, body
    assert _stored(tmp_config)["agent"]["log_level"] == "INFO"


@pytest.mark.parametrize("value", [True, "300", 1.5, None])
async def test_patch_refuses_a_generic_int_of_the_wrong_type(tmp_config, value) -> None:
    status, body = await _send({"path": "mcp_gateway.idle_timeout_secs", "value": value})
    assert status == 400, body
    assert _stored(tmp_config)["mcp_gateway"]["idle_timeout_secs"] == 120


@pytest.mark.parametrize("value", ["Europe/Lodnon", "PST", "../etc"])
async def test_patch_refuses_a_timezone_the_scheduler_cannot_load(tmp_config, value) -> None:
    status, body = await _send({"path": "timezone", "value": value})
    assert status == 400, body
    assert "timezone" not in _stored(tmp_config)


@pytest.mark.parametrize("value", ["Europe/London", "local", ""])
async def test_patch_stores_a_loadable_timezone(tmp_config, value) -> None:
    status, body = await _send({"path": "timezone", "value": value})
    assert status == 200, body
    assert _stored(tmp_config)["timezone"] == value


def test_a_key_another_action_owns_is_read_only() -> None:
    """A field whose help says a plain config write must not set it stays read-only."""
    owned = [
        e.path
        for e in SCHEMA_REGISTRY
        if "plain config write" in e.help
        and (all_settings.descriptor(e) or {}).get("mode") == "edit"
    ]
    assert owned == []
    # Its own control is the embedding-model card, so the row links there.
    assert all_settings.descriptor(_BY_PATH["memory.embedding_dim"])["mode"] == "control"
    assert _editable_config_spec("memory.embedding_dim") is None


def test_every_editable_top_level_key_is_saved_at_the_top_level() -> None:
    """A field saved under another section (an alias) would take a write that changes nothing."""
    from kiro_crew.config.loader import KiroCrewConfig

    saved = KiroCrewConfig().to_dict()
    misplaced = [
        e.path
        for e in SCHEMA_REGISTRY
        if "." not in e.path
        and (all_settings.descriptor(e) or {}).get("mode") == "edit"
        and e.path not in saved
    ]
    assert misplaced == []


async def test_patch_refuses_a_generic_bool_given_a_string(tmp_config) -> None:
    status, _ = await _send({"path": "mcp_gateway.read_buffer_limit_bytes", "value": "1"})
    assert status == 400


async def test_patch_refuses_a_read_only_key(tmp_config) -> None:
    status, body = await _send({"path": "agent.dangerously_skip_permissions", "value": True})
    assert status == 400
    assert "not editable" in body["error"]
    assert "agent" not in _stored(tmp_config)


async def test_patch_refuses_unset_on_a_curated_key(tmp_config) -> None:
    status, body = await _send({"path": "session.timeout_secs", "unset": True})
    assert status == 400
    assert "unset is not allowed" in body["error"]


async def test_schema_route_carries_the_descriptor() -> None:
    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.get("/api/config/schema")
        entries = {e["path"]: e for e in (await resp.json())["entries"]}
    assert entries["mcp_gateway.keep_alive_servers"]["allSettings"]["mode"] == "edit"
    assert entries["agent.dangerously_skip_permissions"]["allSettings"] == {
        "mode": "readonly",
        "reason": all_settings.WHY_SAFETY,
    }
    assert "allSettings" not in entries["mcp_gateway"]


def test_a_dashboard_route_key_links_to_its_control() -> None:
    record = all_settings.descriptor(_BY_PATH["dashboard.quick_send"])
    assert record is not None and record["mode"] == "control"
    assert isinstance(record["settingId"], str) and record["settingId"]


@pytest.mark.parametrize(
    "path",
    [
        "dashboard.theme_mode",
        "dashboard.translucent_panels",
        "dashboard.language",
        "dashboard.theme_color",
        "dashboard.privacy_ack_version",
    ],
)
def test_a_key_the_theme_route_writes_is_never_edited_here(path: str) -> None:
    """The browser's theme state refreshes only on PUT /api/config/theme."""
    record = all_settings.descriptor(_BY_PATH[path])
    assert record is not None and record["mode"] != "edit"
    assert _editable_config_spec(path) is None or path in _EDITABLE_CONFIG


def test_a_theme_route_link_names_a_real_settings_control() -> None:
    import json
    from pathlib import Path

    import kiro_crew

    registry = Path(kiro_crew.__file__).parent / "docs" / "settings-registry.generated.json"
    ids = {s["id"] for s in json.loads(registry.read_text(encoding="utf-8"))["settings"]}
    for path in ("dashboard.theme_mode", "dashboard.translucent_panels", "dashboard.language"):
        record = all_settings.descriptor(_BY_PATH[path])
        assert record is not None and record["mode"] == "control"
        assert record["settingId"] in ids


def test_a_preview_flag_links_to_feature_previews() -> None:
    assert all_settings.descriptor(_BY_PATH["dashboard.feature_previews.webhooks"]) == {
        "mode": "control",
        "page": {"tab": "developer", "sub": "feature-previews"},
    }
    # Its curated rule (the Feature Previews toggle's writer) stays; no generic one is added.
    assert all_settings.generic_spec("dashboard.feature_previews.webhooks") is None


@pytest.mark.parametrize(
    "path", ["session.archive_retention_days", "resource_limits.xdist_auto_cap"]
)
async def test_a_loader_sentinel_saves_and_one_below_it_does_not(tmp_config, path) -> None:
    """``-1`` is a mode these loaders accept (no cleanup / sized from memory)."""
    section, key = path.split(".")
    status, body = await _send({"path": path, "value": -1})
    assert status == 200, body
    assert _stored(tmp_config)[section][key] == -1

    status, body = await _send({"path": path, "value": -2})
    assert status == 400, body
    assert _stored(tmp_config)[section][key] == -1


def test_every_sentinel_floor_names_an_editable_integer_key() -> None:
    """A floor for a key that left the page, or was never an integer, is a stale row."""
    for path, floor in all_settings._SENTINEL_FLOORS.items():
        spec = all_settings.generic_spec(path)
        assert spec is not None and spec["type"] == "int", path
        assert spec["min"] == floor, path


def test_no_key_drawn_as_a_link_row_gets_a_generic_write_rule() -> None:
    """Its own page's writer holds the checks; a second, looser writer must not exist."""
    linked = [
        e.path
        for e in SCHEMA_REGISTRY
        if (all_settings.descriptor(e) or {}).get("mode") == "control"
    ]
    assert "stt.provider" in linked
    assert [p for p in linked if all_settings.generic_spec(p) is not None] == []


async def test_patch_refuses_a_key_whose_control_lives_on_another_page(tmp_config) -> None:
    status, body = await _send({"path": "stt.provider", "value": "apple"})
    assert status == 400, body
    assert "provider" not in _stored(tmp_config).get("stt", {})
