# Conventions

Organization-specific policy. These are choices, not laws of physics — adapt the
values to the environment, but keep the shapes.

## Contents

- [Source of truth](#source-of-truth)
- [Folder policy](#folder-policy)
- [Naming](#naming)
- [The service label problem](#the-service-label-problem)
- [Portability across environments](#portability-across-environments)
- [Deploy contract](#deploy-contract)
- [Permissions](#permissions)
- [Adoption](#adoption)
- [Relationship to the official Grafana skills](#relationship-to-the-official-grafana-skills)

---

## Source of truth

Dashboard JSON lives in Git. CI deploys it. Nobody edits central dashboards in
the Grafana UI.

This constraint exists because the alternative degrades predictably: someone
tweaks a panel in the UI, someone else exports it, a third person imports it into
a different folder, and within a quarter there are a dozen divergent copies and no
way to fix them all at once.

The cost is real, though — editing in the UI is genuinely more pleasant than
editing JSON. Without a path back into Git, people route around the process.
Provide one: copy the central dashboard in the UI, edit the copy, export the JSON,
open an MR. Low friction beats strict policy.

## Folder policy

| Folder | Owner | Editable in UI | Deployed by |
|---|---|---|---|
| `Central Templates` | platform team | no (`editable: false`) | CI |
| team folders | each team | yes | whoever |

Central owns the golden signals. Business-specific panels belong to teams.

Do not try to make central templates cover everything. A template that almost fits
gets forked, and a fork never receives updates. A template that covers the common
80% and stays out of the way gets referenced instead of copied.

Library panels are the middle ground: a shared panel definition that teams embed
in their own dashboards. Changing it centrally updates every consumer. Good for
the handful of panels every service should show identically.

## Naming

**Dashboard uid**: `central-<domain>` — `central-app-golden`, `central-cicd-dora`,
`central-jvm-runtime`, `central-infra`.

The uid is the stable identity across environments and the target of every
deep link. Never change one after release; deep links elsewhere will break
silently.

**Title**: prefix central dashboards with a marker (`【中心】`, `[Central]`) so
they are distinguishable in search results, where folder context is not visible.

**Panel id**: unique within a dashboard. Convention: stat panels `1–9`, row panels
`100+`, content panels `10+`. Gaps are fine and leave room to insert.

**Tags**: at minimum `central` plus the domain. Tags are how people find
dashboards once there are more than about thirty.

## The service label problem

Every query depends on knowing which label identifies a service, and it differs
by organization: `job`, `service_name`, `app`, `application`, `kubernetes_name`.

The approach: put `__SVC_LABEL__` in the source files as a placeholder, and have
the deploy script substitute the real value from a CI variable. This keeps the
unknown in exactly one place instead of scattered through every query.

Where possible, avoid the problem entirely — have recording rules emit a
canonical `service` label, then dashboards never reference the raw label at all.
Only dashboards that query raw metrics (JVM, infrastructure) need the placeholder.

Verification, before assuming anything:

```bash
curl -s 'http://<prom>/api/v1/series?match[]=<metric>' | jq '.data[0] | keys'
```

## Portability across environments

Three things break a dashboard when moved between staging and production:

**Datasource UIDs differ.** Declare a `datasource` template variable and
reference `${datasource}` in every panel and every target. Never hardcode a UID.

```json
{
  "type": "datasource",
  "name": "datasource",
  "label": "Data source",
  "query": "prometheus",
  "current": {},
  "refresh": 1
}
```

**`id` and `version` are per-instance.** Strip both at deploy time. Leaving them
in causes version conflicts and, worse, can overwrite an unrelated dashboard that
happens to hold that numeric id.

**`__inputs` and `__requires`** appear when a dashboard is exported "for sharing".
They turn the JSON into an import template that the API rejects. Strip them too.

## Deploy contract

`scripts/` in the dashboard repository (not this skill) holds `deploy.sh`. Its
contract:

| Variable | Purpose |
|---|---|
| `GRAFANA_URL` | required |
| `GRAFANA_TOKEN` | required unless `DRY_RUN=1` |
| `GRAFANA_FOLDER` | target folder, created if absent |
| `SVC_LABEL` | substituted for `__SVC_LABEL__` |
| `DRY_RUN` | `1` validates without pushing |

What it does, in order: check dependencies, resolve or create the folder, strip
`id`/`version`/`__inputs`/`__requires`, set `editable: false`, substitute
placeholders, fail on any placeholder that remains, POST to
`/api/dashboards/db` with `overwrite: true`.

Pipeline shape: validate on every MR, auto-deploy to staging on merge, manual
gate for production. Dashboards have a wide blast radius and a manual click
before production is cheap insurance.

Recording rules deploy alongside — and **before** — dashboards. A dashboard whose
rules have not evaluated yet shows "No data", and the resulting bug report costs
more than sequencing the deploy correctly.

## Permissions

The MCP server and the deploy pipeline authenticate as a Grafana service account,
never a personal token — personal tokens break when someone changes roles or
leaves.

| Operation | Required |
|---|---|
| Read dashboards | `dashboards:read` |
| Create | `dashboards:create` |
| Update | `dashboards:write` |
| Manage folders | `folders:read`, `folders:write` |

The Editor built-in role covers all of this and is a reasonable shortcut when
fine-grained scopes are more trouble than they are worth. Scope it to the central
folder so a mistake cannot damage team dashboards.

For exploratory MCP use, a read-only token is usually enough and much safer.
Escalate to write only when actually deploying.

## Adoption

Emit an adoption marker from the CI/CD template:

```
platform_template_adopted{project="...", template_version="1.4.0"} 1
```

This one metric answers the question that justifies the whole platform: do
projects using the templates deliver better than projects that do not? Comparing
adopted against non-adopted on the same chart is far more convincing than a
total-volume trend, which confounds platform impact with everything else that
changed.

Start emitting it before it is needed. Baseline data cannot be reconstructed
retroactively, and the question always arrives sooner than expected.

## Relationship to the official Grafana skills

Grafana maintains official Agent Skills at `grafana/skills` (Apache-2.0), grouped
into plugins. Install with:

```bash
claude plugin marketplace add grafana/skills
claude plugin install grafana-core@grafana-skills
```

Division of labour:

| Question | Source |
|---|---|
| How do Grafana panels, variables, transformations work? | official `dashboarding` |
| How do I write or optimize this PromQL? | official `promql` |
| How do alert rules and SLOs work? | official `alerting-irm` |
| Where does this file live and how does it ship? | this skill |
| Which folder, which uid, which label? | this skill |
| Is this dashboard ready to merge? | `scripts/validate.py` |

Do not copy upstream material into this repository. Duplicated guidance drifts
out of sync with the product and creates disagreements nobody can adjudicate.
Link to the official skill instead.
