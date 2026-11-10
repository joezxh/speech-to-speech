# Console 服务 — 端到端浏览器自动化测试 Skill

> 本文档为 AI 浏览器测试 Agent 提供完整的 Console(控制台服务)测试提示词。
> 使用 `/browser` 启动浏览器自动化测试,或使用 MCP Playwright 执行测试。
> 适用于 gstack `/qa` 和 `/qa-only` Skill,通过 `/open-gstack-browser` 导入认证 Cookie 后执行端到端测试。
> 文档同时包含问题自动定位与修复建议机制,支持端到端回归测试。
> 测试对象:高保真设计原型 `console/design/console-refactor-demo.html`(纯前端 Mock,覆盖 Console 服务全部页面与交互元素),并附真实控制台(前端 :3000 / 后端 :8000)的对照验证要点。

---

## 目录

- [1.测试前置条件](#测试前置条件)
- [2.全局测试策略](#全局测试策略)
- [3.Skill 调用方式](#skill-调用方式)
- [4.问题发现与自动修复流程](#问题发现与自动修复流程)
- [5.Console 服务测试模块](#console-服务测试模块)
  - [CON-01 全局框架与导航](#con-01-全局框架与导航)
  - [CON-02 集群总览](#con-02-集群总览)
  - [CON-03 流量与路由](#con-03-流量与路由)
  - [CON-04 计算节点管理](#con-04-计算节点管理)
  - [CON-05 部署参数](#con-05-部署参数)
  - [CON-06 音色库](#con-06-音色库)
  - [CON-07 版本发布](#con-07-版本发布)
  - [CON-08 审计日志](#con-08-审计日志)
  - [CON-09 实时对话](#con-09-实时对话)
  - [CON-10 抽屉与全局弹窗](#con-10-抽屉与全局弹窗)
- [6.测试结果报告模板](#测试结果报告模板)
- [7.模块开发对照与补全清单](#模块开发对照与补全清单)
- [8.文档版本](#文档版本)

---

## 1.测试前置条件

### 1.1 环境要求

| 项目 | 值 |
|------|------|
| Demo 页面 | `http://localhost:4173/design/console-refactor-demo.html` |
| Demo 源文件 | `console/design/console-refactor-demo.html` |
| 真实控制台前端 | `http://localhost:3000`(Vite dev,代理 `/api`、`/vendor`、`/v1` 到 :8000) |
| 真实控制台后端 | `http://localhost:8000`(`uvicorn app.main:app`) |
| Pipeline 服务 | `http://127.0.0.1:8765`(loopback,浏览器不直连) |
| 超级管理员账号 | `admin` |
| 超级管理员密码 | `admin123456` |
| Demo 登录 | 无需登录,直接渲染;语言偏好存于 `localStorage`(键 `LS_KEY`) |

Demo 启动方式(任选其一,在仓库根目录执行):

```bash
# 方式 A: 静态服务器(推荐,路径与设计文档互链)
python -m http.server 4173 --directory console

# 方式 B: 直接打开本地文件
start console/design/console-refactor-demo.html
```

路由说明:Demo 使用 hash 路由,页面与 URL 的对应关系:

| 页面 | Hash 路由 | 渲染函数 |
|------|-----------|---------|
| 集群总览 | `#/overview`(默认) | `renderOverview()` |
| 流量与路由 | `#/lb` | `renderLb()` |
| 计算节点 | `#/machines` | `renderMachines()` |
| 部署参数 | `#/deploy` | `renderDeploy()` |
| 音色库 | `#/voices` | `renderVoices()` |
| 版本发布 | `#/release` | `renderRelease()` |
| 审计日志 | `#/audit` | `renderAudit()` |
| 实时对话 | `#/conversation` | `renderConversation()` |

未知 hash 一律回退 `#/overview`(`applyRoute()` 中 `PAGES[p] ? p : 'overview'`)。

### 1.2 服务依赖检查

测试 Demo 页面时仅需静态文件服务;测试真实控制台时需确认以下服务已启动:

1. **Console 后端**(:8000) — FastAPI 控制台服务
2. **Pipeline**(:8765) — `speech-to-speech serve`,提供 `/v1/pool`、`/v1/realtime`
3. **SQLite/PostgreSQL** — 参数平台数据(`DATABASE_URL=sqlite:///./dev.db`)
4. **参数目录** — `docs/parameter-catalog.yaml`(`PARAM_CATALOG_PATH`)

启动前快速自检:

```bash
curl -s http://127.0.0.1:8000/api/config       # "pipeline":{"baseUrl":"http://127.0.0.1:8765",…}
curl -s http://127.0.0.1:8765/v1/pool          # {"size":1,"in_use":0,"units":[…]}
```

### 1.3 浏览器环境要求

- 浏览器:Chromium / Chrome(headless 模式或带 UI 模式均可)
- Cookie 导入:真实控制台测试通过 `/open-gstack-browser` 导入已登录 Cookie,避免重复登录;Demo 页面无需登录
- 如需手动登录(真实控制台):账号 `admin`,密码 `admin123456`
- 视口建议:≥ 1440×900(Demo 左侧栏 + 主内容区为固定两栏布局,窄屏会出现横向滚动 `.tscroll`)
- Demo 页面存在定时器交互(机器注册测试、音色预计算、对话动画),测试需允许 `setTimeout` 动画完成或显式等待 toast/步骤状态

---

## 2.全局测试策略

### 2.1 模块列表:

| 模块 ID | 模块名称 | 测试场景数 | 说明 |
|---------|---------|-----------|------|
| CON-01 | 全局框架与导航 | 7 | 侧边栏/顶栏/面包屑/集群切换/健康状态/中英切换 |
| CON-02 | 集群总览 | 9 | KPI + 集群 CRUD + 拓扑图跳转 + 最近事件 |
| CON-03 | 流量与路由 | 9 | Token 分析 + 时间窗 + 路由规则 + 分布/egress/实例表 |
| CON-04 | 计算节点管理 | 10 | 搜索/自动注册模拟/新增测试入库/服务声明/状态流转/CRUD |
| CON-05 | 部署参数 | 12 | 参数目录对齐表 + 场景顾问 + 草稿/push/rollback + 音色参数 |
| CON-06 | 音色库 | 12 | 列表 CRUD + 导入/试听/克隆 + 5 步创建向导 |
| CON-07 | 版本发布 | 5 | 金丝雀流水线 + 新建发布 + 回滚 + 历史表 |
| CON-08 | 审计日志 | 5 | KPI + 分类过滤 + 导出 + 空态 |
| CON-09 | 实时对话 | 7 | 呼叫状态机 + 会话气泡 + 工具开关 + verbosity |
| CON-10 | 抽屉与全局弹窗 | 6 | 历史/工具/设置抽屉 + Modal/toast 机制 |
| **合计** | **10 个模块** | **82 个场景** | **~5h 测试时间** |

### 2.2 每个测试用例的验证清单

1. **页面加载**:页面是否正常渲染,无白屏、无 JS 错误
2. **数据加载**:表格数据是否成功加载,loading 状态是否正确消失
3. **交互响应**:按钮点击是否有响应,弹窗是否正常弹出
4. **表单验证**:必填字段校验是否生效,错误提示是否显示
5. **数据回填**:编辑时已有数据是否正确回填到表单
6. **操作反馈**:成功/失败是否有 message 提示
7. **状态更新**:操作后列表数据是否自动刷新
8. **权限控制**:`v-has-permi` 指令是否正确控制按钮显隐
9. **控制台检查**:浏览器控制台是否有报错或警告

> 说明:第 8 项针对真实控制台;Demo 原型无权限体系,验证降级为「只读元素不可编辑、按钮显隐条件正确」(如当前集群无「切换」按钮、`ro` 参数组显示平台托管提示、固定参数列为 `—`)。Demo 中「权限控制」类检查以 **状态驱动显隐**(cur/非cur、draining/bad/ok 状态按钮组、canary/current/rolled.back 操作列)替代。

### 2.3 通用测试模式

每个模块遵循 **CRUD 测试循环**:

```
1. 打开页面 → 验证列表加载
2. 搜索/筛选 → 验证条件过滤
3. 点击「新增」→ 验证弹窗/表单初始化 → 填写并提交 → 验证列表刷新
4. 点击「编辑」→ 验证数据回填 → 修改并提交 → 验证更新生效
5. 点击「删除」→ 验证确认弹窗 → 确认删除 → 验证列表更新
6. 边界测试 → 空数据、超长文本、特殊字符、并发操作
```

Demo 的 Mock 特性补充:

```
- 校验类失败 → 断言 .ferr 错误条文本(DOM 文案含「必填/重复/格式」等关键信息),弹窗不关闭
- 成功类操作 → 断言 #toast 文案出现并在 ~2.4s 后自动消失
- 状态类操作 → 断言表格行、状态标签(statusTag)、健康点(dot)联动刷新
- 跨页跳转 → 断言 location.hash 变化 + 面包屑 #crumb 更新 + 目标页 active
```

---

## 3.Skill 调用方式

### 3.1 方式一:使用 gstack /qa Skill(推荐)

```bash
/qa --tier standard --url http://localhost:4173/design/console-refactor-demo.html
```

### 3.2 方式二:使用 gstack /open-gstack-browser

```
/open-gstack-browser
启动 GStack 浏览器后,执行以下测试流程...

# 或导入 Cookie 跳过登录(真实控制台)
/setup-browser-cookies
选择已登录的 console 会话
执行测试...
```

### 3.3 方式三:直接使用 MCP Playwright

```bash
# 启动浏览器
$B goto http://localhost:4173/design/console-refactor-demo.html#/overview
$B screenshot "overview.png"

# Demo 无需登录;真实控制台登录
$B fill "#username" "admin"
$B fill "#password" "admin123456"
$B click "button[type=submit]"

# 验证跳转
$B wait-for-url "**/#/overview"
$B screenshot "after-load.png"

# 继续测试各模块...
```

### 3.4 方式四:使用 /qa-only(仅发现问题不修复)

```
/qa-only --tier exhaustive --scope "Console服务-部署参数"
```

---

## 4.问题发现与自动修复流程

### 4.1 三阶段闭环

```
阶段 1:问题发现(Detect)
  → 浏览器测试发现异常
  → 截图记录当前状态
  → 记录控制台错误日志
  → 标记失败测试用例

阶段 2:问题定位(Diagnose)
  → 根据错误信息判断问题层级:
    - 前端渲染问题 → 检查 Vue 组件
    - API 请求失败 → 检查 Network 面板(状态码、响应体)
    - 后端逻辑错误 → 检查后端日志
    - 数据问题 → 检查数据库状态
  → 定位到具体文件和行号

阶段 3:自动修复建议(Fix)
  → 输出修复方案(代码 diff)
  → 常见修复模式:
    - 组件未导入 → 补充 import
    - API 路径错误 → 对齐后端路由
    - v-model 绑定问题 → 检查响应式
    - 权限码不匹配 → 对齐前后端权限标识
    - 表单初始值缺失 → 补充默认值
  → 修复后自动重新执行失败的测试用例
```

### 4.2 常见错误自动匹配表

| 浏览器现象 | 可能原因 | 检查文件 |
|-----------|---------|---------|
| 白屏 | 路由组件未注册 / import 路径错误 | `route-helper.ts`, `views/` |
| 表格无数据 | API 返回 code≠0 / 后端未启动 | `request.ts`, Network 面板 |
| 弹窗打不开 | `v-model:open` / `v-model:visible` 绑定问题 | 对应 FormModal.vue |
| 表单不回填 | watch 未监听 / props 延迟 | FormModal.vue 的 watch |
| 按钮不显示 | 权限码不匹配 | `access.ts`, 后端权限配置 |
| 401 错误 | Token 过期 / 刷新 Token 逻辑失败 | `request.ts`, `auth.ts` |
| 删除失败 | 外键约束 / 关联数据未清理 | 后端 Service |
| 分页异常 | pageNo/pageSize 参数不对 | API 请求参数 |
| 树形不展开 | `handleTree` 函数异常 | `menuTreeUtils.ts` |
| 表格列错位 | columns 定义顺序与数据不匹配 | index.vue 的 columns 定义 |
| DictTag 不显示 | 字典类型未注册 / 值为空 | `DictTag.vue`, 后端字典表 |

针对 Demo 原型(`console-refactor-demo.html`)的专属匹配表:

| 浏览器现象 | 可能原因 | 检查位置 |
|-----------|---------|---------|
| 页面切换后内容不更新 | `RENDERERS[state.page]` 未注册 / `applyRoute` 未触发 hashchange | `RENDERERS` 表、`window.addEventListener('hashchange')` |
| 点击无响应 | 事件委托选择器与 `data-*` 属性不匹配 | `document.addEventListener('click')` 内 `el.closest('[data-…]')` |
| 弹窗内容残留 | `closeModal()` 未清理 `#modal-body` / `modalTimers` 未清空 | `openModal()` / `closeModal()` |
| toast 不消失 | `toastTimer` 被重复操作覆盖 | `toast()` 函数(2400ms 自动隐藏) |
| 表单校验不生效 | `ferr` 元素未显示或校验顺序错误 | `saveClusterForm()` / `startMachineTest()` / `vcValidate()` |
| 状态按钮组错误 | `m.state` 三态分支(drain/resume、recover/reboot)判断反了 | `machineRows()` 的 `acts` 三元表达式 |
| 草稿/场景不联动 | `state.draft[machine]` 按机器隔离,切换机器后未重渲染 | `scenePanel()` / `applySceneDraft()` |
| 中英切换后文案半英半中 | i18n 字典 `I18N` 缺 key,`t()` 回退原始 key | 双语字典与 `t()` 函数 |
| 向导步骤跳错 | `vcSkip/vcForward` 对 builtin/design 的跳步规则失效 | 音色向导函数组 |
| SVG 图(拓扑/趋势/波形)空白 | 数据数组为空时 viewBox/坐标 NaN | `topoSVG()` / `tokenTrendSVG()` / `vcWave()` |

---

## 5.Console 服务测试模块

---

### 5.1 CON-01 全局框架与导航

**页面路径**: 所有页面共用的侧边栏 + 顶栏(Hash 路由任意页面)  
**源码文件**: `console/design/console-refactor-demo.html`(`NAV` 常量、`renderNav()`、`renderChrome()`、`applyRoute()`),真实控制台 `console/frontend/src/layouts/ConsoleLayout.vue`  
**API 文件**: 无(Demo);真实控制台 `console/frontend/src/api/*`(登录态 `/api/*`)  
**权限标识**: 无(Demo);真实控制台以登录 JWT 为准

#### 5.1.1 测试场景

1. 侧边栏三组导航(调度/会话/运维)共 11 个入口渲染完整,当前页高亮
2. 页面入口点击后 hash 路由跳转且内容区重渲染
3. 抽屉入口(history/tools/settings)点击打开对应抽屉
4. 面包屑随页面切换更新为「组名 › 页面名」
5. 顶栏集群下拉切换联动全局数据与 toast
6. 健康状态点按「坏机/排水机数量」在 ok/warn 间切换
7. 中英文切换按钮全量重刷文案且 localStorage 持久化

#### 5.1.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开 Console 重构原型页面,执行全局框架与导航的完整测试。

【前置操作】
1. 打开 http://localhost:4173/design/console-refactor-demo.html
2. 等待页面加载完成(默认进入 #/overview)

---

【测试场景 1:侧边栏导航渲染】
1. 验证左侧栏品牌区显示「S2S」mark、品牌名与副标题
2. 验证导航分为三组:「调度 / 会话 / 运维」(中英切换后核对分组标题 i18n)
3. 验证调度组含 2 个页面入口:集群总览、流量与路由
4. 验证会话组含 4 个入口:实时对话、历史记录、工具、设置
5. 验证运维组含 5 个页面入口:计算节点、部署参数、音色库、版本发布、审计日志
6. 验证当前页导航项带 active 类高亮
7. 验证侧边栏底部 foot 文案渲染

预期结果:
✅ 11 个导航入口全部渲染且图标正常
✅ 当前页高亮正确
✅ 分组标题正确

---

【测试场景 2:页面路由跳转】
1. 依次点击「流量与路由」「计算节点」「部署参数」「音色库」「版本发布」「审计日志」「实时对话」
2. 每次验证 location.hash 变为对应 #/<page>
3. 验证内容区 #page-host 重渲染,滚动位置回到顶部
4. 直接在地址栏输入未知路由 #/nonexistent,验证回退渲染集群总览
5. 验证导航 active 类与面包屑同步更新

预期结果:
✅ 7 个页面路由全部可达
✅ 未知路由回退 overview 不白屏
✅ 高亮/面包屑联动

---

【测试场景 3:抽屉入口】
1. 点击导航「历史记录」,验证右侧抽屉 #drawer-history 滑出且遮罩 #overlay 出现
2. 点击遮罩,验证抽屉关闭
3. 点击导航「工具」,验证 #drawer-tools 打开
4. 点击导航「设置」,验证 #drawer-settings 打开
5. 用抽屉内 ✕ 按钮(data-close)关闭,验证 state.overlay 归位

预期结果:
✅ 3 个抽屉均可打开与关闭
✅ 遮罩点击可关闭抽屉

---

【测试场景 4:面包屑】
1. 在「计算节点」页验证 #crumb 显示「运维 › 计算节点」
2. 切换中英文,验证面包屑文案同步翻译
3. 直接改 hash 到 #/deploy,验证面包屑显示「运维 › 部署参数」

预期结果:
✅ 面包屑 = 组名 › 页面名
✅ 双语一致

---

【测试场景 5:顶栏集群切换】
1. 验证 #cluster-select 下拉列出全部集群选项,当前选中集群被 selected
2. 切换到另一集群
3. 验证出现「已切换集群」toast
4. 验证顶栏版本 pill 恒显示 v1.4.2,头像显示 OP
5. 到「计算节点」页验证机器列表已切换为新集群的机器
6. 切回原集群,验证机器恢复

预期结果:
✅ 集群切换联动所有页面数据
✅ 当前集群行有「当前」标签(总览页)

---

【测试场景 6:健康状态联动】
1. 默认集群存在坏机/排水机时,验证 #health-dot 为 warn、#health-text 显示「降级」文案
2. 到计算节点页把 draining 机器 resume、bad 机器 recover(或切换到无异常机器的集群)
3. 验证 #health-dot 变 ok、文案变「健康」
4. 再对一台正常机器执行 drain,验证回到 warn

预期结果:
✅ 健康点 = 集群内 bad/draining 数量驱动
✅ 状态变化即时刷新

---

【测试场景 7:中英文切换与持久化】
1. 点击顶栏 #lang-btn(显示「中文」),验证全站文案切换为中文
2. 刷新页面,验证仍为中文(localStorage 持久化)
3. 再次点击(显示「English」),验证切回英文
4. 打开设置抽屉,用 #set-lang 下拉选择语言,验证与顶栏按钮等效
5. 切换语言时任开一个抽屉,验证抽屉被关闭且不报错

预期结果:
✅ 双语切换覆盖导航/标题/表格/按钮/toast
✅ document.documentElement.lang 同步
✅ 刷新后语言保持

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 页面导航项 | #nav [data-page] | 修改 location.hash |
| 抽屉导航项 | #nav [data-overlay] | openOverlay(history/tools/settings) |
| 集群下拉 | #cluster-select | switchCluster() + toast |
| 健康点 | #health-dot/#health-text | 由集群机器状态计算 |
| 语言按钮 | #lang-btn | setLang 互切 + toast |
| 面包屑 | #crumb | renderChrome() |

---

【问题诊断】
- 点击导航无反应 → 检查 click 委托是否命中 [data-page]
- 刷新后语言丢失 → 检查 LS_KEY 写入与启动读取顺序
- 切集群后部署参数页报空 → 检查 state.machine 是否回落到新集群首台机器
- 未知 hash 白屏 → 检查 PAGES 守卫回退逻辑
```

#### 5.1.3 开发提示词

```
请基于以下信息,在 speech-to-speech 仓库的 console/frontend 中实现【全局框架】模块。

【模块信息】
- 服务: Console(:8000 后端 + Vue3 SPA 前端)
- 页面路径: 应用外壳,包裹所有视图
- 路由: createRouter history,路径与 1.1 节 Hash 对照表一致
- 权限前缀: 登录态(JWT)
- 涉及权限码:
  - console:instance:query(实例/集群监控可见)
  - console:param:update(部署参数写权限,控制按钮显隐)
  - console:release:publish(发布/回滚入口显隐)

【前端文件清单】
- 主布局: console/frontend/src/layouts/ConsoleLayout.vue
- API 封装: console/frontend/src/api/config.ts(集群/pipeline 元信息)

【后端文件清单】
- Controller: console/backend/app/api/(对应 /api/config、/api/v1/status)
- Service: console/backend/app/services/

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 平台配置 | GET | /api/config |
| 服务状态 | GET | /api/v1/status(需 JWT) |

【功能需求】
1. 侧边栏三分组导航(调度/会话/运维),当前路由高亮,未知路由回退总览
2. 顶栏:面包屑、集群下拉、健康徽标(任一实例 unhealthy → warn)、版本 pill、语言切换、头像
3. 语言切换持久化 localStorage,全站 i18n(中英)
4. 抽屉(历史/工具/设置)以 overlay + 右侧滑出实现,遮罩点击可关

【UI 规范】
- UI 库: 与现有 console/frontend 保持一致(Vue3 + 既有组件)
- 视觉基准: console/design/console-refactor-demo.html 的暗色主题与布局
- 操作按钮: 导航项、下拉、按钮均提供可访问名称

【参考实现】
- 原型: console/design/console-refactor-demo.html 的 NAV/renderChrome/applyRoute
- 现有页面: console/frontend/src/views/*(已实现路由的页面直接复用)

【测试验证】
实现完成后,使用 5.1.2 测试提示词中的测试场景验证,重点验证:
1. 11 个导航入口齐全且路由正确
2. 面包屑与高亮联动
3. 集群切换联动数据
4. 健康徽标三态
5. 双语切换与持久化

【交付物清单】
- [ ] ConsoleLayout.vue(侧边栏 + 顶栏 + 抽屉容器)
- [ ] 路由注册与回退守卫
- [ ] i18n 字典(中/英)与 localStorage 持久化
- [ ] 集群下拉与状态 store
- [ ] 健康徽标计算逻辑
- [ ] 通过 5.1.2 所有测试场景
```

---

### 5.2 CON-02 集群总览

**页面路径**: 左侧菜单「调度」→「集群总览」(`#/overview`)  
**源码文件**: `console/design/console-refactor-demo.html`(`renderOverview()`、`clusterRows()`、`topoSVG()`、集群 CRUD 弹窗 `openClusterForm()/saveClusterForm()/deleteCluster()/switchCluster()`),真实控制台 `console/frontend/src/views/InstancesView.vue`  
**API 文件**: 无(Demo);真实控制台 `console/frontend/src/api/*`(实例监控)  
**权限标识**: 无(Demo);真实控制台建议 `console:cluster:*`

#### 5.2.1 测试场景

1. 四个 KPI 卡(机器在线/实例数/活跃会话/错误率)随集群联动
2. 集群表格列完整且当前集群显示「当前」标签
3. 新增集群:表单字段、名称正则、重复名/重复 registry 校验
4. registry 必填与格式校验(scheme://host:port)
5. 编辑集群:名称禁用、registry/policy/note 回填与保存
6. 删除集群:当前/最后集群保护、含机器阻塞、confirm 确认
7. 切换集群按钮与顶栏下拉等效
8. 拓扑图渲染(集群→LB→机器→pipeline 实例)且点击机器跳部署参数页
9. 图例卡与最近事件表(最新 4 条审计)渲染

#### 5.2.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开集群总览页,执行 KPI、集群 CRUD 与拓扑图的完整测试。

【前置操作】
1. 打开页面并进入 #/overview
2. 等待页面加载完成

---

【测试场景 1:KPI 卡片】
1. 验证 4 个 KPI:机器(在线/总数)、实例(含活跃会话子文案)、活跃会话(含路由命中率子文案)、错误率(含 top err)
2. 切换到机器数为 0 的空集群(若无则先切到另一个集群)
3. 验证机器 KPI 显示 0 / 0 且无 NaN
4. 错误率 KPI 使用警告色

预期结果:
✅ 4 卡数值与当前集群数据一致
✅ 空集群不报错

---

【测试场景 2:集群表格】
1. 验证表头:集群 / registry / 策略 / 机器 / 实例 / 状态 / 操作
2. 验证当前集群行带「当前」标签,且不渲染「切换」按钮
3. 验证非当前集群行有「切换 / 编辑 / 删除」3 个按钮
4. 验证策略列显示 i18n 文案(最少会话/轮询/最低延迟)
5. 验证集群有 note 时行下出现说明小字

预期结果:
✅ 表格列齐全
✅ 当前集群无切换按钮

---

【测试场景 3:新增集群】
1. 点击卡片头「新增集群」按钮
2. 验证 Modal 标题为「新增集群」,字段:名称(可编辑)、registry、策略下拉(least/rr/lat)、备注
3. 直接点「保存」→ 验证 .ferr 报「必填 · 名称」,弹窗不关闭
4. 名称输入非法格式 `Bad_Name!` → 验证报名称格式错误
5. 名称输入已存在集群 id → 验证报「重复」
6. 名称输入 `test-cluster-1`,registry 留空保存 → 验证报 registry 必填
7. registry 输入非法 `consul://host`(无端口) → 验证报 registry 格式错误
8. registry 输入其他集群已用值 → 验证报 registry 重复
9. 合法填写(registry 如 consul://10.99.0.1:8500,策略=轮询)保存
10. 验证 toast「集群已新增」、弹窗关闭、下拉包含新集群且视图自动切入新集群(集群表出现空集群行,状态 ok)

预期结果:
✅ 校验顺序与错误文案正确
✅ 新集群自动切换便于加机器

---

【测试场景 4:编辑集群】
1. 点击某集群「编辑」
2. 验证名称输入框 disabled 且回填、registry/policy/note 正确回填
3. 修改策略为「最低延迟」并保存
4. 验证表格策略列更新、toast「集群已更新」
5. 编辑弹窗中把 registry 改成与另一集群重复的值 → 验证报重复且不保存

预期结果:
✅ 编辑回填正确
✅ 名称不可改
✅ 唯一性校验含「排除自身」

---

【测试场景 5:删除集群】
1. 对含机器的集群点「删除」→ 验证 toast 阻塞提示(先移除机器),集群不删除
2. 切换到无机器集群,点「删除」→ 验证浏览器 confirm 出现,取消后集群保留
3. 再次删除并确认 → 集群从表格和下拉消失,toast 提示已删除
4. 删除当前所在集群 → 验证自动回落到第一个集群
5. 只剩最后一个集群时删除 → 验证 toast「至少保留一个集群」类保护

预期结果:
✅ 空集群可删、有机器不可删
✅ confirm 双分支正确

---

【测试场景 6:切换集群】
1. 点击非当前集群「切换」按钮
2. 验证顶栏下拉同步、toast、KPI/机器/实例数据全部联动
3. 重复点击当前集群所在路径(按钮不存在)→ 验证无从重复触发

预期结果:
✅ 与顶栏下拉切换等效
✅ 幂等保护

---

【测试场景 7:拓扑图与跳转】
1. 验证 .topo SVG 渲染:每个集群节点、LB 节点、机器节点、实例方块
2. 验证机器节点带状态色点,坏机呈告警色
3. 点击机器「node-a01」(或列表任意机器)
4. 验证 URL 变 #/deploy、部署参数页顶部选中该机器 chip(active)
5. 返回总览验证图例卡 5 项(在线/告警/排水/故障/流量线)渲染

预期结果:
✅ 拓扑点击跳部署参数并选中机器
✅ 图例齐全

---

【测试场景 8:最近事件】
1. 验证「最近事件」表显示最新 4 条审计(时间/操作者/类别/动作/结果)
2. 到审计页执行一次类别筛选不影响本页
3. 触发一次集群编辑,回总览验证事件表首条更新为该操作

预期结果:
✅ 事件表与 AUDITS 数据一致
✅ 新操作即时出现在首条

---

【测试场景 9:空态与恢复】
1. 删除全部机器与集群直到某集群 0 机器
2. 验证机器列 0 / N、实例列 0、拓扑不崩、无 JS 错误
3. 新增集群 → 加入机器 → 验证总览各行列数值随之更新

预期结果:
✅ 空集群渲染健壮
✅ 数据链路(集群→机器→实例)刷新一致

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 新增集群 | [data-cluster-add] | openClusterForm(null) |
| 编辑集群 | [data-cluster-edit] | openClusterForm(id),名称禁用 |
| 删除集群 | [data-cluster-del] | confirm + 阻塞规则 |
| 切换集群 | [data-cluster-switch] | switchCluster(id) |
| 保存 | [data-csave] | saveClusterForm() 校验链 |
| 关闭弹窗 | [data-modal-close]/#modal-overlay | closeModal() |
| 拓扑机器 | svg [data-machine] | state.machine=id → #/deploy |

---

【问题诊断】
- 保存后列表不刷新 → 检查 renderChrome()+renderPage() 是否都被调用
- 删除后部署参数页报错 → 检查 state.machine 回落逻辑
- registry 校验误报 → 正则 ^([a-z][a-z0-9+.-]*://)?[\w.-]+:\d{2,5}$ 的大小写与端口位数(2~5)
- 拓扑 NaN → 集群无机器时的坐标计算
```

#### 5.2.3 开发提示词

```
请基于以下信息,在 console/frontend 中实现【集群总览】模块。

【模块信息】
- 服务: Console(:8000)
- 页面路径: 左侧菜单「调度」→「集群总览」
- 路由: /overview
- 权限前缀: console:
- 涉及权限码:
  - console:cluster:query(查看集群)
  - console:cluster:create(新增集群)
  - console:cluster:update(编辑集群)
  - console:cluster:delete(删除集群)

【前端文件清单】
- 主页面: console/frontend/src/views/InstancesView.vue(或新建 OverviewView.vue)
- 组件: TopoChart.vue、ClusterFormModal.vue
- API 封装: console/frontend/src/api/clusters.ts

【后端文件清单】
- Controller: console/backend/app/api/clusters.py
- Service: console/backend/app/services/cluster_service.py

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 集群列表 | GET | /api/clusters |
| 集群详情 | GET | /api/clusters/{id} |
| 创建集群 | POST | /api/clusters |
| 更新集群 | PUT | /api/clusters/{id} |
| 删除集群 | DELETE | /api/clusters/{id} |

【功能需求】
1. KPI 四卡:在线机器/实例数/活跃会话/错误率,数据来自 /api/v1/status 与池接口
2. 集群表 CRUD:名称不可改;registry 必填且格式 scheme://host:port、全局唯一;删除需先清空机器、至少保留一个集群
3. 拓扑 SVG:集群→LB→机器→实例四层,机器可点击跳部署参数并选中
4. 图例卡与最近事件表(最新 4 条审计)

【UI 规范】
- UI 库: 与 console/frontend 现有组件一致
- 表单字段:名称、registry、策略(least/rr/lat)、备注
- 错误提示:.ferr 内联错误条 + toast
- 操作按钮:新增/编辑/删除/切换

【参考实现】
- 原型: console-refactor-demo.html renderOverview()/openClusterForm() 校验链
- 现有: InstancesView.vue、VersionTable.vue

【测试验证】
实现完成后,使用 5.2.2 测试提示词中的测试场景验证,重点验证:
1. 集群唯一性与 registry 格式校验
2. 删除阻塞规则
3. 拓扑点击跳转与机器选中
4. KPI 随集群联动

【交付物清单】
- [ ] 总览页面 .vue 与拓扑组件
- [ ] ClusterFormModal(含校验)
- [ ] 前端 API 封装 .ts(含 TypeScript 类型)
- [ ] 后端集群 CRUD 接口
- [ ] 路由注册(/overview)
- [ ] 菜单注册(「调度」→「集群总览」)
- [ ] 权限码注册(console:cluster:*)
- [ ] 通过 5.2.2 所有测试场景
```

---

### 5.3 CON-03 流量与路由

**页面路径**: 左侧菜单「调度」→「流量与路由」(`#/lb`)  
**源码文件**: `console/design/console-refactor-demo.html`(`renderLb()`、`tokenSummaryCard()`、`tkWinChips()`、`tokenTrendSVG()`、`tkDistrCard()`、`wlEgressCard()`),真实控制台 `console/frontend/src/views/InstanceTrendsView.vue`、`components/InstanceTrendChart.vue`  
**API 文件**: 无(Demo);真实控制台 `console/frontend/src/api/metrics.ts`  
**权限标识**: 无(Demo,本页全只读);真实控制台 `console:instance:query`

#### 5.3.1 测试场景

1. KPI 四卡(P95 TTFT/活跃会话/路由命中率/错误率)渲染
2. Token 汇总卡:时间窗 chips(5m/1h/24h)切换重算总量/占比/速率/水位
3. prompt/completion 分布条与成本估算随窗口变化
4. 策略卡只读(least-in-use/sticky/health/evict/canary)+ Token 策略(max_tokens/context/quota/水位)
5. 路由规则表(签名固定/金丝雀/默认)三行与窗口列
6. Token 趋势 SVG(网格线/面积/折线/峰值点/now 标注)
7. 按机器 Token 分布表(会话/实例/速率/水位条/占比)与 top 提示
8. 负载 egress 表(pipeline/llm/video/jepa/embed 分类路由)
9. 实例表 11 列(load 条/rpm/ttft/rtf/err/status/token/水位)

#### 5.3.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开流量与路由页,执行 Token 分析与路由展示的完整测试。

【前置操作】
1. 打开页面并进入 #/lb
2. 等待 SVG 与表格渲染完成

---

【测试场景 1:KPI 卡片】
1. 验证 4 个 KPI:P95 首包 TTFT(警告色 s2s-a1-3)、活跃会话(含实例数子文案)、路由命中率(粘性 30s)、错误率(含 top err)
2. 验证数值与当前集群一致

预期结果:
✅ 4 卡齐全,TTFT/错误率用警告色

---

【测试场景 2:Token 时间窗切换】
1. 验证默认选中「1 小时」chip(active)
2. 依次点击「5 分钟」「24 小时」chip(data-tkwin=5m/24h)
3. 每次验证:Token 汇总 KPI 标题随窗口变化、总量/prompt/completion 数值重算
4. 验证窗口子文案(点数 n)随之更新(5→60→1440)
5. 验证当前 chip 高亮态正确迁移

预期结果:
✅ 三窗口切换重算正确
✅ 只有一个 chip active

---

【测试场景 3:分布与成本】
1. 验证 prompt/completion 占比条(.split .p/.c 宽度和=100%)
2. 验证两行百分比文案(prompt% + completion% + 成本 ≈ $)
3. 切换窗口后验证成本估算随总量变化
4. 验证速率 KPI 下方水位%(quota)显示,水位 ≥85% 转警告色

预期结果:
✅ 占比条与文案一致
✅ 成本随窗口联动

---

【测试场景 4:策略卡与 Token 策略】
1. 验证策略卡只读项:路由策略、粘性 TTL、健康间隔、驱逐、金丝雀
2. 验证 Token 策略区:max_tokens/context/quota/水位,每项带生效徽章(启动即生效/即时)
3. 验证 quota 行显示每分钟额度与当前占比
4. 尝试点击策略卡任意项,验证无编辑控件、无跳转(只读)

预期结果:
✅ 策略区无输入控件
✅ 生效徽章文案正确

---

【测试场景 5:路由规则表】
1. 验证 3 行:签名会话、金丝雀、默认,每行目的标签
2. 验证「窗口」列 Token 数按规则占比分配(签名/金丝雀/默认)
3. 切换时间窗后验证窗口列数值同步重算

预期结果:
✅ 3 条规则齐全
✅ 规则 Token 随窗口变化

---

【测试场景 6:Token 趋势图】
1. 验证 .trend SVG 存在 4 条网格线与 y 轴刻度
2. 验证折线 polyline、面积 path、峰值标注、当前点 now 标注
3. 验证 svg data-points 与 data-last 属性有值
4. 切到 5 分钟窗口,验证趋势点数与提示文案(每点代表 3 分钟)一致

预期结果:
✅ 趋势图渲染无 NaN
✅ 峰值与当前点标注正确

---

【测试场景 7:按机器 Token 分布】
1. 验证表头:机器/会话/实例/速率/水位/占比
2. 验证按速率降序排列,首行机器有 top 提示文案
3. 验证水位条 ≥85% 转警告色
4. 集群无机器时验证空态行「machine.empty」

预期结果:
✅ 排序与 top 提示正确
✅ 水位条告警阈值生效

---

【测试场景 8:负载 egress 表】
1. 验证按工作负载分类行(pipeline/llm/video/jepa/embed)
2. 验证 engine/hosts/load/token/vram/route 列;非 Token 类显示「不适用」
3. 验证 pipeline 行 token 显示集群总量,route 列为「LB 路由」;其余为「直连」标签
4. 切换集群后验证 hosts 与列数随之变化

预期结果:
✅ 各工作负载行渲染
✅ 路由类型标签(pipeline=LB,其余=直连)正确

---

【测试场景 9:实例表】
1. 验证 11 列:实例/节点/负载(条)/rpm/ttft/rtf/err/status/token 速率/水位
2. 验证负载条宽度=inUse/size,ttft/rtf 缺失显示「—」
3. 验证有 err 的实例用警告标签,status 用 statusTag
4. 空集群验证 colspan 空态

预期结果:
✅ 列齐全、缺失值降级显示
✅ 错误/状态标签正确

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 时间窗 chip | [data-tkwin=5m/1h/24h] | state.tkWin 切换 → renderPage() |
| 趋势图 | svg.trend[data-points/data-last] | 只读渲染 |
| 分布水位条 | .bar > i(width%) | 只读,阈值变色 |
| egress 路由标签 | .badge | 只读 |

> 本模块无写操作、无 API 调用(真实控制台对应只读监控接口),重点验证「窗口切换 → 全量指标重算」的联动一致性。

---

【问题诊断】
- 切窗口数值不变 → 检查 tkWindowTotal/tkPrompt 是否读 state.tkWin
- 占比条溢出/负宽 → 检查总量为 0 时的除零保护
- 趋势图空白 → TK_TREND 拼接当前点后坐标计算
- 分布排序错 → 比较函数速率与 id 次序
```

#### 5.3.3 开发提示词

```
请基于以下信息,在 console/frontend 中实现【流量与路由】模块。

【模块信息】
- 服务: Console(:8000)
- 页面路径: 左侧菜单「调度」→「流量与路由」
- 路由: /lb
- 权限前缀: console:
- 涉及权限码:
  - console:instance:query(监控只读)

【前端文件清单】
- 主页面: console/frontend/src/views/InstanceTrendsView.vue
- 组件: InstanceTrendChart.vue、TokenSummaryCard.vue
- API 封装: console/frontend/src/api/metrics.ts

【后端文件清单】
- Controller: console/backend/app/api/metrics.py
- Service: console/backend/app/services/metrics_service.py

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 集群指标 | GET | /api/v1/metrics/cluster?window=1h |
| 实例池 | GET | /api/v1/pool |
| Token 趋势 | GET | /api/v1/metrics/tokens?window=1h |

【功能需求】
1. KPI 四卡 + Token 汇总卡(时间窗 5m/1h/24h 切换重算)
2. prompt/completion 分布条、成本估算、水位告警(≥85%)
3. 只读策略卡(路由/粘性/健康/驱逐/金丝雀 + Token 策略含生效徽章)
4. 路由规则表、Token 趋势图、按机器分布表、负载 egress 表、实例表(11 列)

【UI 规范】
- UI 库: 与 console/frontend 现有组件一致(图表可复用 InstanceTrendChart)
- 只读展示:无输入控件,提供 loading/empty 态
- 告警色:warning 用于 TTFT/错误率/高水位

【参考实现】
- 原型: console-refactor-demo.html renderLb()/tokenSummaryCard()/tkDistrCard()/wlEgressCard()
- 现有: InstanceTrendsView.vue、InstanceCard.vue

【测试验证】
实现完成后,使用 5.3.2 测试提示词中的测试场景验证,重点验证:
1. 时间窗切换全指标联动重算
2. 占比条与水位阈值
3. egress 路由类型标签
4. 实例表缺失值降级

【交付物清单】
- [ ] 流量与路由页面 .vue
- [ ] Token 汇总/趋势/分布/egress 子组件
- [ ] 前端 API 封装 .ts(含类型)
- [ ] 后端指标聚合接口
- [ ] 路由注册(/lb)与菜单注册
- [ ] 权限码注册(console:instance:query)
- [ ] 通过 5.3.2 所有测试场景
```

---

### 5.4 CON-04 计算节点管理

**页面路径**: 左侧菜单「运维」→「计算节点」(`#/machines`)  
**源码文件**: `console/design/console-refactor-demo.html`(`renderMachines()`、`machineRows()`、`machineSvcRow()`、机器 CRUD `openMachineForm()/startMachineTest()/runMachineTest()/addMachineManual()/openMachineEdit()/saveMachineEdit()/deleteMachine()/simulateAutoRegister()`),真实控制台 `console/backend` Agent 注册相关接口  
**API 文件**: 无(Demo);真实控制台健康探测/重启接口  
**权限标识**: 无(Demo);真实控制台 `console:machine:*`

#### 5.4.1 测试场景

1. 机器表 12 列渲染与状态标签/注册方式标签
2. 搜索框实时过滤(id/地址)与无结果空态
3. 模拟自动注册(延迟后新入 auto 机器)
4. 新增机器表单校验(id 正则/重复、地址格式/重复)
5. 服务声明子表单(勾选展开、端口冲突、8765 保留、模型必填)
6. Agent 注册测试三步动画(pass 入库 / fail 不入库可返回)
7. 行内展开服务列表 toggle + 健康检查 toast
8. drain/resume/reboot/recover 状态驱动按钮组
9. 编辑机器(地址/角色/服务声明 + 保存校验)
10. 删除机器 confirm + 行点击跳部署参数

#### 5.4.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开计算节点页,执行机器列表、搜索、注册测试入库与状态流转的完整测试。

【前置操作】
1. 打开页面并进入 #/machines
2. 确认当前集群有机器(否则先在总览新增)

---

【测试场景 1:列表加载与列显示】
1. 验证 12 列:机器/地址/角色/GPU/利用率/实例/工作负载/显存/版本/状态/注册/操作
2. 验证每行机器名前带状态色点(dotFor)
3. 验证 manual 注册显示橙色标签、auto 显示蓝色标签
4. 验证操作列按钮组(见场景 8)
5. 验证坏机/排水机存在时顶部出现健康提示 note

预期结果:
✅ 列齐全且状态/注册标签正确

---

【测试场景 2:搜索过滤】
1. 在 #m-search 输入部分机器 id(如 a01),验证表格实时过滤
2. 输入地址片段(如 10.12),验证按地址匹配
3. 输入无匹配关键字,验证行内空态「machine.search.empty」
4. 清空搜索框,验证恢复全量

预期结果:
✅ 搜索实时更新无需回车
✅ 无结果与空集群文案区分

---

【测试场景 3:模拟自动注册】
1. 点击「模拟自动注册」(data-mauto)
2. 验证先弹 toast「等待注册」,约 1.4s 后新机器入库
3. 验证新机器 id 为未占用编号(node-x0n)、reg=auto、默认 pipeline 服务
4. 重复点击多次,验证 id 不重复递增

预期结果:
✅ 自动注册异步完成入列
✅ 机器编号递增不冲突

---

【测试场景 4:新增机器表单校验】
1. 点击「新增机器」(data-madd),验证 Modal 标题与字段(集群提示/id/地址/GPU/角色/服务声明/测试模拟)
2. id 留空点「开始测试」→ 验证报「必填 · 机器」
3. id 输入 `E`(少于 2 字符)→ 验证报格式错误
4. id 输入已存在机器 → 验证报重复
5. 地址留空 → 验证必填;地址 `1.2.3.4`(无端口) → 验证格式错;地址重复 → 验证报重复
6. 每次失败弹窗不关闭且回显已填值

预期结果:
✅ id 正则、地址正则、唯一性校验全部生效

---

【测试场景 5:服务声明校验】
1. 新增/编辑机器表单中勾选一个非 pipeline 工作负载(如 llm),验证 svcgrid 字段展开(engine/model/port/vram)
2. 取消勾选,验证字段隐藏
3. port 输入非 2~5 位数字 → 验证报端口错误
4. model 留空 → 验证报模型必填
5. port 输入 8765(pipeline 保留端口)→ 验证报端口冲突
6. 声明内两个服务 port 相同 → 验证报重复端口

预期结果:
✅ pipeline 默认锁定不可取消
✅ 端口/模型/冲突校验正确

---

【测试场景 6:注册测试与入库】
1. 合法填写后点「开始测试」,验证进入测试面板(3 步步骤条)
2. 默认模拟二通过:验证步骤逐行 running→ok,约 2.5s 后提示入库成功并自动关窗
3. 验证新机器出现在表格且已选中为当前机器
4. 再次新增并将「测试模拟」选为失败:验证第 2 步 fail + 失败提示 + toast,机器不入库,审计新增一条 fail
5. 测试面板点「返回修改」(data-mback),验证回到预填表单

预期结果:
✅ 测试通过才入库
✅ 失败不入库且可返回修正
✅ 失败写入审计(bad)

---

【测试场景 7:行内服务展开与健康检查】
1. 点击某行「服务列表」toggle(data-msvc),验证展开内联机全服务子表(colspan 行)
2. 验证子表列:服务/类型/engine/模型/端口/状态/显存/健康检查/注册/备注
3. 子表内点「检查」(data-svc-hp)→ 验证 toast 健康检查提示
4. 再次 toggle 收起,验证子表消失

预期结果:
✅ 展开/收起切换正确
✅ 健康检查为只读 toast

---

【测试场景 8:状态流转按钮组】
1. 正常(ok)机器行验证有「排水 drain / 重启 reboot」两按钮
2. 点 drain → toast 排水提示,行状态变 draining(验证变为「恢复 resume」单按钮)
3. 点 resume → 变回 ok(drain/reboot 恢复)
4. bad 机器行验证有「重新上线 recover」按钮,点击后状态恢复
5. 点 reboot → toast 重启提示
6. 验证状态变化后顶栏健康点与总览 KPI 同步

预期结果:
✅ 按钮组随状态正确切换(三态分支)
✅ 状态变更联动健康位

---

【测试场景 9:编辑机器】
1. 点行内「编辑」(data-medit),验证回填地址/GPU/角色/注册标签(只读)/已有服务声明
2. 修改地址为非法/重复值保存 → 验证报错不关窗
3. 合法保存 → 验证列表地址更新、toast
4. 修改服务声明(增/删一个服务)保存 → 验证服务变更 toast + 审计 svc 记录

预期结果:
✅ 地址/服务唯一性校验
✅ 服务变更时额外 toast

---

【测试场景 10:删除与跳转】
1. 点行内「删除」(data-mdel),验证 confirm 提示(含实例数 n),取消则保留
2. 确认删除 → 验证机器行消失、其实例/服务一并移除、toast
3. 删除当前选中机器 → 验证 state.machine 回落到首台
4. 点击机器行本体(非按钮区, data-goto-deploy)→ 验证跳 #/deploy 且选中该机器
5. 验证行内按钮区点击不会误触发行跳转

预期结果:
✅ 删除级联清理
✅ 行点击跳部署、按钮不冒泡

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 搜索框 | #m-search | input 事件 → machineRows() 重绘 |
| 自动注册 | [data-mauto] | simulateAutoRegister() 延时入库 |
| 新增机器 | [data-madd] | openMachineForm(null) |
| 开始/重测 | [data-mtest] | startMachineTest() → runMachineTest() |
| 返回修改 | [data-mback] | openMachineForm(pendingAdd) |
| 保存编辑 | [data-msave] | saveMachineEdit(id) |
| 删除机器 | [data-mdel] | confirm + deleteMachine(id) |
| 状态按钮 | [data-act=drain/resume/reboot/recover] | handleAct() toast |
| 服务展开 | [data-msvc] | state.svcOpen 切换 |
| 服务检查 | [data-svc-hp] | toast 健康 mock |
| 行跳转 | [data-goto-deploy] | state.machine=id → #/deploy |
| 服务勾选 | .svc-on[data-svc-kind] | change 展开/隐藏 svcgrid |

---

【问题诊断】
- 测试失败机器仍入库 → 检查 runMachineTest 的 sim==='fail' 分支未调 addMachineManual
- 删除后页码/选中错乱 → 检查 state.machine 回落与 renderPage
- 行展开时按钮触发跳转 → 检查 [data-act] 与 [data-goto-deploy] 冒泡优先级
- 端口冲突未拦 → readSvcForm 中 PIPE_PORT=8765 与 list 去重逻辑
```

#### 5.4.3 开发提示词

```
请基于以下信息,实现【计算节点管理】模块。

【模块信息】
- 服务: Console(:8000)
- 页面路径: 左侧菜单「运维」→「计算节点」
- 路由: /machines
- 权限前缀: console:
- 涉及权限码:
  - console:machine:query(查看)
  - console:machine:create(新增/自动注册)
  - console:machine:update(编辑/状态流转)
  - console:machine:delete(删除)

【前端文件清单】
- 主页面: console/frontend/src/views/MachinesView.vue
- 组件: MachineFormModal.vue、ServiceDeclareForm.vue、MachineTestPanel.vue
- API 封装: console/frontend/src/api/machines.ts

【后端文件清单】
- Controller: console/backend/app/api/machines.py
- Service: console/backend/app/services/machine_service.py

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 机器列表 | GET | /api/machines |
| 注册测试 | POST | /api/machines/{id}/test |
| 新增机器 | POST | /api/machines |
| 更新机器 | PUT | /api/machines/{id} |
| 删除机器 | DELETE | /api/machines/{id} |
| 状态流转 | PUT | /api/machines/{id}/state |

【功能需求】
1. 机器列表支持实时搜索(id/地址)、分页、健康提示
2. 新增需通过 Agent 注册测试三步(连接→注册→健康),测试通过才入库
3. 服务声明可勾选多类工作负载,端口/模型/冲突校验,pipeline 默认锁定
4. 支持 drain/resume/reboot/recover 状态流转与行内服务展开
5. 删除级联清理关联实例/服务,当前选中机器自动回落

【UI 规范】
- UI 库: 与 console/frontend 现有组件一致
- 表单字段:机器 id、地址、GPU、角色(agent/gateway/canary)、服务声明
- 校验提示:.ferr 内联错误条;成功/失败均 toast

【参考实现】
- 原型: console-refactor-demo.html renderMachines()/startMachineTest()/runMachineTest()
- 现有: ModelRuntimeCard.vue、RuntimeGrid.vue

【测试验证】
实现完成后,使用 5.4.2 测试提示词中的测试场景验证,重点验证:
1. 注册测试失败不入库
2. 端口/地址/id 唯一性校验
3. 状态按钮三态分支正确
4. 行跳转与删除级联

【交付物清单】
- [ ] 机器列表页 .vue 与表单/测试面板组件
- [ ] 前端 API 封装 .ts(含类型)
- [ ] 后端机器 CRUD + 注册测试接口
- [ ] 路由/菜单/权限码注册
- [ ] 审计日志接入(machine 分类)
- [ ] 通过 5.4.2 所有测试场景
```

---

### 5.5 CON-05 部署参数

**页面路径**: 左侧菜单「运维」→「部署参数」(`#/deploy`,或由拓扑/机器行点击带入选中机器)  
**源码文件**: `console/design/console-refactor-demo.html`(`renderDeploy()`、`scenePanel()`、`groupCard()`、`paramRow()`、`applySceneDraft()`、`recCard()`、`sceneDiff()`、`backendBar()/backendFold()`),真实控制台 `console/frontend/src/views/ParamsView.vue`、`components/ParamTree.vue`、`components/ParamField.vue`、`components/DiffTable.vue`、`components/PublishDialog.vue`  
**API 文件**: 无(Demo);真实控制台参数平台写接口(见 `docs/console-service.md` 链路 A/B)  
**权限标识**: 无(Demo);真实控制台 `console:param:update`(写)、ops 级参数另需管理员确认

#### 5.5.1 测试场景

1. 机器 chips 选择与 active 态、空集群提示
2. KPI 四卡(参数总数/漂移数/ops 参数/热参数)+ 漂移与离线 note
3. 部署栈信息卡字段与版本标签颜色、配置 push / rollback 按钮 toast
4. 参数按组统计表与生效方式图例
5. 场景顾问 chips 切换与推荐卡内容(理由/收益/代价/风险/ref)
6. 场景 diff 视图展开与「已是目标值」空 diff 态
7. 场景应用到草稿(apply)、草稿条计数、clear draft、离线机器禁改
8. 参数组 group chips 过滤(ALL/vad/stt/llm/tts/platform)与计数
9. 分组卡片 backend 当前/可选条、platform 组只读提示
10. ops 高危参数 toggle 显示/隐藏
11. 参数实际值编辑(输入/下拉)触发 mock 提示并还原、漂移行徽章与 push/rollback 单行
12. 音色类参数(speaker/spk/rvq/instruct)下拉选项来自音色库

#### 5.5.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开部署参数页,执行机器选择、场景顾问、参数目录表与漂移处理的完整测试。

【前置操作】
1. 打开页面并进入 #/deploy
2. 记录当前选中机器(默认 node-a01)

---

【测试场景 1:机器选择】
1. 验证顶部机器 chips 列出当前集群全部机器,每台带状态点,选中机器 active
2. 点击另一台 chip,验证参数表「实际值」列随机器刷新
3. 从总览拓扑/机器行跳入,验证带入的机器被选中
4. 切到无机器集群(如新建空集群)进 #/deploy,验证显示「集群无机器可部署」类提示不报错

预期结果:
✅ chips 选中驱动全局 state.machine
✅ 空集群降级提示

---

【测试场景 2:KPI 与漂移提示】
1. 验证 4 卡:参数总数(含漂移参数子文案)、ops 参数(危险色)、热参数(青色)、当前场景
2. 存在漂移参数时验证页顶出现漂移 note(参数数/机器/配置来源=控制台)
3. 选中 bad 状态机器,验证离线 note 且场景推荐卡区域显示离线提示

预期结果:
✅ KPI 数值与目录统计一致
✅ 离线机器有明确警示

---

【测试场景 3:部署栈信息卡】
1. 验证字段:机器/版本标签/部署时间/配置来源/GPU·利用率/状态/最近推送(时间+人)
2. 验证版本标签 class 随机器状态变化(ok/warn/bad/orange)
3. 点击「推送配置 push」→ 验证 toast 推送提示
4. 点击「回滚 rollback」→ 验证 toast 回滚提示

预期结果:
✅ 信息卡与实际机器数据一致
✅ push/rollback 反馈可见

---

【测试场景 4:参数分组统计】
1. 验证「按组参数」表行=有当前 backend 的组(vad/stt/llm/tts 等),列=组名/当前 backend/参数数
2. 验证参数总数 = 各组之和
3. 验证表下生效方式图例 note 存在

预期结果:
✅ 分组计数自洽

---

【测试场景 5:场景顾问 chips 与推荐卡】
1. 验证场景 chips:无/低延迟/慢语速/噪声环境/边缘小盒/中英混说
2. 默认「无」时验证面板只有提示文案
3. 点「低延迟」:验证场景说明 note、推荐卡数量文案、每张卡包含参数名/所属组/生效差距徽章/当前值→建议值/理由·收益·代价/风险/ref
4. 已是目标值的卡验证有「相同」徽章
5. 切到「噪声环境」验证出现跨组联动橙色警示(scene.cross)
6. 选中场景后顶栏 KPI「场景」同步显示场景名

预期结果:
✅ 6 个 chip 可切换且互斥
✅ 推荐卡字段完整(why/gain/cost/risk/ref)

---

【测试场景 6:场景 diff 视图】
1. 在选中场景面板点「查看差异 diff」(data-diff),验证出现 diff 表:参数/当前/目标/差距徽章
2. 再点一次收起,验证 state.diffOn 切换
3. 对一台已满足全部建议值的机器点 diff,验证显示「无差异」空态文案
4. 切换场景后验证 diff 自动关闭不残留

预期结果:
✅ diff 展开/收起正确
✅ 空 diff 文案正确

---

【测试场景 7:应用到草稿与清理】
1. 选中场景点「应用到草稿」(data-apply),验证 toast 含参数数 n 与机器 id
2. 验证出现草稿条(draftbar,含数量),相关参数行目标值列旁出现「草稿」徽章
3. 切换另一台机器,验证其无草稿(草稿按机器隔离),切回后草稿仍在
4. 点「清空草稿」(data-clear-draft),验证草稿条与徽章消失、toast
5. 选中 bad 机器时应用,验证离线保护提示(不修改)

预期结果:
✅ 草稿按机器隔离
✅ apply/clear 反馈完整

---

【测试场景 8:参数组过滤】
1. 验证 group chips:ALL(N)+各分组(M),数字为参数计数
2. 点「VAD」验证仅显示 vad 卡;点 ALL 恢复全部
3. 验证卡内子分区行(shead)与表头 11 列:参数/默认值/来源/生效/暴露/影响面·成本/实际值/期望值/风险/锚点/操作
4. 验证默认值列附「范围 range」小字

预期结果:
✅ 组过滤与计数正确
✅ 参数表列完整

---

【测试场景 9:backend 条与只读组】
1. 验证 vad 卡顶部当前 backend=silero,可选含 silero/firered,当前项高亮
2. 验证 tts 卡当前 qwen3 且可选列表长(多后端)
3. 展开卡底「其他后端」折叠(details, backendFold),验证表列 backend/字段/必填/说明,收起默认
4. 切到「platform 平台」组,验证只读说明 note(平台托管)、参数行实际值为只读文本、操作列为「—」

预期结果:
✅ 当前/可选 backend 展示正确
✅ ro 参数不可编辑无操作按钮

---

【测试场景 10:ops 高危参数 toggle】
1. 在含 ops 参数的组(如 llm/tts)验证出现「显示 N 个运维参数」chip
2. 点击后验证表格加 show-ops 类、ops 行(暴露=ops,带风险徽章)可见,再点收起
3. 验证 ops 行默认隐藏且 toggle 文案计数正确

预期结果:
✅ ops 显示/隐藏切换正确
✅ ops 行风险徽章可见

---

【测试场景 11:参数编辑与漂移处理】
1. 修改一个可编辑参数实际值输入框(.pv)并触发 change
2. 验证出现「参数修改为模拟」toast 且输入值自动还原 data-orig
3. 找到带「不一致/drift」徽章的漂移行(背景 drift 高亮),验证操作列有「推送此参数 push」与「回滚 rollback」
4. 点单行 push → 验证 toast 含参数名与机器;点 rollback → 验证 toast 回滚含参数名
5. 非漂移行验证无按钮但有「一致 equal」徽章
6. 点漂移行「推送全部配置」(部署栈卡 push)验证与单行提示区分

预期结果:
✅ Demo 编辑即还原+toast(mock 语义)
✅ 漂移行徽章/按钮组正确,equal 行无按钮

---

【测试场景 12:音色类参数下拉】
1. 切到 tts 组,找到 speaker 参数行(如 qwen3_tts_speaker),验证控件是 select 而非 input
2. 展开下拉,验证选项含默认 Aiden + 就绪(ready)音色库条目(带来源后缀)
3. 选择另一值触发 change → 验证 mock toast + 还原
4. 验证 spk/rvq/instruct 类下拉仅列 clone/design 就绪音色(或 None)
5. 到音色库新建一个就绪音色后回本页,验证下拉新选项出现

预期结果:
✅ 音色参数选项源=音色库(联动)
✅ 未就绪/外部音色不进入候选

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 机器 chip | [data-machine-pick] | state.machine 切换 |
| 场景 chip | [data-scene] | state.scene+关 diff,重渲染 |
| diff | [data-diff] | state.diffOn 切换 |
| 应用草稿 | [data-apply] | applySceneDraft() 按机器写入 |
| 清草稿 | [data-clear-draft] | delete state.draft[machine] |
| 组过滤 | [data-group] | state.group 切换 |
| ops 显示 | [data-ops=组名] | state.opsOn[组] 切换 |
| 参数编辑 | input.pv / select.pv | change → toast + 还原 orig |
| 单行推送 | [data-push] | toast 含 p 与机器 |
| 单行回滚 | [data-rollback] | toast 含 p 与机器 |
| 整配置推送 | [data-act=push] | toast 推送 |
| 整配置回滚 | [data-act=rollback] | toast 回滚 |

---

【问题诊断】
- 场景切换后推荐卡不更新 → 检查 scenePanel 对 sceneByKey(state.scene) 的空值分支
- apply 后徽章不出现 → 检查 paramRow 的 draft[key] 命中(pk 组合 group+param)
- 漂移徽章错乱 → actualOf 与 expectedOf 比较(字符串化)
- 音色下拉缺新音色 → vcPickReady 过滤(status=ready 且非 external)与 src 分类
- ops 行不隐藏 → 检查 show-ops 默认 display:none 规则
```

#### 5.5.3 开发提示词

```
请基于以下信息,实现【部署参数】模块。

【模块信息】
- 服务: Console(:8000) 参数平台
- 页面路径: 左侧菜单「运维」→「部署参数」
- 路由: /deploy
- 权限前缀: console:
- 涉及权限码:
  - console:param:query(查看参数目录)
  - console:param:update(修改/推送参数)
  - console:param:ops(运维级参数显示与修改)

【前端文件清单】
- 主页面: console/frontend/src/views/ParamsView.vue
- 组件: ParamTree.vue、ParamField.vue、EffectBadge.vue、ExposureTag.vue、DiffTable.vue、PublishDialog.vue
- API 封装: console/frontend/src/api/params.ts

【后端文件清单】
- Controller: console/backend/app/api/params.py
- Service: console/backend/app/services/param_service.py(链路 A 进程重启 / 链路 B 会话热更新)

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 参数目录 | GET | /api/params/catalog |
| 实例实际值 | GET | /api/params/actual?machine=X |
| 期望值 diff | GET | /api/params/diff?machine=X |
| 提交变更 | POST | /api/params/publish |
| 热更新 | POST | /api/params/hot-reload |

【功能需求】
1. 按机器查看参数目录对齐表(默认值/来源/生效方式/暴露/影响面/实际/期望/风险/锚点)
2. 场景顾问:latency/slow/noisy/edge/mix 五场景推荐卡 + diff + 应用草稿(按机器隔离)
3. 漂移行支持单参数 push/rollback;整配置 push/rollback 走发布对话框
4. ops 参数默认隐藏、toggle 显示;platform 组只读
5. 音色类参数(speaker/spk/rvq/instruct)下拉选项由音色库驱动

【UI 规范】
- 参数目录事实源: docs/parameter-catalog.yaml(schema: s2s-parameter-catalog-v1),不得双写
- 生效徽章:启动即生效/热更新/容器级;暴露徽章:user/ops;风险类红色
- 漂移行高亮(drift),equal/diff 徽章区分

【参考实现】
- 原型: console-refactor-demo.html renderDeploy()/scenePanel()/paramRow()
- 文档: docs/parameter-catalog.md、docs/console-service.md(两条生效链路)

【测试验证】
实现完成后,使用 5.5.2 测试提示词中的测试场景验证,重点验证:
1. 场景 apply 后草稿徽章与机器隔离
2. 漂移行 push/rollback 单行操作
3. ops 参数显示 toggle
4. 音色参数联动音色库
5. platform 只读保护

【交付物清单】
- [ ] 部署参数页 .vue 与参数表/场景面板组件
- [ ] 前端 API 封装 .ts(含类型)
- [ ] 后端参数目录/实际值/diff/publish 接口
- [ ] 路由/菜单/权限码注册
- [ ] 审计日志接入(param/deploy 分类)
- [ ] 通过 5.5.2 所有测试场景
```

---

### 5.6 CON-06 音色库

**页面路径**: 左侧菜单「运维」→「音色库」(`#/voices`)  
**源码文件**: `console/design/console-refactor-demo.html`(`renderVoices()`、音色向导 `openVoiceWizard()/vcStepSource/vcStepAudio/vcStepPreview/vcStepPre/vcStepName/vcNext/vcBack/vcRunPre/vcSave()`),真实控制台 `console/frontend/src/views/VoicesView.vue`、`components/VoiceLibraryTable.vue`、`components/VoiceCreateDialog.vue`、`components/VoiceAudition.vue`  
**API 文件**: 无(Demo);真实控制台音色库后端接口  
**权限标识**: 无(Demo);真实控制台 `console:voice:*`

#### 5.6.1 测试场景

1. KPI 四卡(音色总数/外部 PocketTTS/训练中/总用量)+ 外部音色 note
2. 音色表列(名称/后端/来源/模型/语言/状态/用量/操作)与状态标签
3. 导入音色、试听测试、克隆、删除(confirm)
4. 向导步骤 1 来源选择(builtin/clone/design + base 下拉 + 未选报错)
5. 向导步骤 2 素材(上传/录制/转写/xvec / design 的 instruct + 校验)
6. 向导步骤 3 裁剪试听(波形/full·edge/数值保留时长/最小保留校验)
7. 向导步骤 4 预计算(运行动画/失败重试/产物列表/next 门控)
8. 向导步骤 5 命名保存(名称正则/唯一/摘要/写入映射)
9. builtin 跳步(跳过 2~4)与 design 跳试听(步骤 3)
10. 步骤 rail 进度与 back/next 禁用态
11. 新音色保存后回写音色表与部署参数下拉
12. 向导关闭不残留状态

#### 5.6.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开音色库页,执行列表 CRUD 与 5 步音色创建向导的完整测试。

【前置操作】
1. 打开页面并进入 #/voices
2. 等待列表渲染

---

【测试场景 1:KPI 与提示】
1. 验证 4 卡:音色总数(含 ready 数)、外部音色(PocketTTS)、训练中(aria)、活跃会话(总用量)
2. 存在 external 音色时验证顶部出现外部提示 note
3. 验证表头区「导入音色」与「新建音色」按钮存在

预期结果:
✅ KPI 数值与 VOICES 数据一致

---

【测试场景 2:列表列与标签】
1. 验证列:音色/后端/来源/模型/语言/状态/用量/操作
2. 验证来源标签 builtin/clone/design 三色区分
3. 验证 external 音色名后带橙色标签、状态 ready/partial/training 标签色
4. 验证 hint 区显示可被部署参数选用(pickable)的音色数

预期结果:
✅ 来源/状态标签正确

---

【测试场景 3:行操作】
1. 点行内「试听」(voice.test)→ 验证 toast 试听含音色名
2. 点「克隆」(voice.clone)→ 验证 toast 克隆含音色名
3. 点「删除」(voice.delete)→ 验证 confirm,取消则保留
4. 确认删除 → 音色从列表消失、KPI 总数减一、toast
5. 点「导入音色」→ 验证 toast 导入提示

预期结果:
✅ 删除带 confirm 且刷新 KPI
✅ 试听/克隆/导入为 mock 反馈

---

【测试场景 4:向导步骤 1 来源】
1. 点「新建音色」(voice.new),验证弹窗标题含「1/5 来源」、步骤 rail 5 节点
2. 不选来源直接点「下一步」→ 验证报「请选择来源」(bad.src)不前进
3. 选 builtin,验证出现「基础音色」下拉(列 ready 的 builtin + Aiden)
4. 选 clone,验证下一步进入素材(上传),无 base 下拉
5. 选 design,验证下一步进入 instruct 输入(无素材上传)

预期结果:
✅ 三种来源分支正确
✅ 未选来源不能前进

---

【测试场景 5:向导步骤 2 素材】
1. clone 来源到步骤 2,验证文件上传框、录制按钮、转写文本框、xvec 复选框
2. 不上传直接下一步 → 验证报「缺少参考音频」(bad.audio)
3. 点「录制」(data-vwrec),验证模拟加载 recording-6s4.wav(时长 6.4s)回显
4. 转写少于 4 字下一步 → 验证报 bad.text
5. design 来源到步骤 2,验证为 instruct 文本域,少于 8 字下一步报 bad.instruct

预期结果:
✅ 素材校验分来源区分
✅ 录制 mock 回填文件名与时长

---

【测试场景 6:向导步骤 3 裁剪试听】
1. clone 到步骤 3(载入素材后),验证波形 SVG(48 条 bar,保留窗口高亮 .win)
2. 点「整段 full」chip → t0=0、t1=总时长,full chip active
3. 点「去首尾 edge」chip → t0=250、t1=总-300,edge chip active
4. 修改 t0/t1 数值框,验证保留时长与进度条实时更新
5. 保留时长小于最小值(VC_MIN_KEEP)下一步 → 验证报 bad.trim(含 max/min)
6. 点「试听」(data-vwplay)→ 验证 toast

预期结果:
✅ 波形与保留窗口一致
✅ 裁剪边界校验生效

---

【测试场景 7:向导步骤 4 预计算】
1. 到步骤 4,验证模拟下拉(成功/失败)、步骤行、进度条、运行按钮、job 号
2. 未预计算直接「下一步」→ 按钮 disabled 且报 bad.pre
3. 点「开始预计算」(data-vwpre),验证步骤逐行 running→ok、进度增长到 100%
4. 模拟选失败重新运行 → 验证某步 fail + 失败 note + 审计 voice.precompute.fail + 按钮变「重试」
5. 成功后验证出现产物列表(clone: spk.npy/rvq.npy/ref.wav;design: voice.json)
6. 验证预计算完成后「下一步」解禁

预期结果:
✅ 预计算门控 next 禁用
✅ 失败可重试且写审计

---

【测试场景 8:向导步骤 5 命名保存】
1. 到步骤 5,验证名称输入框、摘要(来源/后端/素材/裁剪/产物)、将写入参数映射(vcWrites 按来源不同)
2. 名称留空保存 → 验证报必填;输入非法字符(空格/特殊符)→ 验证 bad.id
3. 名称与已有音色重复(忽略大小写)→ 验证 name.taken
4. builtin 来源步骤 5 摘要显示 base,写 speaker=名称或 base
5. 合法名称保存 → 验证新音色入列表(status=ready)、toast、审计 voice.create、弹窗关闭

预期结果:
✅ 名称正则与唯一性
✅ 摘要/写入映射随来源正确

---

【测试场景 9:来源跳步】
1. builtin 来源选 base 后点下一步,验证直接从步骤 1 跳到步骤 5(命名),rail 中 2~4 显 pending/跳过
2. design 来源到步骤 2(instruct)后下一步,验证跳过步骤 3(试听)到预计算
3. clone 全流程逐步不跳
4. 回退 back 时验证按同样跳步规则逆向到上一有效步骤

预期结果:
✅ builtin 跳过素材/预览/预计算
✅ design 跳过试听
✅ rail 状态同步

---

【测试场景 10:rail 与按钮态】
1. 验证每步顶部 pipe:done(✓)/current(●)/pending(·)状态正确
2. 步骤 1(首个)验证「返回」disabled
3. 非末步验证底部为「下一步」,末步为「保存」
4. 步骤 4 未预计算时验证「下一步」disabled

预期结果:
✅ rail 三态正确
✅ back/next/save 门控正确

---

【测试场景 11:新音色回写联动】
1. 新建一个 ready 的 clone 音色后,到「部署参数」tts 组 speaker/spk 下拉验证新音色出现
2. 回音色库验证列表、KPI 总数、pickable 数均更新
3. 验证新行来源标签为 clone/design/builtin 对应

预期结果:
✅ 音色库与部署参数下拉联动
✅ 计数一致

---

【测试场景 12:向导关闭不残留】
1. 向导中途点「关闭」(modal-close)或 ✕,验证弹窗关闭
2. 再次「新建音色」,验证 state.voice 重置为全新(step=0、src=null、pre=idle)
3. 验证无上次残留输入

预期结果:
✅ 关闭即重置

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 试听/克隆/删除 | [data-act=voice.test/clone/delete] | handleAct toast/confirm |
| 导入 | [data-act=voice.import] | toast |
| 新建 | [data-act=voice.new] | openVoiceWizard() |
| 来源卡 | [data-vwsrc=builtin/clone/design] | 设 src,重置 pre |
| 录制 | [data-vwrec] | 模拟文件名+时长 |
| 裁剪 full/edge | [data-vwtrim=full/edge] | 设 t0/t1 |
| 试听音频 | [data-vwplay] | toast |
| 预计算 | [data-vwpre] | vcRunPre() |
| 下一步/返回 | [data-vwnext]/[data-vwback] | vcNext/vcBack |
| 保存 | [data-vwsave] | vcSave() |

---

【问题诊断】
- 步骤跳转错 → 检查 vcSkip/vcForward/vcPrevStep 的 src 判定
- 预计算卡在运行 → vcRunPre 的 mTimer 链与 renderVoiceWizard 时机
- 保存后不回写 → vcSave 需 push VOICES 并 renderChrome/renderPage
- 校验不拦截 → vcValidate 每步返回串非空即拦截
```

#### 5.6.3 开发提示词

```
请基于以下信息,实现【音色库】模块。

【模块信息】
- 服务: Console(:8000)
- 页面路径: 左侧菜单「运维」→「音色库」
- 路由: /voices
- 权限前缀: console:
- 涉及权限码:
  - console:voice:query
  - console:voice:create(新建/克隆/导入)
  - console:voice:delete

【前端文件清单】
- 主页面: console/frontend/src/views/VoicesView.vue
- 组件: VoiceLibraryTable.vue、VoiceCreateDialog.vue、VoiceAudition.vue、VoicePicker.vue
- API 封装: console/frontend/src/api/voices.ts

【后端文件清单】
- Controller: console/backend/app/api/voices.py
- Service: console/backend/app/services/voice_service.py(预计算 job 队列)

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 音色列表 | GET | /api/voices |
| 新建音色 | POST | /api/voices |
| 上传素材 | POST | /api/voices/{id}/audio |
| 预计算 | POST | /api/voices/{id}/precompute |
| 试听 | POST | /api/voices/{id}/audition |
| 删除音色 | DELETE | /api/voices/{id} |

【功能需求】
1. 音色表:来源(builtin/clone/design)/后端/模型/语言/状态(ready/partial/training)/用量,支持导入/试听/克隆/删除
2. 5 步创建向导:来源→素材→裁剪试听→预计算→命名保存
3. builtin 跳过素材/预览/预计算;design 跳过试听;预计算成功前「下一步」禁用
4. 名称正则 + 忽略大小写唯一;新音色回写并供部署参数 speaker 下拉联动
5. 并发/超时取自 console/backend/app/config/_console.py 的 voice_* 配置项

【UI 规范】
- UI 库: 与 console/frontend 现有组件一致
- 表单: 文件上传 accept=audio/*、转写/instruct textarea、xvec 复选、t0/t1 数值裁剪
- 状态: rail 三态(✓/●/·),失败可重试,产物列表 mono

【参考实现】
- 原型: console-refactor-demo.html renderVoices()/openVoiceWizard()/vcStep*
- 现有: VoiceCreateDialog.vue、VoiceAudition.vue、VoicePicker.vue

【测试验证】
实现完成后,使用 5.6.2 测试提示词中的测试场景验证,重点验证:
1. 三种来源跳步规则
2. 各步校验(来源/素材/裁剪/预计算/名称)
3. 预计算失败重试与审计
4. 新音色与部署参数下拉联动

【交付物清单】
- [ ] 音色库页 .vue 与向导组件
- [ ] 前端 API 封装 .ts(含类型)
- [ ] 后端音色 CRUD + 预计算 job 接口
- [ ] 路由/菜单/权限码注册
- [ ] 审计日志接入(voice 分类)
- [ ] 通过 5.6.2 所有测试场景
```

---

### 5.7 CON-07 版本发布

**页面路径**: 左侧菜单「运维」→「版本发布」(`#/release`)  
**源码文件**: `console/design/console-refactor-demo.html`(`renderRelease()`、`handleAct('release.new'/'release.rollback')`),真实控制台 `console/frontend/src/views/VersionsView.vue`、`components/VersionTable.vue`  
**API 文件**: 无(Demo);真实控制台发布接口  
**权限标识**: 无(Demo);真实控制台 `console:release:publish`

#### 5.7.1 测试场景

1. KPI 四卡(版本总数/金丝雀百分比/灰度节点/漂移节点)
2. 金丝雀流水线四阶段(build/staging/canary/rollout)状态渲染
3. 新建发布按钮 toast
4. 回滚(canary 行)带 confirm + toast
5. 发布历史表(版本/日期/状态/进度条/节点/变更/操作按状态区分)

#### 5.7.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开版本发布页,执行流水线、历史表与发布/回滚操作的测试。

【前置操作】
1. 打开页面并进入 #/release

---

【测试场景 1:KPI】
1. 验证 4 卡:版本总数(current: v1.4.1)、金丝雀(百分比 + warming · node-b01 警告色)、v1.4.2 灰度(1/N)、漂移节点(警告色)
2. 验证数值与 RELEASES 首条一致

预期结果:
✅ 4 卡与当前发布态一致

---

【测试场景 2:流水线阶段】
1. 验证 4 个 stage:构建(done ✓)、预发(done ✓)、金丝雀(current ●)、全量(pending ·)
2. 验证各 sub 文案(日期/ok/批次/全量)
3. 验证卡头标题「金丝雀 · v1.4.2」与「新建发布」按钮

预期结果:
✅ 阶段状态 ✓/●/· 正确

---

【测试场景 3:新建发布与回滚】
1. 点「新建发布」(release.new)→ 验证 toast 新发布提示
2. 找到 canary 行点「回滚」(release.rollback)→ 验证 confirm,取消则不操作
3. 确认回滚 → 验证 toast 回滚提示
4. current 行验证操作列为「pin」标签不可点;rolled.back 行为 disabled 按钮

预期结果:
✅ 新建/回滚反馈正确
✅ 回滚带二次 confirm

---

【测试场景 4:历史表列与状态】
1. 验证列:版本/日期/状态/进度/节点/变更/操作
2. 验证 current 版本名后带「当前」标签
3. 验证状态标签(canary=橙,current=绿,rolled.back=红)
4. 验证进度条宽=pct,mono 百分比文案
5. 验证变更列多行(有 changes)与「无」降级

预期结果:
✅ 每状态行操作列呈现正确(回滚/锁定/禁用)
✅ 进度条与状态标签一致

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 新建发布 | [data-act=release.new] | toast |
| 回滚 | [data-act=release.rollback] | confirm + toast |
| 历史操作列 | 按 r.status 分支 | canary 回滚/current 标签/其他禁用 |

---

【问题诊断】
- 回滚无 confirm → 检查 handleAct 前置 confirm 分支
- 阶段态错 → 检查 stages 数组 s 值(done/current/pending)映射
```

#### 5.7.3 开发提示词

```
请基于以下信息,实现【版本发布】模块。

【模块信息】
- 服务: Console(:8000)
- 页面路径: 左侧菜单「运维」→「版本发布」
- 路由: /release
- 权限前缀: console:
- 涉及权限码:
  - console:release:query
  - console:release:publish

【前端文件清单】
- 主页面: console/frontend/src/views/VersionsView.vue
- 组件: VersionTable.vue
- API 封装: console/frontend/src/api/releases.ts

【后端文件清单】
- Controller: console/backend/app/api/releases.py
- Service: console/backend/app/services/release_service.py

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 发布历史 | GET | /api/releases |
| 新建发布 | POST | /api/releases |
| 回滚 | POST | /api/releases/{ver}/rollback |

【功能需求】
1. KPI 四卡 + 金丝雀流水线四阶段可视化
2. 历史表:版本/日期/状态/进度/节点/变更/操作,操作列按状态区分(回滚/锁定/禁用)
3. 新建发布与回滚均需二次确认,回滚仅 canary 可发起

【UI 规范】
- UI 库: 与 console/frontend 现有组件一致
- 状态: pipeline 三态(done/current/pending),状态标签三色
- 参考: docs/releases/*

【参考实现】
- 原型: console-refactor-demo.html renderRelease()
- 现有: VersionsView.vue、VersionTable.vue

【测试验证】
实现完成后,使用 5.7.2 测试提示词中的测试场景验证,重点验证:
1. 流水线阶段状态渲染
2. 回滚 confirm 与仅 canary 可回滚
3. 历史表操作列状态分支

【交付物清单】
- [ ] 版本发布页 .vue 与历史表组件
- [ ] 前端 API 封装 .ts(含类型)
- [ ] 后端发布/回滚接口
- [ ] 路由/菜单/权限码注册
- [ ] 审计日志接入(release 分类)
- [ ] 通过 5.7.2 所有测试场景
```

---

### 5.8 CON-08 审计日志

**页面路径**: 左侧菜单「运维」→「审计日志」(`#/audit`)  
**源码文件**: `console/design/console-refactor-demo.html`(`renderAudit()`、`audit()` 写入函数、`AUDITS` 常量),真实控制台 `console/frontend/src/views/AuditView.vue`、`components/AuditTable.vue`  
**API 文件**: 无(Demo);真实控制台审计接口  
**权限标识**: 无(Demo);真实控制台 `console:audit:query`、`console:audit:export`

#### 5.8.1 测试场景

1. KPI 四卡(全部变更/被拒操作/参数变更数/发布数)
2. 分类 chips 过滤(all/param/deploy/release/voice/machine/cluster/access)
3. 表格列(时间/操作者/类型/动作/结果/详情)与结果标签
4. 导出按钮 toast
5. 其他模块操作实时写入审计并在首行/总览事件联动

#### 5.8.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开审计日志页,执行分类过滤、导出与跨页写入联动的测试。

【前置操作】
1. 打开页面并进入 #/audit

---

【测试场景 1:KPI 卡片】
1. 验证 4 卡:全部变更(总数)、被拒操作(result≠ok 数, danger 色)、参数变更、发布变更
2. 记录各数值供后续联动对比

预期结果:
✅ 4 卡与 AUDITS 统计一致

---

【测试场景 2:分类过滤】
1. 验证 chips:全部/参数/部署/发布/音色/机器/集群/访问(默认「全部」active)
2. 点「机器」→ 验证仅 machine 类行显示、chip active、无其他分类
3. 依次点其余分类验证行数 = 该分类数据量
4. 选中无数据分类(如 fresh mock)→ 验证空态 colspan 行「audit.empty」
5. 点「全部」恢复全量

预期结果:
✅ 8 个 chip 过滤正确互斥
✅ 空结果有降级态

---

【测试场景 3:表格列与标签】
1. 验证列:时间/操作者/类型/动作/结果/详情
2. 验证类型列 accent 标签、结果列 statusTag(ok=绿/bad=红)
3. 验证失败登录类条目动作文案带参数插值、结果为失败
4. 验证详情为辅助小字且随语言切换

预期结果:
✅ 列完整、动作插值正确

---

【测试场景 4:导出】
1. 点卡片头「导出」(audit.export)→ 验证 toast 导出提示
2. 过滤后导出仍提示成功(mock)

预期结果:
✅ 导出反馈可见

---

【测试场景 5:跨页写入联动】
1. 到集群总览新增一个集群 → 回审计选「集群」分类,验证首行出现新增记录(who/time)
2. 到音色库完成一次失败预计算 → 回审计「音色」分类验证出现 fail 结果行
3. 验证 KPI「全部变更」计数 +1
4. 回总览验证「最近事件」首条同步为新记录

预期结果:
✅ 写操作实时进审计
✅ 失败操作计入「被拒」KPI

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 分类 chip | [data-cat] | state.cat 切换重渲染 |
| 导出 | [data-act=audit.export] | toast |
| 新记录写入 | audit(cat, act, val, result?) | 各模块保存函数调用 |

---

【问题诊断】
- 新记录不出现 → 检查各模块是否调用 audit() 而非只 toast
- 动作插值错误 → t(a.act, {param, value}) 的 a.val 分割逻辑
- KPI 与表行数不符 → 检查过滤后是否误用 list 而非 AUDITS 算 KPI
```

#### 5.8.3 开发提示词

```
请基于以下信息,实现【审计日志】模块。

【模块信息】
- 服务: Console(:8000)
- 页面路径: 左侧菜单「运维」→「审计日志」
- 路由: /audit
- 权限前缀: console:
- 涉及权限码:
  - console:audit:query
  - console:audit:export

【前端文件清单】
- 主页面: console/frontend/src/views/AuditView.vue
- 组件: AuditTable.vue
- API 封装: console/frontend/src/api/audit.ts

【后端文件清单】
- Controller: console/backend/app/api/audit.py
- Service: console/backend/app/services/audit_service.py

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 审计列表 | GET | /api/audit?category=&page= |
| 导出 | GET | /api/audit/export |

【功能需求】
1. KPI 四卡(全部/被拒/参数类/发布类)
2. 分类 chips 过滤(param/deploy/release/voice/machine/cluster/access)+ 空态
3. 表格列时间/操作者/类型/动作(含插值)/结果/详情,失败红标
4. 所有写操作(集群/机器/参数/音色/发布)必须同步写入审计

【UI 规范】
- UI 库: 与 console/frontend 现有组件一致
- 详情列仅运维可见;导出产 CSV 下载

【参考实现】
- 原型: console-refactor-demo.html renderAudit()/audit()
- 现有: AuditView.vue、AuditTable.vue

【测试验证】
实现完成后,使用 5.8.2 测试提示词中的测试场景验证,重点验证:
1. 8 类过滤与空态
2. 失败操作的 KPI/标签
3. 跨页写入实时性

【交付物清单】
- [ ] 审计页 .vue 与表格组件
- [ ] 前端 API 封装 .ts(含类型)
- [ ] 后端审计查询/导出接口与各写链路埋点
- [ ] 路由/菜单/权限码注册
- [ ] 通过 5.8.2 所有测试场景
```

---

### 5.9 CON-09 实时对话

**页面路径**: 左侧菜单「会话」→「实时对话」(`#/conversation`)  
**源码文件**: `console/design/console-refactor-demo.html`(`renderConversation()`、`toggleCall()/stepTalk()/paintCall()/addBubble()/pickInstance()`),真实控制台 `console/frontend/src/views/VoiceView.vue`、`features/voice/components/`(OrbStage/TranscriptList/MicGate/QueueOverlay/TurnTimings)  
**API 文件**: 无(Demo);真实控制台 WebSocket `ws://…/v1/realtime`(经 :8000 代理)  
**权限标识**: 无(Demo);真实控制台需登录 + 会话配额

#### 5.9.1 测试场景

1. 页面布局:orb 舞台 + 右侧路由/工具/verbosity 面板
2. 发起呼叫:选中最小负载 ok 实例 + 路由面板回填 + toast
3. 对话状态机动画(listening→thinking→speaking 循环、气泡逐条追加)
4. 挂断(call.end)与脚本自然结束的文案差异
5. 路由面板字段(实例/端点/音色/last TTFT/turn 模型)
6. 工具开关(data-tool)切换 + toast 含开关态
7. verbosity 下拉(terse/balanced/detailed)

#### 5.9.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

打开实时对话页,执行呼叫状态机、路由面板与工具开关的测试。

【前置操作】
1. 打开页面并进入 #/conversation
2. 确认当前集群存在 state=ok 的实例(否则验证无实例分支)

---

【测试场景 1:页面布局】
1. 验证左侧舞台卡:orb 元素、状态文字「空闲」、提示气泡「点击呼叫开始会话」、主按钮「呼叫」
2. 验证右侧面板三段:路由信息/工具开关/verbosity 下拉
3. 验证路由字段初始为占位「—」

预期结果:
✅ 布局完整,初始 idle

---

【测试场景 2:发起呼叫】
1. 点「呼叫」(data-act=call)
2. 验证 toast 开始提示含实例 id
3. 验证路由面板回填:实例/端点 node:8765/音色 sara/last TTFT/smart-turn 模型
4. 验证 transcript 区先出现两条 meta 气泡(路由节点/会话已开始),hint 气泡被移除
5. 验证按钮变「挂断」且去 primary 样式,状态文字变连接中→聆听
6. 在无 ok 实例的集群重复呼叫 → 验证 toast「无可用实例」不进入会话

预期结果:
✅ 选实例=最小负载 ok 实例
✅ 无实例保护

---

【测试场景 3:对话状态机动画】
1. 呼叫后持续观察 ≥15s
2. 验证状态文字按 聆听(listening)→思考(thinking)→说话(speaking) 循环,orb class 同步变色
3. 验证 user 气泡与 assistant 气泡交替追加且滚动到底部
4. 验证脚本播完后自然停止:回到 idle、按钮恢复「呼叫」、出现停止 meta 气泡

预期结果:
✅ 状态机顺序与 orbClass 一致
✅ 气泡逐条追加

---

【测试场景 4:挂断】
1. 会话中点「挂断」
2. 验证立即回 idle、meta「会话已结束」气泡、toast
3. 验证挂断后路由面板保留上次实例信息
4. 再次呼叫验证会话从头开始(step 重置)

预期结果:
✅ 挂断中断定时器与状态

---

【测试场景 5:工具开关】
1. 验证右侧工具段列出全部 TOOLS(名称+描述+开关 on 态)
2. 点击开关(data-tool)→ 验证 on 类切换 + toast 含工具名与开/关
3. 多开关独立不互斥

预期结果:
✅ 开关双向切换 + 反馈

---

【测试场景 6:verbosity 下拉】
1. 验证 #verbosity 选项 terse/balanced/detailed,默认 balanced
2. 切换到 terse,验证选中态保持(页面内 mock)

预期结果:
✅ 三档可选、默认正确

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 呼叫/挂断 | #call-btn [data-act=call] | toggleCall() |
| orb/状态 | #orb/#orb-state | paintCall() 随 state |
| 气泡区 | #transcript | addBubble(user/assistant/meta) |
| 工具开关 | .switch[data-tool] | TOOLS[i].on 翻转 |
| verbosity | #verbosity | 本地选择(mock) |

> 真实控制台补充验证:WS 升级 `ws://localhost:8000/v1/realtime` 收到 session.created;麦克风权限缺失时的引导态;断线重连提示(对应 set.reconnect)。

【问题诊断】
- 呼叫无反应 → 检查 pickInstance() 在当前集群 ok 实例池为空
- 动画卡住 → stepTalk 的 setTimeout 链是否被挂断正确 clearTimeout
- 气泡重叠 hint → addBubble 首条时移除 hint 的条件比较
- 状态机跳序 → SCRIPT_LINES role 分支与延迟(900/600/1100ms)
```

#### 5.9.3 开发提示词

```
请基于以下信息,实现【实时对话】模块。

【模块信息】
- 服务: Console(:8000 代理) → Pipeline(:8765 /v1/realtime)
- 页面路径: 左侧菜单「会话」→「实时对话」
- 路由: /conversation
- 权限前缀: console:
- 涉及权限码:
  - console:session:start(发起会话,计配额)

【前端文件清单】
- 主页面: console/frontend/src/views/VoiceView.vue
- 组件: features/voice/components/OrbStage.vue、TranscriptList.vue、MicGate.vue、QueueOverlay.vue、TurnTimings.vue
- WS 封装: console/frontend/src/api/realtime.ts

【后端文件清单】
- Controller: console/backend/app/api/realtime.py(WS 代理 /v1/realtime)
- Service: LB /session 会话分配 + 配额 limiter

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 会话分配 | POST | /session(经 LB) |
| 实时语音 | WS | /v1/realtime |
| 服务状态 | GET | /api/v1/status |

【功能需求】
1. 呼叫前按最小负载选 ok 实例;无实例给出提示
2. orb 状态机 idle→connecting→listening→thinking→speaking,挂断中断在途会话
3. 实时转写气泡列表(user/assistant/meta),自动滚动
4. 右侧面板展示路由信息(实例/端点/音色/TTFT/turn 模型),工具开关与 verbosity 可会话中切换
5. 浏览器不直连 8765,一律同源 /v1 代理

【UI 规范】
- UI 库: 与 console/frontend 现有组件一致;orb 动效对齐原型
- 音频: 麦克风采集 + 播放 worklets(参考 demo/worklets)

【参考实现】
- 原型: console-refactor-demo.html renderConversation()/toggleCall()
- 现有: demo/main.js 的 RealtimeSession 集成、VoiceView.vue

【测试验证】
实现完成后,使用 5.9.2 测试提示词中的测试场景验证,重点验证:
1. 选实例与无实例保护
2. 状态机与挂断中断
3. WS 真实链路 session.created
4. 工具开关与会话同步

【交付物清单】
- [ ] 对话页 .vue 与 orb/转写组件
- [ ] WS 封装与重连逻辑
- [ ] 后端 /v1/realtime 代理与会话分配
- [ ] 配额/计费接入(demo limiter 同源逻辑)
- [ ] 路由/菜单/权限码注册
- [ ] 通过 5.9.2 所有测试场景
```

---

### 5.10 CON-10 抽屉与全局弹窗

**页面路径**: 跨页面一层的右侧抽屉(历史/工具/设置)与通用 Modal/toast 机制  
**源码文件**: `console/design/console-refactor-demo.html`(`openOverlay()/closeOverlay()`、`renderHistory()/renderTools()/renderSettings()`、`openModal()/closeModal()`、`toast()`)  
**API 文件**: 无(Demo)  
**权限标识**: 无(Demo)

#### 5.10.1 测试场景

1. 历史抽屉:条目渲染、时长/轮次/实例、回放按钮 toast
2. 工具抽屉:开关与对话页同步联动
3. 设置抽屉:语言下拉/音色选择/verbosity/开关(wake/denoise/reconnect 静态)
4. 抽屉互斥与遮罩/✕关闭、Esc 行为
5. 通用 Modal 生命周期:多弹窗互不残留、modalTimers 清理
6. toast 机制:出现、文案、~2.4s 自动消失、连续操作不叠加

#### 5.10.2 测试提示词

```
/qa

前端 Demo:http://localhost:4173/design/console-refactor-demo.html

执行抽屉(历史/工具/设置)与全局 Modal/toast 机制的测试。

【前置操作】
1. 打开页面任意位置

---

【测试场景 1:历史抽屉】
1. 导航点「历史记录」打开 #drawer-history
2. 验证标题、描述/筛选提示文案、HISTORY 逐条(时间/实例/摘要/轮次/时长)
3. 点条目内「回放」(data-act=replay)→ 验证 toast 回放提示
4. 验证抽屉内无页面跳转副作用

预期结果:
✅ 历史条目字段完整
✅ 回放为 mock toast

---

【测试场景 2:工具抽屉与联动】
1. 打开 #drawer-tools,验证工具行(名称+描述+开关)
2. 记录某开关状态,切到实时对话页验证同一开关状态一致(TOOLS 共享)
3. 在抽屉内切换开关,验证 toast + 对话页同步反映

预期结果:
✅ 工具开关跨页一致

---

【测试场景 3:设置抽屉】
1. 打开 #drawer-settings
2. 验证 #set-lang 下拉(English/中文)与当前语言 selected;选择后验证全站切语(同 CON-01 场景 7)
3. 验证 #set-voice 仅列 ready 音色且默认 sara selected
4. 验证 verbosity 下拉、wake(关)/denoise(开)/reconnect(开)三个开关(data-static 为静态展示)
5. 点静态开关,验证不报错(展示型)

预期结果:
✅ 语言/音色选项源正确
✅ 静态开关无副作用

---

【测试场景 4:抽屉互斥与关闭】
1. 打开历史抽屉后再点工具入口,验证先关闭旧抽屉再开新抽屉(同一时刻仅一个 .open)
2. 点遮罩 #overlay 验证关闭
3. 点抽屉 ✕(data-close)验证关闭
4. 连点不同抽屉入口无残留 DOM(.open 叠加)

预期结果:
✅ 同时仅一个抽屉开启
✅ 遮罩/✕ 均可关

---

【测试场景 5:通用 Modal 生命周期】
1. 打开集群新增弹窗,不保存直接点 ✕/遮罩 #modal-overlay → 验证关闭且 #modal-body 下次打开重建
2. 机器测试进行中关闭弹窗 → 验证 modalTimers 被清空,无延时回调在关后误触(无报错/不入库)
3. 快速连续打开两个不同弹窗(如先集群后机器),验证标题/内容不串位
4. 弹窗开启时验证背后页面不可误交互(遮罩层)

预期结果:
✅ 弹窗关闭即清定时器
✅ 无内容残留/串位

---

【测试场景 6:toast 机制】
1. 触发任意 toast(如语言切换),验证 #toast.show 出现文案
2. 等待 ~2.4s 验证自动消失
3. 连续快速触发多个 toast,验证仅保留最新一条不叠加(旧 timer 被清)
4. 切换页面后 toast 不阻塞交互

预期结果:
✅ 单例 toast 自隐
✅ 不被旧定时器提前清除

---

【交互元素对照】

| 元素 | 选择器/属性 | 行为 |
|------|------------|------|
| 抽屉入口 | #nav [data-overlay] | openOverlay(kind) |
| 抽屉关闭 | [data-close] / #overlay | closeOverlay() |
| 回放 | [data-act=replay] | toast |
| 工具开关 | .switch[data-tool] | 共享 TOOLS 状态 |
| 设置语言 | #set-lang | change → setLang |
| 静态开关 | [data-static] | 无副作用 |
| Modal | #modal/#modal-overlay/[data-modal-close] | openModal/closeModal |
| toast | #toast | toast() 2400ms |

---

【问题诊断】
- 抽屉叠加 → openOverlay 未先 closeOverlay 或 state.overlay 判定错
- 弹窗关闭后回调仍跑 → closeModal 未 clearTimeout(modalTimers)
- toast 闪退 → 连续触发时 toastTimer 未 clearTimeout
```

#### 5.10.3 开发提示词

```
请基于以下信息,实现【抽屉与全局弹窗】通用层。

【模块信息】
- 服务: Console(:8000)
- 页面路径: 全局层(跨页面)
- 路由: 无(组件级)
- 权限前缀: console:
- 涉及权限码: 登录态即可

【前端文件清单】
- 抽屉: features/voice/components/HistoryDrawer.vue、ToolsDialog.vue、SettingsDialog.vue
- 弹窗: components/ConfirmDialog.vue
- 布局容器: layouts/ConsoleLayout.vue

【后端文件清单】
- 历史/回放: console/backend/app/api/sessions.py

【API 端点】
| 操作 | 方法 | 路径 |
|------|------|------|
| 会话历史 | GET | /api/sessions |
| 回放 | POST | /api/sessions/{id}/replay |

【功能需求】
1. 右侧抽屉统一容器(遮罩 + 滑入),同时只允许一个开启,✕/遮罩可关
2. 历史抽屉展示时长/轮次/实例/摘要与回放
3. 工具/设置抽屉与主页面状态共享(双向同步)
4. 全局 Modal + toast 单例,关闭时清理定时器

【UI 规范】
- UI 库: 与 console/frontend 现有组件一致
- 无障碍: dialog aria-modal、焦点陷阱、Esc 关闭

【参考实现】
- 原型: console-refactor-demo.html openOverlay/openModal/toast
- 现有: HistoryDrawer.vue、SettingsDialog.vue、ConfirmDialog.vue

【测试验证】
实现完成后,使用 5.10.2 测试提示词中的测试场景验证,重点验证:
1. 抽屉互斥与关闭
2. 工具开关跨页一致
3. Modal 定时器清理与无残留
4. toast 单例自隐

【交付物清单】
- [ ] 抽屉/Modal/toast 通用层实现
- [ ] 历史/回放接口封装
- [ ] 共享状态 store(工具/设置)
- [ ] 无障碍与 Esc 行为
- [ ] 通过 5.10.2 所有测试场景
```

---

## 6.测试结果报告模板

```markdown
# Console 服务测试报告

**测试日期**: YYYY-MM-DD  
**测试人员**: AI Agent (gstack /qa)  
**测试环境**: http://localhost:4173/design/console-refactor-demo.html  
**Console 服务**: http://localhost:8000(真实控制台)

## 测试摘要

| 指标 | 值 |
|------|------|
| 总用例数 | N |
| 通过 | X |
| 失败 | Y |
| 跳过 | Z |
| 通过率 | X/N% |
| 执行时长 | M 分钟 |

## 结果汇总

| 模块 | 用例数 | 通过 | 失败 | 跳过 | 通过率 |
|------|--------|------|------|------|--------|
| CON-01 全局框架与导航 | 7 | 7 | 0 | 0 | 100% |
| CON-02 集群总览 | 9 | 9 | 0 | 0 | 100% |
| CON-03 流量与路由 | 9 | 9 | 0 | 0 | 100% |
| CON-04 计算节点管理 | 10 | 10 | 0 | 0 | 100% |
| CON-05 部署参数 | 12 | 12 | 0 | 0 | 100% |
| CON-06 音色库 | 12 | 11 | 1 | 0 | 91.7% |
| CON-07 版本发布 | 5 | 5 | 0 | 0 | 100% |
| CON-08 审计日志 | 5 | 5 | 0 | 0 | 100% |
| CON-09 实时对话 | 7 | 7 | 0 | 0 | 100% |
| CON-10 抽屉与全局弹窗 | 6 | 6 | 0 | 0 | 100% |
| **合计** | **82** | **X** | **Y** | **Z** | **X/N%** |

## 失败用例详情

### CON-06 音色库 — 测试场景 9:来源跳步

- **现象**: builtin 来源未跳过素材/预览/预计算,仍逐页要求填写
- **控制台错误**: 无(逻辑错误,非异常)
- **截图**: [.gstack/qa-reports/screenshots/con06-skip-step.png](.gstack/qa-reports/screenshots/con06-skip-step.png)
- **定位**: `vcForward()/vcSkip()` 对 `src==='builtin'` 的判定条件遗漏
- **修复建议**: `vcSkip = (v,i) => v.src==='builtin' ? i>=1 && i<=3 : v.src==='design' && i===2`
- **修复文件**: `console/design/console-refactor-demo.html`
- **状态**: 已修复

## 建议

1. **高优先级**:修复音色向导跳步与预计算门控,影响主流程
2. **中优先级**:部署参数漂移行与草稿按机器隔离需回归验证
3. **低优先级**:流量页时间窗切换的数值一致性断言可入自动化
4. **测试补充**:建议补充窄屏(≤ 1280px)下 .tscroll 横向滚动与表格列完整性的响应式测试
```

---

## 7.模块开发对照与补全清单

本章节对照设计原型 `console-refactor-demo.html`(参考)与 `console/frontend` 实现(当前项目),梳理 Console 各模块的实现状态与补全建议。

### Console 模块补全对照表

| 模块 | 原型页面/函数 | console/frontend 路径 | 前端状态 | 后端状态 | 补全建议 |
|------|-----------------|----------------------|---------|---------|---------|
| 全局框架与导航 | NAV/renderChrome/applyRoute | layouts/ConsoleLayout.vue | ✅ 原型完整 | ✅ | 真实项目需对齐三分组导航与集群下拉 |
| 集群总览 | renderOverview/topoSVG/集群 CRUD | views/InstancesView.vue | ⚠ 部分(拓扑/集群 CRUD 待确认) | ⚠ | 原型含集群 CRUD,真实项目需核实是否已有集群写接口 |
| 流量与路由 | renderLb/tokenSummaryCard | views/InstanceTrendsView.vue + InstanceTrendChart.vue | ✅ 已有趋势页 | ✅ | 对齐 Token 时间窗与 egress 分类展示 |
| 计算节点管理 | renderMachines/startMachineTest | (新增)MachinesView.vue | ❌ 未见独立页 | ⚠ | 需新增机器 CRUD + 注册测试入库链路 |
| 部署参数 | renderDeploy/scenePanel/paramRow | views/ParamsView.vue + ParamTree/ParamField/DiffTable/PublishDialog | ✅ 完整 | ✅ | 场景顾问(五场景)与音色参数下拉为原型增强,需回归对齐 |
| 音色库 | renderVoices/5 步向导 | views/VoicesView.vue + VoiceCreateDialog/VoiceAudition/VoicePicker | ✅ 完整 | ✅ | 向导跳步/预计算门控/与 speaker 下拉联动需重点测 |
| 版本发布 | renderRelease | views/VersionsView.vue + VersionTable.vue | ✅ 完整 | ✅ | 金丝雀回滚二次确认与仅 canary 可回滚 |
| 审计日志 | renderAudit | views/AuditView.vue + AuditTable.vue | ✅ 完整 | ✅ | 确保所有写链路都埋 audit() |
| 实时对话 | renderConversation/toggleCall | views/VoiceView.vue + features/voice/* | ✅ 完整 | ✅(WS 代理) | 真实链路需验 WS session.created 与配额 |
| 抽屉与弹窗 | openOverlay/openModal/toast | HistoryDrawer/ToolsDialog/SettingsDialog/ConfirmDialog | ✅ 完整 | — | 抽屉互斥/Modal 定时器清理/toast 单例 |

> 状态图例:✅ 已具备;⚠ 部分/需核实;❌ 缺失需新建。表格仅为对照指引,实际以仓库当前 `console/frontend/src/views` 与 `console/backend/app/api` 为准。

---

## 8.文档版本

| 版本 | 日期 | 修改内容 | 作者 |
|------|------|---------|------|
| 1.0.0 | 2026-10-28 | 基于 scene-template.md 结构与风格,面向 console-refactor-demo.html 生成完整浏览器自动化测试文档,涵盖 CON-01~CON-10 共 82 个测试场景与全模块测试/开发提示词 | AI Agent |

| 项目 | 值 |
|------|------|
| 适用服务 | Console(:8000 后端 + Vue3 SPA 前端) |
| 测试对象 | `console/design/console-refactor-demo.html`(纯前端 Mock 原型) |
| Demo 入口 | http://localhost:4173/design/console-refactor-demo.html |
| 真实前端入口 | http://localhost:3000 |
| 默认账号 | admin / admin123456(Demo 无需登录) |
| 测试 Skill | `/qa`, `/qa-only`, `/open-gstack-browser`, MCP Playwright |
| 模块总数 | 10 个(CON-01~CON-10) |
| 场景总数 | 82 个 |
