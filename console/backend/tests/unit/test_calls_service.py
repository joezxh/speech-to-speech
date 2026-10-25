from __future__ import annotations


def test_grant_connect_url_flips_the_scheme_map():
    from app.services.allocator import grant_connect_url

    assert grant_connect_url("http://192.168.40.31:8765") == "ws://192.168.40.31:8765/v1/realtime"
    assert grant_connect_url("https://pipe.example.com/") == "wss://pipe.example.com/v1/realtime"
    # 与 handshake_url 对称：ws↔http、wss↔https（spec §8.3）
    from app.services.calls_service import handshake_url

    assert handshake_url(grant_connect_url("http://h:1")) == "http://h:1/v1/realtime/calls"
