web_server/
├── main.py              ← 入口，Flask 工厂 + 6 个 Blueprint 注册
├── config.py            ← 路径/常量/SQLite
├── db.py                ← MySQL 连接
├── yaml_utils.py        ← YAML 清洗/断言标准化
├── templates.py         ← conftest + 测试代码模板
├── _conftest_template.py← conftest 源码（从原文件提取）
├── routes_generate.py   ← /api/generate, /api/batch
├── routes_execute.py    ← /api/execute
├── routes_ai_assert.py  ← /api/ai_assert
├── routes_db.py         ← /api/db/config, /api/db/records
├── routes_danmaku.py    ← /api/danmaku/* (CRUD + 压测)
└── routes_static.py     ← /, /health, /report/<path>
