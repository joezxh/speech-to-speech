"""Tests for the deployment parameter platform (spec §11.2).

`demo/` and `src/` are both put on `sys.path` here rather than being assumed:
`param_platform` is a demo-local package, and `speech_to_speech` has to be this
checkout — a published runtime of the same name in site-packages is older and
lacks the YAML config layer the validator calls.

Nothing here needs docker, a GPU or a database: the store goes to `tmp_path` and
the publish flow's side effects are replaced, so what is tested is the logic
that decides, not the deployment it decides about.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
for _candidate in (REPO / "demo", REPO / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from param_platform import (  # noqa: E402
    catalog,
    compose_runner,
    drafts,
    layout,
    publish_flow,
    renderer,
    store,
    validator,
)

CATALOG_PATH = REPO / "docs" / "parameter-catalog.yaml"
SOURCE_ROOT = REPO / "src" / "speech_to_speech"
MAC_CONFIG = REPO / "example_configs" / "mac.yaml"


@pytest.fixture(scope="module")
def loaded() -> catalog.Catalog:
    result = catalog.load(CATALOG_PATH)
    assert result.available, result.hint
    return result


@pytest.fixture(scope="module")
def entries(loaded: catalog.Catalog) -> dict:
    return loaded.by_key()


def _mac_text(profile: str = "mac", num_pipelines: object | None = None) -> str:
    """`example_configs/mac.yaml`, optionally renamed and re-counted.

    Renaming rather than pasting keeps this test on the one profile the spec
    names as the golden case (§11.2) even when the profile under test changes.
    """
    text = MAC_CONFIG.read_text(encoding="utf-8")
    if profile != "mac":
        text = text.replace("  mac:", f"  {profile}:", 1)
    if num_pipelines is not None:
        text = text.replace(
            f"  {profile}:\n", f"  {profile}:\n    num_pipelines: {num_pipelines}\n", 1
        )
    return text


def _document(profile: str = "prod") -> dict:
    return {
        "schema_version": 1,
        "blocks": {
            "vad": {"kind": "vad", "backend": "silero", "settings": {"min_silence_ms": 700}},
            "tts": {"kind": "tts", "backend": "qwen3"},
        },
        "pipelines": {
            profile: {
                "stages": {"vad": "vad", "stt": "stt", "llm": "llm", "tts": "tts"},
                "num_pipelines": 2,
            }
        },
    }


# ── catalog ──────────────────────────────────────────────────────────────────


def test_catalog_pins_its_schema(loaded: catalog.Catalog):
    assert loaded.schema == catalog.EXPECTED_SCHEMA
    assert loaded.entries, "the catalog is empty"


def test_catalog_keys_are_ambiguous_only_where_declared(loaded: catalog.Catalog):
    """`<stage>.<name>` is the patch key; two backends may share one.

    The shared ones are listed in `variant_keys`, so the patch key stays
    unambiguous for everything else — a console writes `vad.min_silence_ms`
    without naming a block.
    """
    seen: set[str] = set()
    duplicated: set[str] = set()
    for entry in loaded.entries:
        if entry.key in seen:
            duplicated.add(entry.key)
        else:
            seen.add(entry.key)
    assert duplicated == set(loaded.variant_keys)


def test_exposure_filter_is_cumulative(loaded: catalog.Catalog):
    basic = loaded.filtered(exposure="basic")
    advanced = loaded.filtered(exposure="advanced")
    assert {entry.key for entry in basic} <= {entry.key for entry in advanced}
    assert len(basic) < len(advanced) <= len(loaded.entries)
    assert all(entry.exposure != "ops" for entry in advanced)

    with pytest.raises(catalog.CatalogError):
        loaded.filtered(exposure="superuser")


def test_ops_entries_state_their_risk_class(loaded: catalog.Catalog):
    """Spec §7.2: an `ops` parameter without a risk category is not reviewable."""
    keyworded = ("安全", "隐私", "环境绑定")
    thin = [
        entry.key
        for entry in loaded.entries
        if entry.exposure == "ops" and not any(word in entry.risk for word in keyworded)
    ]
    assert thin == []


def test_hot_parameters_reach_sessions_only(loaded: catalog.Catalog):
    """Spec §2.2: `hot` means chain B can apply it, which is per-session only."""
    wrong = [(entry.key, entry.impact) for entry in loaded.entries if entry.effect == "hot" and entry.impact != "session"]
    assert wrong == []


def test_arguments_class_entries_name_a_field_the_source_still_has(loaded: catalog.Catalog):
    """The drift check §11.2 asks for, in the direction that can be verified.

    Every `arguments_classes/*.py` reference must still contain a field with the
    catalog's name: a rename in the backend without a catalog update is what
    makes a publish write a key `validate_config` then rejects.
    """
    drifted: list[str] = []
    checked = 0
    for entry in loaded.entries:
        relative = entry.source_ref.split(":", 1)[0].split(" (")[0].strip()
        if not relative.startswith("arguments_classes/"):
            continue
        checked += 1
        source = SOURCE_ROOT / relative
        name = entry.name.rsplit(".", 1)[-1]
        if not source.is_file():
            drifted.append(f"{entry.key}: {relative} is gone")
        elif name not in source.read_text(encoding="utf-8", errors="ignore"):
            drifted.append(f"{entry.key}: {name} is not in {relative}")
    assert checked > 100, f"only {checked} entries reference arguments_classes"
    assert drifted == []


# ── validator ────────────────────────────────────────────────────────────────


def test_example_config_passes(entries: dict):
    result = validator.validate(_mac_text(), "mac", entries=entries)
    assert result["ok"], result["errors"]
    assert result["checks"]["parse"] == "ok"


def test_string_num_pipelines_is_refused(entries: dict):
    result = validator.validate(_mac_text(num_pipelines='"2"'), "mac", entries=entries)
    assert not result["ok"]
    assert any("num_pipelines" in (error.get("field") or "") for error in result["errors"])


def test_wrong_schema_version_is_refused(entries: dict):
    text = _mac_text().replace("schema_version: 1", "schema_version: 2", 1)
    result = validator.validate(text, "mac", entries=entries)
    assert not result["ok"]
    assert any(error.get("field") == "schema_version" for error in result["errors"])


def test_unknown_top_level_key_is_refused(entries: dict):
    result = validator.validate(_mac_text() + "\nextra_key: 1\n", "mac", entries=entries)
    assert not result["ok"]
    assert any("extra_key" in error["message"] for error in result["errors"])


def test_vram_budget_refuses_more_pipelines_than_the_card_holds(entries: dict):
    """Step 4 of chain A: 12 GB fits two pipelines at 4.6 GB with 15 % headroom."""
    result = validator.validate(_mac_text(num_pipelines=10), "mac", entries=entries, vram_gb=12.0)
    assert not result["ok"]
    budget = [error for error in result["errors"] if error.get("details")]
    assert budget, result["errors"]
    assert budget[0]["field"] == "runtime.num_pipelines"
    assert budget[0]["details"]["max_allowed"] == 2
    assert result["checks"]["vram"].startswith("failed")


def test_vram_budget_without_a_measurement_says_so(entries: dict, monkeypatch):
    monkeypatch.delenv("PARAM_VRAM_GB", raising=False)
    result = validator.validate(_mac_text(), "mac", entries=entries)
    assert result["checks"]["vram"].startswith("skipped")


def test_types_come_from_the_catalog(entries: dict):
    integer_key = next(entry.key for entry in entries.values() if entry.type == "integer")
    string_key = next(entry.key for entry in entries.values() if entry.type == "string")

    errors, _ = validator.check_values(
        {integer_key: True, string_key: 700, "vad.not_a_parameter": 1}, entries
    )
    messages = {error["field"]: error["message"] for error in errors}
    # `True` is an int in Python; the check has to reject it anyway.
    assert messages[integer_key] == "expected integer, got bool"
    assert messages[string_key] == "expected string, got int"
    assert messages["vad.not_a_parameter"] == "unknown parameter"


def test_a_required_parameter_cannot_be_cleared(entries: dict):
    """`null` means "back to the default", which is not available for these."""
    required = [entry for entry in entries.values() if entry.required]
    if not required:
        pytest.skip("the catalog marks no parameter as required")
    errors, _ = validator.check_values({required[0].key: None}, entries)
    assert [error["field"] for error in errors] == [required[0].key]
    assert "required" in errors[0]["message"]


def test_env_reference_is_accepted_but_a_quoted_one_is_a_warning(entries: dict):
    key = next(entry.key for entry in entries.values() if entry.type == "string" and entry.stage != "env")
    errors, warnings = validator.check_values({key: {"env": "SOME_KEY"}}, entries)
    assert errors == []
    assert warnings == []

    errors, warnings = validator.check_values({key: "{env: SOME_KEY}"}, entries)
    assert errors == []
    assert warnings and "must be a mapping" in warnings[0]["message"]


# ── renderer and layout ──────────────────────────────────────────────────────


def test_rendering_the_same_patch_twice_is_byte_identical(entries: dict):
    """Spec §11.2: an audit diff of "no change" must not show noise."""
    first, applied, refused = renderer.render_yaml(
        _document(), "prod", {"tts.qwen3_tts_speaker": "Ethan"}, entries
    )
    second, _, _ = renderer.render_yaml(_document(), "prod", {"tts.qwen3_tts_speaker": "Ethan"}, entries)
    assert first == second
    assert applied == ["tts.qwen3_tts_speaker"]
    assert refused == []
    assert 'qwen3_tts_speaker: Ethan' in first


def test_dumping_a_dumped_document_is_stable(entries: dict):
    text, _, _ = renderer.render_yaml(_document(), "prod", {"tts.qwen3_tts_speaker": "Ethan"}, entries)
    body = text[text.index("schema_version") :]
    once = renderer.dump_yaml(yaml.safe_load(body))
    twice = renderer.dump_yaml(yaml.safe_load(once[once.index("schema_version") :]))
    assert once == twice


def test_a_null_patch_removes_the_key_and_the_container_it_emptied(entries: dict):
    document = _document()
    applied, refused = layout.apply(document, "prod", {"vad.min_silence_ms": None}, entries)
    assert refused == []
    assert applied == ["vad.min_silence_ms"]
    assert "settings" not in document["blocks"]["vad"]


def test_a_key_with_no_location_is_refused_rather_than_dropped(entries: dict):
    text, applied, refused = renderer.render_yaml(
        copy.deepcopy(_document()), "prod", {"deploy.base_image": "s2s:latest"}, entries
    )
    assert applied == []
    assert refused and "compose" in refused[0]["reason"]
    assert "base_image" not in text


def test_a_patch_needs_the_block_it_belongs_to(entries: dict):
    document = _document()
    document["blocks"].pop("vad")
    _, refused = layout.apply(document, "prod", {"vad.min_silence_ms": 900}, entries)
    assert refused and refused[0]["key"] == "vad.min_silence_ms"
    assert "vad" in refused[0]["reason"]


def test_an_env_reference_dumps_on_one_line():
    """Quoted, `{env: NAME}` becomes a literal credential (spec §12 R9)."""
    text = renderer.dump_yaml({"blocks": {"llm": {"settings": {"api_key": {"env": "OPENAI_API_KEY"}}}}})
    assert "api_key: {env: OPENAI_API_KEY}" in text


def test_env_rendering_keeps_comments_order_and_unknown_keys():
    existing = "# a comment\nA=1\nB=2\n"
    text, applied = renderer.render_env(existing, {"A": "9", "C": "3"})
    assert text.splitlines() == ["# a comment", "A=9", "B=2", "C=3"]
    assert applied == ["A", "C"]


def test_env_deletion_removes_the_line_and_stays_removed():
    text, applied = renderer.render_env("A=1\nB=2\n", {"B": None})
    assert text == "A=1\n"
    assert applied == ["B"]


def test_env_booleans_are_written_as_numbers():
    text, _ = renderer.render_env("", {"FEATURE": True, "OTHER": False})
    assert text.splitlines() == ["FEATURE=1", "OTHER=0"]


def test_diff_values_separates_an_int_from_its_string():
    changes = renderer.diff_values({"vad.min_silence_ms": 700}, {"vad.min_silence_ms": "700"})
    assert changes == [{"key": "vad.min_silence_ms", "before": 700, "after": "700"}]


# ── drafts: the merge, the mask and the stale base ───────────────────────────


@pytest.fixture
def draft_env(tmp_path, monkeypatch):
    """A store in `tmp_path` and a publish flow that renders without touching disk."""
    monkeypatch.setattr(store, "_db_path", tmp_path / "params.sqlite3")
    store.init()
    monkeypatch.setattr(drafts, "live_version", lambda profile: 3)
    monkeypatch.setattr(drafts, "profile_path", lambda profile: tmp_path / f"{profile}.yaml")
    (tmp_path / "prod.yaml").write_text("schema_version: 1\n", encoding="utf-8")

    def fake_render(profile, values, *, environ=None):
        return SimpleNamespace(
            text="schema_version: 1\n",
            values=values,
            applied=sorted(values),
            env_text=None,
            expected_size=2,
            resolved={"pipelines": [profile]},
            warnings=[],
        )

    monkeypatch.setattr(drafts, "render", fake_render)
    return tmp_path


def test_saving_one_field_keeps_the_others(draft_env):
    store.put_draft("prod", {"vad.min_silence_ms": 700}, 3, "zhangsan")
    result = drafts.save_draft("prod", {"vad.thresh": 0.6}, base_version=3, actor="zhangsan")
    assert result["draft"] == {"vad.min_silence_ms": 700, "vad.thresh": 0.6}
    assert result["validation"]["expected_pool_size"] == 2


def test_a_masked_secret_is_not_written_back(draft_env):
    """A.0 sends `***`; storing it literally would set the password to `***`."""
    store.put_draft("prod", {"llm.responses_api_api_key": {"env": "KEY"}}, 3, "zhangsan")
    result = drafts.save_draft(
        "prod",
        {"llm.responses_api_api_key": drafts.MASK, "vad.min_silence_ms": 900},
        base_version=3,
    )
    assert result["skipped_masked"] == ["llm.responses_api_api_key"]
    assert result["draft"]["llm.responses_api_api_key"] == {"env": "KEY"}
    assert drafts.MASK not in str(result["draft"])


def test_a_stale_base_version_is_a_conflict(draft_env):
    with pytest.raises(drafts.FlowError) as raised:
        drafts.save_draft("prod", {"vad.thresh": 0.6}, base_version=2)
    assert raised.value.status == 409
    assert raised.value.code == "version_conflict"


def test_saving_is_audited_and_the_audit_names_the_masked_keys(draft_env):
    drafts.save_draft("prod", {"llm.responses_api_api_key": drafts.MASK}, base_version=3, actor="lisi")
    entry = store.list_audit("prod")[0]
    assert entry["action"] == "draft.save"
    assert entry["actor"] == "lisi"
    assert entry["detail"]["masked_skipped"] == ["llm.responses_api_api_key"]


def test_a_typed_secret_never_reaches_the_audit_log(draft_env):
    """A.0 masks it on the way out; the audit must not reintroduce it.

    The draft has to hold the value an operator typed — it is what the next
    publish writes — so the audit stores the *key* and nothing else.
    """
    literal = "sk-live-do-not-log"
    drafts.save_draft(
        "prod", {"llm.responses_api_api_key": literal}, base_version=3, actor="zhangsan"
    )
    assert literal not in str(store.list_audit("prod"))


def test_an_unknown_profile_is_refused_before_anything_is_rendered(draft_env):
    with pytest.raises(drafts.FlowError) as raised:
        drafts.read_draft("missing")
    assert raised.value.status == 404


# ── store: append-only history ──────────────────────────────────────────────


@pytest.fixture
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", tmp_path / "params.sqlite3")
    store.init()
    return store


def test_a_rollback_is_a_new_version_pointing_at_the_old_one(fresh_store):
    first = fresh_store.create_version("prod", {"vad.min_silence_ms": 700}, status="live")
    second = fresh_store.create_version("prod", {"vad.min_silence_ms": 900}, status="live")
    third = fresh_store.create_version(
        "prod", {"vad.min_silence_ms": 700}, status="rolled_back", rolled_back_to=first
    )
    assert (first, second, third) == (1, 2, 3)
    assert [row["version"] for row in fresh_store.list_versions("prod")] == [3, 2, 1]
    # The version that was reverted is still a valid target: undo the undo.
    assert fresh_store.latest_live("prod")["version"] == 3
    assert fresh_store.latest_live("prod", exclude=3)["version"] == 2
    assert fresh_store.get_version(first)["values"] == {"vad.min_silence_ms": 700}


def test_an_unknown_state_is_refused(fresh_store):
    with pytest.raises(ValueError):
        fresh_store.create_version("prod", {}, status="almost_live")


def test_a_version_keeps_the_exact_text_it_served(fresh_store):
    version = fresh_store.create_version("prod", {}, rendered="schema_version: 1\n", status="live")
    assert fresh_store.get_version(version)["rendered"] == "schema_version: 1\n"


def test_audit_details_round_trip_as_a_mapping(fresh_store):
    audit_id = fresh_store.record_audit(
        "publish.live", profile="prod", version=1, result="ok", detail={"applied": ["vad.thresh"]}
    )
    entry = fresh_store.list_audit("prod")[0]
    assert entry["id"] == audit_id
    assert entry["detail"] == {"applied": ["vad.thresh"]}


# ── secrets never leave the platform (spec §11.2) ───────────────────────────


def test_secret_values_are_masked_on_the_way_out():
    import param_api

    masked = param_api._mask(
        {
            "llm.responses_api_api_key": "sk-live-123",
            "runtime.server.auth_token": "t-123",
            "vad.min_silence_ms": 700,
        }
    )
    assert masked == {
        "llm.responses_api_api_key": "***",
        "runtime.server.auth_token": "***",
        "vad.min_silence_ms": 700,
    }


# ── publish, health check and automatic revert (spec §11.2, §4.1 steps 5-8) ──


def _healthy(size: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        ok=True,
        reason=f"pool of {size}",
        pool=SimpleNamespace(size=size, in_use=0),
        attempts=1,
        notes=[],
    )


def _unhealthy(reason: str = "the pool never reached 1") -> SimpleNamespace:
    return SimpleNamespace(ok=False, reason=reason, pool=None, attempts=3, notes=[reason])


def _compose(failed: bool) -> SimpleNamespace:
    return SimpleNamespace(ok=not failed, returncode=1 if failed else 0, stdout="", stderr="boom")


@pytest.fixture
def deploy_env(tmp_path, monkeypatch):
    """A real profile on a temp config dir, with docker and the pool probe replaced.

    Everything the publish flow does to *files* — the write, the `.bak.<version>`
    backup and the restore — runs for real, so the assertions about what is on
    disk afterwards mean something. Only the two things a test box cannot do
    (`compose up` and `GET /v1/pool`) are fakes; each test supplies its own.
    """
    config = tmp_path / "config"
    config.mkdir()
    original = (REPO / "config" / "prod.yaml").read_text(encoding="utf-8")
    path = config / "prod.yaml"
    path.write_text(original, encoding="utf-8")

    monkeypatch.setenv("PARAM_CONFIG_DIR", str(config))
    # prod.yaml points its key at `{env: GPUSTACK_API_KEY}`, which fails to
    # resolve when the variable is missing — that is a validator error, not the
    # subject of these tests.
    monkeypatch.setenv("GPUSTACK_API_KEY", "sk-test")
    monkeypatch.delenv("PARAM_VRAM_GB", raising=False)
    monkeypatch.setattr(store, "_db_path", tmp_path / "params.sqlite3")
    store.init()

    monkeypatch.setattr(compose_runner, "available", lambda: (True, "docker compose v2"))
    monkeypatch.setattr(
        compose_runner,
        "read_pool",
        lambda timeout=5.0: SimpleNamespace(reachable=True, size=1, in_use=0),
    )
    monkeypatch.setattr(compose_runner, "logs", lambda tail=200: "container log tail")
    return SimpleNamespace(path=path, original=original)


def test_a_container_that_will_not_start_is_reverted(deploy_env, monkeypatch):
    """Step 7 fails, step 8 puts back the file that was running."""
    store.put_draft("prod", {"vad.min_silence_ms": 900}, 0, "zhangsan")
    attempts = []

    def recreate():
        attempts.append(1)
        # The publish fails; the revert's own `compose up` is a fresh container
        # on the restored file, which is the case being asserted.
        return _compose(failed=len(attempts) == 1)

    monkeypatch.setattr(compose_runner, "recreate", recreate)
    monkeypatch.setattr(
        compose_runner, "wait_healthy", lambda expected, *, timeout=None: _healthy()
    )

    with pytest.raises(publish_flow.FlowError) as raised:
        publish_flow.publish("prod", actor="zhangsan")

    assert raised.value.code == "compose_failed"
    assert raised.value.status == 502
    assert deploy_env.path.read_text(encoding="utf-8") == deploy_env.original
    assert store.list_versions("prod")[0]["status"] == "rolled_back"
    assert [a["action"] for a in store.list_audit("prod")][0] == "publish.rolled_back"


def test_a_container_that_never_becomes_healthy_is_reverted(deploy_env, monkeypatch):
    """A started container is not a working one: the pool has to reach the size."""
    store.put_draft("prod", {"vad.min_silence_ms": 900}, 0, "zhangsan")
    monkeypatch.setattr(compose_runner, "recreate", lambda: _compose(failed=False))
    health = [_unhealthy(), _healthy()]
    monkeypatch.setattr(
        compose_runner, "wait_healthy", lambda expected, *, timeout=None: health.pop(0)
    )

    with pytest.raises(publish_flow.FlowError) as raised:
        publish_flow.publish("prod", actor="zhangsan")

    assert raised.value.code == "healthcheck_timeout"
    assert raised.value.status == 504
    assert deploy_env.path.read_text(encoding="utf-8") == deploy_env.original
    assert store.list_versions("prod")[0]["status"] == "rolled_back"


def test_a_failed_revert_leaves_the_version_for_a_human(deploy_env, monkeypatch):
    """`failed` is the one state that means the container runs something unverified."""
    store.put_draft("prod", {"vad.min_silence_ms": 900}, 0, "zhangsan")
    monkeypatch.setattr(compose_runner, "recreate", lambda: _compose(failed=True))
    monkeypatch.setattr(
        compose_runner, "wait_healthy", lambda expected, *, timeout=None: _unhealthy()
    )

    with pytest.raises(publish_flow.FlowError) as raised:
        publish_flow.publish("prod", actor="zhangsan")

    assert raised.value.code == "rollback_failed"
    assert raised.value.status == 500
    assert store.list_versions("prod")[0]["status"] == "failed"
    # The file is still restored — a human decides about the process, not the text.
    assert deploy_env.path.read_text(encoding="utf-8") == deploy_env.original


def test_a_publish_over_the_vram_budget_never_reaches_the_file(deploy_env, monkeypatch):
    """Step 4 refuses before a version row exists: nothing to roll back."""
    monkeypatch.setenv("PARAM_VRAM_GB", "12")
    store.put_draft("prod", {"runtime.num_pipelines": 5}, 0, "zhangsan")

    with pytest.raises(publish_flow.FlowError) as raised:
        publish_flow.publish("prod", actor="zhangsan")

    assert raised.value.code == "vram_budget_exceeded"
    assert raised.value.status == 422
    assert store.list_versions("prod") == []
    assert deploy_env.path.read_text(encoding="utf-8") == deploy_env.original
