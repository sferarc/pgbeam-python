# @pgbeam/python-sdk

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
