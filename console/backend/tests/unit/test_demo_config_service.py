from __future__ import annotations

import json

from app.config import console
from app.services.demo_config_service import config, ice_servers


def test_ice_servers_accept_a_json_list():
    raw = json.dumps([{"urls": "turn:t.example.com", "username": "u", "credential": "c"}])
    assert ice_servers(raw) == [{"urls": "turn:t.example.com", "username": "u", "credential": "c"}]


def test_ice_servers_accept_a_single_object():
    assert ice_servers('{"urls": "stun:stun.l.google.com:19302"}') == [
        {"urls": "stun:stun.l.google.com:19302"}
    ]


def test_ice_servers_fall_back_to_a_comma_list():
    assert ice_servers("stun:a, stun:b ,") == [{"urls": "stun:a"}, {"urls": "stun:b"}]


def test_ice_servers_are_empty_when_unset():
    # Host candidates only. An empty list is valid and is what local dev uses.
    assert ice_servers("   ") == []


def test_config_names_the_pipeline_this_console_is_wired_to():
    # 语音页要能说清“我在用哪一个 pipeline”，而状态探测 / 热更新 / WS 反代
    # 用的是同一个 PIPELINE_BASE_URL；两者必须同源，不能各写一份地址。
    payload = config()

    assert payload["pipeline"] == {
        "baseUrl": console.pipeline_base_url.strip(),
        "container": console.pipeline_container.strip(),
    }
    assert payload["pipeline"]["baseUrl"].startswith("http")
