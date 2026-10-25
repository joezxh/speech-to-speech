from app.config import AllocatorSettings, allocator


def test_defaults_keep_everything_off():
    # spec §12: 全部带默认值，且默认不改行为
    assert allocator.mode == "off"
    assert allocator.queue_enabled is False
    assert allocator.webrtc_hangup_enabled is False
    assert allocator.probe_interval_s == 5
    assert allocator.probe_timeout_s == 2
    assert allocator.fail_threshold == 3
    assert allocator.recover_threshold == 2
    assert allocator.grant_ttl_s == 60
    assert allocator.usage_interval_s == 30
    assert allocator.metric_retention_days == 7
    assert allocator.seed_path == ""


def test_console_id_falls_back_to_the_hostname():
    import socket

    # 字段本身默认空（不在类定义里读 hostname，免得导入时机影响取值），
    # 消费方一律走 resolved_console_id（spec §12：CONSOLE_ID 默认主机名）。
    assert allocator.console_id == ""
    assert allocator.resolved_console_id == socket.gethostname()


def test_env_names_match_the_spec(monkeypatch):
    # spec §12 定死了每个变量的 env 名（前缀不统一），alias 写错字就是静默失效，
    # 所以逐条断言一次真实读取。
    env = {
        "ALLOCATOR_MODE": "local",
        "CONSOLE_ID": "console-2",
        "INSTANCES_SEED_PATH": "/app/instances.yaml",
        "INSTANCE_PROBE_INTERVAL_S": "3",
        "INSTANCE_PROBE_TIMEOUT_S": "4",
        "INSTANCE_FAIL_THRESHOLD": "5",
        "INSTANCE_RECOVER_THRESHOLD": "6",
        "INSTANCE_GRANT_TTL_S": "90",
        "INSTANCE_USAGE_INTERVAL_S": "15",
        "INSTANCE_METRIC_RETENTION_DAYS": "14",
        "INSTANCE_QUEUE_ENABLED": "true",
        "INSTANCE_WEBRTC_HANGUP_ENABLED": "true",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = AllocatorSettings(_env_file=None)
    assert settings.mode == "local"
    assert settings.console_id == "console-2"
    assert settings.resolved_console_id == "console-2"
    assert settings.seed_path == "/app/instances.yaml"
    assert settings.probe_interval_s == 3
    assert settings.probe_timeout_s == 4
    assert settings.fail_threshold == 5
    assert settings.recover_threshold == 6
    assert settings.grant_ttl_s == 90
    assert settings.usage_interval_s == 15
    assert settings.metric_retention_days == 14
    assert settings.queue_enabled is True
    assert settings.webrtc_hangup_enabled is True
