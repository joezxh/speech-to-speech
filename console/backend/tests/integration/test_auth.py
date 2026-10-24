# `client` comes from tests/integration/conftest.py (seeded `alice`, temp DB).


def test_login_returns_camel_case_tokens(client):
    body = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()
    assert body["code"] == 200
    data = body["data"]
    assert data["tokenType"] == "bearer" and data["expiresIn"] == 1800
    assert data["user"] == {"username": "alice", "role": "admin"}


def test_unknown_user_and_wrong_password_look_identical(client):
    a = client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"})
    b = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json()["code"] == b.json()["code"] == "invalid_credentials"


def test_me_requires_a_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_role(client):
    token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()["data"][
        "accessToken"
    ]
    body = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["data"]["username"] == "alice" and "lastLoginAt" in body["data"]


def test_refresh_token_is_not_an_access_token(client):
    tokens = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}).json()["data"]
    headers = {"Authorization": f"Bearer {tokens['refreshToken']}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_sixth_failure_is_429(client):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"})
    sixth = client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"})
    assert sixth.status_code == 429
    assert sixth.json()["code"] == "too_many_attempts"
