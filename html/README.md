html/
├── common/                # 公共模块（复用性强的组件/样式）
│   ├── header.html        # 顶部导航栏（logo、标题、子标题）
│   ├── page-tabs.html     # 顶层页签切换（视图切换的tab栏）
│   └── common.css         # 公共样式（重置样式、body、通用交互类）
├── views/                 # 业务视图模块（按功能拆分）
│   ├── records/           # 运行记录视图
│   │   ├── records.html   # 运行记录HTML结构
│   │   └── records.css    # 运行记录专属样式
│   ├── perf/              # 性能测试视图
│   │   ├── perf.html      # 性能测试HTML结构
│   │   └── perf.css       # 性能测试专属样式
│   └── danmaku/           # 弹幕压测视图
│       ├── danmaku.html   # 弹幕压测HTML结构
│       └── danmaku.css    # 弹幕压测专属样式
└── index.html             # 主入口页面（整合所有模块）