# 安装与配置总结

面向:Grafana / Prometheus / OpenTelemetry 的可观测性工具链,配合 Claude 的
skill + CLI + MCP 三层形态。

按优先级分三档。**先跑通第一档再往下走** —— 现在手上的四套模板、一份 skill、
两份 recording rules 都还没在真实环境验证过,继续装工具的边际收益在递减。

---

## 目录

- [第一档:现在就装](#第一档现在就装)
  - [Skills](#skills)
  - [CLI](#cli)
  - [模板仓库](#模板仓库)
- [第二档:接下来两周](#第二档接下来两周)
- [第三档:暂缓](#第三档暂缓)
- [MCP 连接器](#mcp-连接器)
- [CI 集成](#ci-集成)
- [验证清单](#验证清单)
- [排错](#排错)

---

## 第一档:现在就装

### Skills

**Grafana 官方**(Apache-2.0,持续维护):

```bash
claude plugin marketplace add grafana/skills

claude plugin install grafana-core@grafana-skills   # dashboarding / promql / alerting-irm / opentelemetry / alloy / beyla / grafana-oss
claude plugin install grafana-lgtm@grafana-skills   # prometheus / loki / tempo / mimir / pyroscope
```

非 Claude Code 环境(Cursor、Codex 等遵循 Agent Skills 标准的工具):

```bash
npx skills add grafana/skills
```

**Anthropic 官方**:

```bash
claude plugin marketplace add anthropics/skills
claude plugin install example-skills@anthropic-agent-skills
```

其中两个直接相关:`skill-creator`(生成 skill 骨架并跑评测)、
`mcp-server`(写 MCP server 的指南)。

> 注意:该仓库里的 document-skills(docx/pdf/pptx/xlsx)是 point-in-time
> 快照,不再维护,且已预装在 Claude 里,不需要单独装。

**自有 skill**:

```bash
tar xzf grafana-dashboard-skill.tar.gz
mkdir -p ~/.claude/skills
cp -r grafana-dashboard ~/.claude/skills/grafana-central-templates
```

只覆盖组织约定(folder 划分、uid 命名、`__SVC_LABEL__` 机制、部署契约、
校验脚本)。通用 Grafana 和 PromQL 知识交给 `grafana-core`,不要重复维护。

验证已装上:

```bash
claude plugin list
ls ~/.claude/skills/
```

### CLI

| 工具 | 用途 | 获取方式 |
|---|---|---|
| `promtool` | 规则语法校验 + **单元测试** | Prometheus 二进制包自带 |
| `python3` | 运行 `validate.py`(纯标准库) | 系统自带,3.8+ |
| `jq` | `deploy.sh` 依赖 | `apt install jq` / `brew install jq` |
| `curl` | 查 Prometheus API | 系统自带 |

```bash
which promtool python3 jq curl
```

`promtool` 是这一档里最重要的。它能给 recording rules 写单元测试,离线跑,
不需要连 Prometheus:

```bash
promtool check rules recording-rules/*.yml    # 语法
promtool test rules tests/*.yml               # 单元测试
promtool check config prometheus.yml          # 主配置
promtool tsdb analyze /path/to/data           # 基数分析
```

### 模板仓库

```bash
tar xzf grafana-central.tar.gz
cd grafana-central
git init -b main && git add . && git commit -m "feat: 中心 Grafana 模板初版"
```

推到公司 GitLab。注意:把公司代码放个人 GitHub 账户下,很多公司的信息安全
规定是明确禁止的,不区分 public / private,推之前确认一下。

**部署前必须替换两个占位符:**

| 占位符 | 含义 | 怎么查 |
|---|---|---|
| `__SVC_LABEL__` | 服务标识 label | 见下方命令 |
| `__PROD_JOB_RE__` | 匹配生产部署 job 的正则 | 看 Jenkins job 命名 |

```bash
# 有哪些 HTTP 相关指标
curl -s 'http://<prom>/api/v1/label/__name__/values' \
  | jq '.data[] | select(test("http_server|http_request"))'

# 这个指标带哪些 label
curl -s 'http://<prom>/api/v1/series?match[]=<metric>' | jq '.data[0] | keys'
```

常见值:`job` / `service_name` / `app` / `application` / `kubernetes_name`。
不同埋点来源可能不一样,那就在 `normalize-http.yml` 里分 group 各改各的。

---

## 第二档:接下来两周

### OpenTelemetry Collector 工具

```bash
otelcol validate --config=config.yaml   # 配置校验,Collector 二进制自带
otelcol components                       # 列出当前发行版包含的组件
```

**telemetrygen** —— 造合成遥测数据验证管道通不通,地位相当于 promtool 之于
规则:

```bash
go install github.com/open-telemetry/opentelemetry-collector-contrib/cmd/telemetrygen@latest

telemetrygen metrics --otlp-endpoint localhost:4317 --otlp-insecure --duration 10s
telemetrygen traces  --otlp-endpoint localhost:4317 --otlp-insecure --traces 100
```

**ocb**(Collector Builder)—— 自建发行版,只打包实际用到的组件,减小体积和
攻击面。等 Collector 配置稳定后再考虑。

### Grafana Cloud 相关 skill(自建环境也适用的部分)

```bash
claude plugin install grafana-cloud@grafana-skills
```

大部分是 Cloud 专用,但这两个对自建 Prometheus 同样有价值:

- `prometheus-label-strategy` —— label schema 审计与设计
- `prometheus-cardinality-troubleshooter` —— 基数爆炸诊断

混用 OTel 和 Micrometer 时基数问题迟早会来:OTel 默认埋点的 label 基数通常
比 Micrometer 高,`http.route` 没做归一化就会炸。

---

## 第三档:暂缓

### Weaver

OpenTelemetry 官方的语义约定管理 CLI。把遥测当成公开 API:用 YAML 定义
registry,CLI 校验、生成代码和文档。

```bash
# 二进制:见 open-telemetry/weaver releases 页面
# 或 Docker 镜像 otel/weaver
weaver registry check -r ./model
weaver registry live-check         # 拿真实遥测比对约定
weaver registry generate --templates ./templates/java/ --output ./gen/
weaver registry diff               # 比对两个版本
weaver registry mcp                # 自带 MCP server
```

**为什么暂缓:** 它解决的是「让各团队按同一份约定埋点」,前提是有人能推动
各团队改代码。你们现在连一个团队都还没接入模板,这时候上 Weaver 只会得到
一份没人遵守的漂亮文档。recording rules 那套归一化补丁不需要别人配合就能落地,
先用着。

等模板真的推开、命名冲突变成实际痛点了再上。届时中心仓库存约定 YAML、各团队
提 MR、平台组 review —— 和你们做 CI/CD 模板是同一套治理模式。

> Weaver 版本迭代较快,命令细节以官方文档为准。

### gcx

Grafana Cloud 资源管理 CLI。**自建 Grafana 用不上**,跳过。

---

## MCP 连接器

### Grafana MCP

```
https://github.com/grafana/mcp-grafana
```

需要 Grafana 9.0+。权限按用途分两档:

| 用途 | 需要的权限 |
|---|---|
| 只读探索 | `dashboards:read` + `datasources:query` |
| 创建/更新看板 | `dashboards:create` + `dashboards:write` + folder scope |

嫌配细粒度 scope 麻烦可以直接给 service account 分配 **Editor** 内置角色,
但建议把 folder scope 限定在 `Central Templates`,避免误伤团队看板。

**建两个 token 更稳:**

- Viewer token —— 生产环境查询用
- Editor token —— folder scope 限定在沙箱目录,AI 生成的看板先落沙箱,
  人工确认后再挪到正式目录

**context 管理**(官方明确建议):

- 改动前先 `get_dashboard_summary` 看概览
- 只需要局部时用 `get_dashboard_property` 配 JSONPath
- 避免 `get_dashboard_by_uid` 拉整份 JSON,真实看板轻易超过 100KB
- 小改动用 `update_dashboard` 的 patch 模式,别传整份 JSON

### GitHub MCP

官方托管端点,不需要本地跑 Docker:

```
https://api.githubcopilot.com/mcp/
```

在 Claude 设置里添加自定义连接器,填入 URL 后走 OAuth 授权。加 `/readonly`
可限制为只读。授权时建议只勾选需要的仓库,而不是全部。

---

## CI 集成

### GitLab(`.gitlab-ci.yml` 已在仓库里)

需要配置的 CI/CD Variables(全部设为 Masked + Protected):

```
GRAFANA_URL_STG / GRAFANA_TOKEN_STG
GRAFANA_URL_PRD / GRAFANA_TOKEN_PRD
SVC_LABEL
PROD_JOB_RE
```

三段流水线:validate 在每个 MR 跑,staging 合入默认分支自动部署,
**生产手动触发**。看板影响面大,手动点一次是便宜的保险。

### 校验步骤该包含什么

```bash
promtool check rules recording-rules/*.yml
promtool test rules tests/*.yml
python3 ~/.claude/skills/grafana-central-templates/scripts/validate.py \
  dashboards/*.json --svc-label "$SVC_LABEL"
GRAFANA_URL=http://dummy DRY_RUN=1 bash scripts/deploy.sh
```

`validate.py` 只用 Python 标准库,不依赖 jq。它检查的是 JSON review 看不出来
的东西:面板重叠、id 重复、硬编码 datasource UID、`percent` 与 `percentunit`
混淆、阈值配了但 `color.mode` 不对所以不生效。

### 部署顺序

**recording rules 必须先于 dashboard 部署。** 规则还没求值时看板全是
"No data",由此产生的 bug 报告成本远高于把顺序排对。

---

## 验证清单

按顺序做,每步通过再进行下一步:

- [ ] `claude plugin list` 能看到 grafana-core、grafana-lgtm
- [ ] `ls ~/.claude/skills/` 能看到 grafana-central-templates
- [ ] `which promtool python3 jq` 三个都有
- [ ] 查清服务标识 label,填入 CI 变量 `SVC_LABEL`
- [ ] 确认生产部署 job 的正则,填入 `PROD_JOB_RE`
- [ ] `promtool check rules` 通过
- [ ] `promtool test rules` 通过 —— **这一步目前还没有测试文件,需要先写**
- [ ] recording rules 加载到 Prometheus,以下查询有数据:
      ```promql
      svc:http_requests_total:rate5m
      count by (source) (svc:http_requests:rate5m)
      ```
- [ ] `validate.py` 对四份 dashboard 零 error
- [ ] Grafana service account 权限确认(Editor 或等价 scope)
- [ ] staging 部署成功,看板有数据
- [ ] 生产手动部署

---

## 排错

**`deploy.sh` 报「JSON 语法错误」但 JSON 是好的**
缺 jq。脚本已加依赖检查,会明确报「缺少依赖: jq」。

**看板全是 No data**
按顺序排查,从原始指标往外走,不要从面板往里改:
1. 裸指标名在 Prometheus 里有数据吗 → 没有就是埋点或抓取问题
2. 去掉 label 过滤有数据吗 → 有就是 label 名或值错了
3. recording rule 存在且在求值吗 → `curl .../api/v1/rules`
4. 看板时间范围比 `rate()` 窗口短吗 → 5m rate 配 1m 范围显示不出来

**跨环境导入后看板打不开**
检查是不是硬编码了 datasource UID。用 `${datasource}` 模板变量,
`validate.py` 会检出这个。

**指标被重复计数**
同一服务被两种埋点方式同时采集。用 `source` label 排查:
```promql
count by (source) (svc:http_requests:rate5m)
```

**Grafana 13 的 API 废弃提示**
`/api/dashboards/db` 已标记废弃,推荐 Kubernetes 风格的新 API。旧接口仍完全
可用,移除推迟到未来某个大版本,现有 `deploy.sh` 暂时不用改。新建环境如果
直接是 Grafana 13,可以考虑用新接口。

---

## 一句话优先级

装完工具后的最优下一步不是继续装,而是:**用 promtool 给
`normalize-http.yml` 写单元测试并跑通**。那两个 `label_replace` 是四套看板的
地基,到现在一次都没验证过。
