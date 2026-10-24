from __future__ import annotations

import json

from app.services.demo_config_service import ice_servers


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
