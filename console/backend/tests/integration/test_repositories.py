from app.repositories.draft_repository import DraftRepository
from app.repositories.version_repository import VersionRepository


def test_draft_round_trip(db_session):
    repo = DraftRepository(db_session)
    assert repo.get("prod") is None
    repo.put("prod", base_version=3, patch={"vad.min_silence_ms": 900}, actor="alice")
    row = repo.get("prod")
    assert row.patch == {"vad.min_silence_ms": 900} and row.base_version == 3
    assert repo.drop("prod") is True and repo.get("prod") is None


def test_version_numbers_are_append_only(db_session):
    repo = VersionRepository(db_session)
    first = repo.create("prod", status="publishing", yaml_text="a: 1\n", env_sha256="x", note="n", author="alice")
    second = repo.create("prod", status="publishing", yaml_text="a: 2\n", env_sha256="x", note="n", author="alice")
    assert (first.version, second.version) == (1, 2)
    # Rendering the same text twice must hash identically (audit relies on it).
    assert repo.get("prod", 1).yaml_sha256 == repo.get("prod", 1).yaml_sha256
    assert repo.latest_live("prod") is None
    repo.set_status(second, "live")
    assert repo.latest_live("prod").version == 2
