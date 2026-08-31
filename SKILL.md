---
name: grafana-central-templates
description: Build, validate, and deploy Grafana dashboards that follow this organization's central template conventions — Git as source of truth, recording-rule normalization, folder policy, and the CI deploy contract. Use this skill whenever the user mentions dashboards, Grafana, PromQL, Prometheus, monitoring, observability, SLI/SLO, golden signals, RED/USE, DORA metrics, or wants to visualize metric data — even if they never say "Grafana". Also use it when reviewing dashboard JSON before a merge request, or when a panel shows "No data". This skill covers organizational conventions only; for general Grafana and PromQL knowledge, defer to the official grafana-core skills.
---

# Central Grafana Templates

Organizational conventions for dashboards that live in Git and deploy through CI.

## Scope: what this skill is and is not

This skill deliberately does **not** teach Grafana or PromQL. Grafana maintains
official skills for that, and they track product versions in a way a local copy
cannot:

```bash
claude plugin marketplace add grafana/skills
claude plugin install grafana-core@grafana-skills
```

`grafana-core` covers `dashboarding` (panels, variables, transformations,
thresholds), `promql` (writing, validating, optimizing queries), `alerting-irm`,
and `opentelemetry`. Use those for anything general.

This skill covers only what is specific to this organization and therefore cannot
come from upstream:

- Git as the source of truth, and the deploy contract that enforces it
- Recording-rule normalization across mixed instrumentation
- Folder policy, uid naming, and the `__SVC_LABEL__` placeholder mechanism
- A validator that checks these conventions

When the two conflict, the official skill wins on Grafana behavior; this skill
wins on where files live and how they ship.

## Start from the skeleton, not from scratch

Copy `assets/skeleton.json` and modify it. Do not generate dashboard JSON from
nothing.

Models write PromQL well and Grafana layout JSON badly — panel geometry,
`fieldConfig` nesting, and variable wiring are easy to get subtly wrong in ways
that load but look broken. The skeleton already encodes the conventions below,
so copying it costs fewer tokens and produces a better result.

Editing an existing dashboard follows the same principle: change what needs
changing, leave the rest byte-identical.

## Workflow

### 1. Establish the service label

Every query depends on which label identifies a service, and it varies by
organization: `job`, `service_name`, `app`, `application`.

```bash
curl -s 'http://<prom>/api/v1/series?match[]=<metric>' | jq '.data[0] | keys'
```

Never guess it. `references/conventions.md` explains the `__SVC_LABEL__`
placeholder that keeps this unknown confined to one place.

### 2. Normalize before visualizing

When metrics arrive from more than one source — OTel and Micrometer, say — write
recording rules mapping all sources to one canonical name, and have dashboards
query only canonical names. Do not spread `or` clauses through every panel.

The argument is maintenance: with recording rules, a fourth instrumentation style
means editing one file. Without them, it means editing every panel of every
dashboard.

Rules deploy **before** dashboards. A dashboard whose rules have not evaluated
yet shows "No data", and the resulting bug report costs more than sequencing the
deploy correctly.

### 3. Build panels

Follow the official `dashboarding` skill for panel construction. The conventions
this organization adds on top — grid widths, panel id ranges, uid naming, the
central-folder title prefix — are in `references/conventions.md`.

### 4. Validate before review

```bash
python3 scripts/validate.py dashboards/*.json --svc-label job
```

Standard library only, no `jq` dependency. It catches what JSON review misses:
overlapping panels, duplicate ids, hardcoded datasource UIDs, unresolved
placeholders, `percent` where `percentunit` was meant, and thresholds configured
in ways that silently do nothing.

Errors block; warnings are judgment calls. Run it before showing a dashboard to
anyone — it is far cheaper than a review round trip.

### 5. Deploy

Validate on every MR, auto-deploy to staging on merge, manual gate for
production. Dashboards have a wide blast radius and a manual click before
production is cheap insurance. Contract details in `references/conventions.md`.

## Working with existing dashboards over MCP

Real dashboard JSON easily exceeds 100KB, which swamps the context window and
leaves no room to think. Use the narrowest tool available:

| Need | Use |
|---|---|
| What's on this dashboard? | `get_dashboard_summary` |
| One specific piece | `get_dashboard_property` with JSONPath |
| Full JSON | `get_dashboard_by_uid` — last resort |
| Small edit | `update_dashboard` with patch operations |

Writing requires `dashboards:create` and `dashboards:write` plus folder scope.
Check this before building, not after.

## Debugging "No data"

Work outward from the raw metric rather than inward from the panel:

1. Does the bare metric name return anything? → if not, it is an instrumentation
   or scrape problem, not a dashboard problem
2. Does it return data with label filters removed? → if yes, the label is wrong
3. Does the recording rule exist and evaluate? → check `/api/v1/rules`
4. Is the dashboard time range shorter than the `rate()` window? → nothing renders

Resist rewriting the query. The query is usually right and the assumption
underneath it is usually wrong.

## Conventions worth stating up front

**Ratios need a clamped denominator and an absolute companion.** A service at
100% error rate serving 0.02 requests/sec is a health check on a scaled-to-zero
deployment, not an incident. The ratio alone cannot express that, and readers
will page someone over it.

**Never hardcode a datasource UID.** They differ between environments. Declare a
`datasource` template variable and reference `${datasource}` everywhere.

**Strip `id` and `version` at deploy time.** They are per-instance; leaving them
in can overwrite an unrelated dashboard holding that numeric id.

**Delete panels you cannot justify.** A dashboard exists so someone can answer a
question during an incident. If you cannot name the question a panel answers,
it is noise competing with the panels that matter.

## Related official skills

Beyond `grafana-core`, two from `grafana-cloud` apply directly to mixed OTel and
Micrometer environments, where label cardinality tends to grow unnoticed:

- `prometheus-label-strategy` — auditing and designing label schemas
- `prometheus-cardinality-troubleshooter` — diagnosing live cardinality problems

For alerting, use `alerting-irm`. Alerts belong in a separate repository from
dashboards: the two have different lifecycles and reviewers, and combining them
means every alert threshold change drags a dashboard review along with it.
