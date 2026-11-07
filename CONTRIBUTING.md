# Contributing

## 开发环境

```bash
pip install -e ".[dev]"
pre-commit install          # 可选
```

## 提交前

```bash
ruff check .
python -m pytest
python -m coverage run --branch -m pytest -q && python -m coverage report
mypy gen4399                # 目前为观察项，尽量保持无新增错误
```

## 代码约定

- 零运行时依赖（只用标准库）；新增第三方库只能进 `dev` extra。
- 公共 API 变更要更新 `README.md`、`CHANGELOG.md` 与 `__init__.__all__`。
- 涉及 PII 的输出必须默认打码，禁止写入日志。
- 新增注册路径：在 `forms.py` 加 `RegistrationForm` 并登记到 `FORMS`，补字段与校验测试。
- 规则变化：按 `docs/rules.md` 的流程更新并跑 `scripts/verify_rules.py`。

## 提交信息

建议 Conventional Commits：`feat(...)` / `fix(...)` / `docs(...)` / `test(...)` / `build(...)`。
