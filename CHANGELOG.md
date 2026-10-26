# @pgbeam/python-sdk

## 0.4.0

### Minor Changes

- 796f4a7: Policy profiles carry `query_mode` (`sql` or `templates`). A profile set to `templates` admits only the project's enabled query templates, and every other rule on the profile still applies to what a template runs. Setting `templates` is refused when the project has no enabled template, and while the organization has a live self-hosted enrollment. On update, an omitted `query_mode` keeps the stored mode. In Terraform, Crossplane and Pulumi, removing `query_mode` from a config plans `sql`, and the plan shows that change.

## 0.3.1

### Patch Changes

- 5dbe64b: `DryEvalResult` gains an optional `template` field: the name of the project query template a statement matched, present only when the policy is templates-only.
- 9ce389d: Honour `Retry-After: 0` and a `Retry-After` date in the past by retrying at once instead of falling back to exponential backoff. A POST or PATCH sent without an `Idempotency-Key` (for example with `RetryConfig(idempotency_keys=False)`) is no longer retried after a read timeout, a 502, a 504 or a 503 without `Retry-After`, since the server may already have made the write; it still retries connect failures, 408, 429 and a 503 that carries `Retry-After`.

  An `idempotency-key` passed in lowercase through the client headers is no longer sent alongside a generated `Idempotency-Key`.

- d651ca6: Query templates can be declared as code: `pgbeam_query_template`, the Crossplane `QueryTemplate` and the Pulumi `QueryTemplate`. Removing `description`, `include_sql`, `enabled` or `params` from a config resets it to the API default (empty, false, true, none) rather than keeping the last value. The query template input's `description` now declares its default (empty) in the contract, which is what the API already stored for an omitted one. Nothing restricts a credential to templates yet: the policy profile setting that does arrives in a later release.

## 0.3.0

### Minor Changes

- 421ec09: Parse RFC 9457 problem documents into `ApiError`. The message now comes from `detail` (then `title`) instead of falling back to the bare status text, and `code`, `type`, `title`, `detail`, `instance`, `request_id` and `errors` are attributes, so callers can tell a 403 `FORBIDDEN` from a 403 `PLAN_LIMIT_REACHED` without reading `body`.
- f363bd7: Add the query templates API: create, list, get, update and delete named, parameterized statements on a project (`/v1/projects/{project_id}/query-templates`, under the Policies tag). A template is checked when it is written and refused with 400 if it is not exactly one SELECT, INSERT, UPDATE or DELETE whose `$n` placeholders match its declared parameters. Nothing restricts a credential to templates yet: the policy profile setting that does arrives in a later release.
- 94466c2: Remove the internal Slack support webhook (`POST /v1/internal/support/slack-event`) from the public SDKs and their docs. It only accepts calls from the dashboard's Slack handler, so `api.internal.handleSlackSupportEvent` (TypeScript), `client.Internal.HandleSlackSupportEvent` and the `SlackEventPayload` type (Go), and `client.internal.handle_slack_support_event` (Python) are gone. This removes public methods, so it would be a breaking change after 1.0; while the SDKs are pre-1.0 it ships as a minor release.

### Patch Changes

- ba058a7: Describe the management MCP endpoint as it behaves: six registered tools, with API operations reached through `call_endpoint`, and the protocol version negotiated at `initialize` rather than pinned.
- 6cd15fe: Stop sending an automatic `Idempotency-Key` on `POST /v1/scan/text`, which the API rejects with 400. Retries stay on for that call, since a scan has no side effects.

## 0.2.12

### Patch Changes

- 14df323: Approval rules can be authored: five operations under `/v1/projects/{project_id}/approval-rules` and `pgbeam approvals rules {list,create,show,update,delete}`.

## 0.2.11

### Patch Changes

- eb77c5f: `listAnomalyAlerts` takes an optional `kind` filter, one of the new `AnomalyKind` enum values.
- 9d6807d: The audit session summary carries `anomalies`: the alerts raised from the session's own entries, and separately the rate and shape alerts on its credentials whose window overlaps it. The field is absent when the caller's role does not hold `anomaly:read`. `pgbeam audit session` prints both lists.
- d92dcdb: Reword five API descriptions that carried em dashes into every generated reference.

## 0.2.10

### Patch Changes

- b821f90: Approval requests carry `approval_rule_name`, the approval rule that held the statement.

## 0.2.9

### Patch Changes

- 16ed7f3: feat(proxy): content_scan_mode=block now blocks, and it does it out loud (roadmap item 7, rung 3)

## 0.2.8

### Patch Changes

- a9c235e: feat(api): anomaly rules, the authoring surface (roadmap item 4, slice 3)

## 0.2.7

### Patch Changes

- e4af35f: Update dependencies

## 0.2.6

### Patch Changes

- 40af2fb: feat(proxy,api): raise an anomaly alert for a high-confidence content-scan finding

## 0.2.5

### Patch Changes

- e3ca897: Update dependencies

## 0.2.4

### Patch Changes

- 631f106: feat(contentscan): a flagged result records a content_flagged audit entry

## 0.2.3

### Patch Changes

- a5fbfca: feat(proxy): scan result content on the wire for agent-directed text

## 0.2.2

### Patch Changes

- 3342c65: feat(policy): content_scan_mode and content_scan_max_bytes on the policy profile

## 0.2.1

### Patch Changes

- f056d55: fix(ci): the guard that checks workflows did not run when workflows changed

## 0.2.0

### Minor Changes

- ea5f407: feat(sdk): a Python SDK, generated from the OpenAPI contract

  `pgbeam` on PyPI: a blocking `PgBeamClient` and an awaitable `AsyncPgBeamClient` over every operation in the public API, with a `TypedDict` per request and response body and a `py.typed` marker, so mypy and pyright check calls against the contract. `models.py`, `operations.py` and `services.py` come out of `pnpm generate`, so the client cannot drift from the spec, and CI fails on a stale one the same way it does for the Go, TypeScript and IaC surfaces. The transport is a port of the TypeScript SDK's, not a second opinion: same retryable statuses, same three bounds, same idempotency keys, and the same two error classes, so a 429 or a 409 means one thing across both clients.
