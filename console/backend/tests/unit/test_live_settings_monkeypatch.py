"""回归：LiveSettings 门面必须与 pytest monkeypatch 兼容（spec 2026-11-17 §4.2）。

门面把属性取值改成 `__getattr__` 动态解析后，`monkeypatch.setattr(门面, "x", v)` 的
撤销路径曾报 `AttributeError: 'LiveSettings' object has no attribute 'x'`，在全量跑中
级联出 232 个 teardown ERROR。本文件钉住：patch→读→撤销全程无异常，且撤销后取值还原。
"""

from __future__ import annotations

import pytest

from app.config import console, demo


@pytest.mark.parametrize(
    ("facade", "attr", "value"),
    [
        (demo, "speech_to_speech_url", "http://repro.test:9999"),
        (console, "static_dir", "/tmp/repro-dist"),
    ],
)
def test_monkeypatch_setattr_on_facade_roundtrips(monkeypatch, facade, attr, value):
    before = getattr(facade, attr)
    monkeypatch.setattr(facade, attr, value)
    assert getattr(facade, attr) == value
    monkeypatch.undo()
    assert getattr(facade, attr) == before


def test_double_patch_then_undo_restores_original(monkeypatch):
    original = demo.speech_to_speech_url
    monkeypatch.setattr(demo, "speech_to_speech_url", "http://one.test")
    monkeypatch.setattr(demo, "speech_to_speech_url", "http://two.test")
    assert demo.speech_to_speech_url == "http://two.test"
    monkeypatch.undo()
    assert demo.speech_to_speech_url == original


def test_delattr_without_override_never_deletes_the_pydantic_field():
    """对门面 delattr 一个"只有动态解析"的属性，底层 pydantic 字段必须安然无恙。

    pytest 对非数据描述符属性从 `target.__dict__` 记账（#10644），门面动态属性会被
    记成 delattr 条目；`__delattr__` 的兜底曾顺着删 pydantic 单例字段（一删永失），
    这就是全量跑 232 个 teardown 错误的放大器。
    """
    before = demo.speech_to_speech_url
    mp = pytest.MonkeyPatch()
    try:
        mp.delattr(demo, "speech_to_speech_url", raising=False)
        assert demo.speech_to_speech_url == before
    finally:
        mp.undo()
    assert demo.speech_to_speech_url == before
    assert hasattr(demo._settings, "speech_to_speech_url")


def test_nested_patch_contexts_do_not_poison_the_pydantic_singleton():
    """嵌套两层 monkeypatch 撤销后，底层 pydantic 实例不得丢字段（全量跑 232 错的根因）。

    pytest 9 为避免 #10644 遮蔽，从 `target.__dict__` 取旧值——门面动态属性记为
    NOTSET，undo 走 `delattr`；内层撤销删掉覆盖层后，外层撤销的 `delattr` 会落进
    `__delattr__` 的兜底。兜底曾去删 pydantic 单例的字段（pydantic v2 字段就在
    `__dict__` 里，一删永失），此后所有测试的 `__getattr__` 全部 AttributeError。
    """
    from app.config import console

    with pytest.MonkeyPatch.context() as outer:
        outer.setattr(console, "static_dir", "/outer-dist")
        assert console.static_dir == "/outer-dist"
        with pytest.MonkeyPatch.context() as inner:
            inner.setattr(console, "static_dir", "/inner-dist")
            assert console.static_dir == "/inner-dist"
        # 内层撤销后仍必须可读（哪怕值回到外层覆盖或 env 默认）。
        assert console.static_dir
    # 外层撤销后：底层字段还在、属性还能解析、还能再来一轮 patch。
    assert hasattr(console._settings, "static_dir")
    assert console.static_dir
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(console, "static_dir", "/again")
        assert console.static_dir == "/again"
    finally:
        monkeypatch.undo()
    assert console.static_dir
