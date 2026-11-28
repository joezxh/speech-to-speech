from sqlalchemy import UniqueConstraint

from app.models.front_setting import ParamFrontSetting


def test_table_and_columns():
    table = ParamFrontSetting.__table__
    assert table.name == "param_front_setting"
    assert [c.name for c in table.columns] == [
        "id",
        "config_key",
        "value",
        "value_type",
        "updated_by",
        "updated_at",
    ]


def test_config_key_is_unique():
    constraints = [
        c for c in ParamFrontSetting.__table__.constraints if isinstance(c, UniqueConstraint)
    ]
    assert any(c.name == "uq_param_front_setting_key" for c in constraints)