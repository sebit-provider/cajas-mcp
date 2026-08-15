# CAJAS MCP

Vendor-neutral MCP adapter for CAJAS accounting workflows.

This implementation is a thin adapter over the authenticated CAJAS API:

```text
MCP Client
  -> CAJAS MCP Server
  -> CAJAS FastAPI
  -> backend/supabase_admin.py
  -> Supabase
```

## Design Documents

- [Protocol Contract](docs/protocol_contract.md)
- [Deployment and Repository Design](docs/deployment_and_repository.md)
- [Tool Catalog](docs/tool_catalog.md)
- [Resource Catalog](docs/resource_catalog.md)
- [Release Checklist](docs/release_checklist.md)

## Implemented In This Phase

- Streamable HTTP MCP skeleton at `/mcp`.
- Local stdio entrypoint.
- `/health`, `/ready`, `/version`.
- CAJAS API HTTP client with bearer forwarding, `x-org-id`, request IDs, read retries, and error normalization.
- Read-only tools:
  - `cajas.list_workspaces`
  - `cajas.search_raw_entries`
  - `cajas.search_events`
  - `cajas.get_event`
- RAW file import pipeline:
  - `cajas.inspect_raw_file`
  - `cajas.preview_raw_import`
  - `cajas.import_raw_file`
- CoA profile import pipeline:
  - `cajas.inspect_coa_file`
  - `cajas.preview_coa_import`
  - `cajas.import_coa`
- Criterion and Interpretation workflow:
  - `cajas.find_criterion_group`
  - `cajas.resolve_standard_reference`
  - `cajas.propose_criterion_group`
  - `cajas.find_interpretations`
  - `cajas.propose_interpretation`
- Resource:
  - `cajas://capabilities`
- Assembly Recommendation PoC:
  - deterministic weighted signals;
  - pairwise threshold grouping;
  - organization-local historical Assembly pattern support;
  - governance-aware historical support quality;
  - existing human Assembly comparison for already assembled RAW;
  - optional user-requested Stack Exchange community validation;
  - non-binding output with `mutation=false`.

## Assembly Recommendation Boundary

CAJAS MCP can analyze RAW accounting entries and suggest explainable Assembly candidates using:

- RAW structural similarity;
- organization-specific historical Assembly patterns weighted by governance quality;
- optional external operational context.

Recommendations are non-binding. They do not determine accounting treatment and never finalize accounting judgment.

Historical patterns are supporting observations, not accounting rules or mandatory grouping rules.

When input RAW entries already belong to an Assembly, `cajas.recommend_assembly` may return an
`existing_judgment_comparison` with `AGREEMENT`, `SUGGESTED_SPLIT`, `SUGGESTED_MERGE`, or
`PARTIAL_OVERLAP`. Differences between an existing human Assembly and an MCP recommendation are review
signals only. CAJAS MCP does not split, merge, void, or modify existing Assembly/Event records.

### Community Validation

`cajas.recommend_assembly` can optionally validate an Assembly recommendation against public Stack Exchange discussions:

```json
{
  "community_validation": {
    "enabled": true,
    "mode": "BALANCED"
  }
}
```

Supported modes are `SUPPORT`, `CHALLENGE`, and `BALANCED`. The default is `BALANCED` when validation is enabled.

Community validation is opt-in only. Low internal confidence does not automatically call Stack Exchange. The validation result is returned as an independent `community_validation` block and does not change the internal recommendation score.

Stack Exchange content is public operational context, not accounting authority. CAJAS MCP treats all community content as `UNTRUSTED_EXTERNAL_DATA`; it never uses community results to create standards, determine accounting treatment, approve, sign, finalize, split, merge, or mutate Assembly/Event records.

The Stack Exchange API key is server-side only:

```text
STACKEXCHANGE_ENABLED=true
STACKEXCHANGE_KEY=
STACKEXCHANGE_SITE=stackoverflow
```

No Stack Exchange user login is required. Provider failures, rate limits, or disabled configuration degrade gracefully and do not fail the core Assembly recommendation.

## RAW File Import

CAJAS MCP supports a composable RAW import flow for synthetic or user-provided CSV/XLSX accounting data:

1. Inspect a CSV/XLSX file with `cajas.inspect_raw_file`.
2. Review sheet structure, warnings, and inferred Smart Excel column mapping.
3. Preview the import with `cajas.preview_raw_import` against a selected `profile_id`.
4. Resolve unresolved CoA or mapping errors in the preview result.
5. Import only a successful preview with `cajas.import_raw_file`.
6. Use the returned RAW IDs with `cajas.recommend_assembly`.

`inspect` and `preview` are non-mutating. `import` creates RAW entries/groups through the authenticated CAJAS Smart Excel API, but it does not create Events, approve, sign, finalize, or alter immutable history.

Supported file types are `.csv` and `.xlsx`. Macro-enabled workbooks, legacy `.xls`, PDFs, ZIP files, and unknown binaries are rejected. Formulas are never executed.

When RAW preview reports unresolved CoA accounts, CAJAS MCP keeps account creation separate:

1. Inspect a CoA CSV/XLSX file with `cajas.inspect_coa_file`.
2. Preview it against a specific `profile_id` with `cajas.preview_coa_import`.
3. Review `ADD`, `UPDATE_METADATA`, `CONFLICT`, `BLOCKED`, and `DEACTIVATE_CANDIDATE` operations.
4. Apply only explicit accepted operation IDs with `cajas.import_coa`.
5. Rerun `cajas.preview_raw_import` for the RAW file.

CoA import is profile-scoped and merge-oriented. It does not replace the whole CoA, infer account-code renames, deactivate accounts missing from the file, or auto-create accounts during RAW import.

## Criterion and Interpretation Exploration

CAJAS MCP supports a non-mutating standards workflow:

1. Search existing CAJAS criterion groups with `cajas.find_criterion_group`.
2. Resolve an external standard locator with `cajas.resolve_standard_reference` when no reusable group exists.
3. Generate a CAJAS-authored criterion proposal with `cajas.propose_criterion_group`.
4. Search reusable interpretations under that group with `cajas.find_interpretations`.
5. Propose a new interpretation with `cajas.propose_interpretation` only when reuse is not appropriate.

Reference resolution identifies locators such as `IFRS 15.22-30` or `IAS 36.9-14`. It does not return or store full IFRS/GAAP text, does not copy official headings into CAJAS titles, and does not create standards, templates, event links, approvals, or confirmations.

## Production Authentication

CAJAS MCP uses the existing CAJAS identity boundary. It does not create MCP-specific user accounts and it does not access Supabase directly.

Remote MCP data access requires a bearer token for the actual CAJAS user. MCP forwards that token to the authenticated CAJAS API, where `/api/auth/me`, `org_memberships`, `require_org_user`, and the existing role checks remain the source of truth.

For production, do not configure a shared Railway token:

```text
CAJAS_MCP_ENV=production
CAJAS_API_BEARER_TOKEN=
```

If `CAJAS_MCP_ENV=production` and `CAJAS_API_BEARER_TOKEN` is set, the server refuses to start. `CAJAS_API_BEARER_TOKEN` is only for local development or smoke tests.

The HTTP MCP endpoint can run as an OAuth protected resource:

```text
CAJAS_MCP_AUTH_ENABLED=true
CAJAS_MCP_AUTH_RESOURCE_URL=https://sebit-mcp.com/mcp
CAJAS_MCP_AUTH_ISSUER_URL=https://your-cajas-auth.example
CAJAS_MCP_OAUTH_SCOPES_SUPPORTED=cajas:read,cajas:raw:write,cajas:coa:write,cajas:criterion:read
```

When enabled, unauthenticated `/mcp` requests receive `401` with `WWW-Authenticate` and protected-resource metadata. Presented access tokens are validated against CAJAS `/api/auth/me`, then forwarded per request to the CAJAS API. OAuth scopes only describe broad request categories; CAJAS workspace roles still decide whether a read or mutation is allowed.

Workspace selection remains explicit. `cajas.list_workspaces` works without an `org_id`; workspace-scoped tools require `org_id`, which is forwarded as `x-org-id` and verified by CAJAS backend membership checks.

RAW and CoA import preview sessions are process-local and bound to the bearer token, organization, and profile context. A preview ID created by one token cannot be replayed by another token.

## Planned

- Human-approved Criterion/Interpretation creation and Event linkage.
- CAJAS authorization-code login facade if a dedicated OAuth authorization server is required.

## Non-Goals

- No direct Supabase access from MCP.
- No CAJAS domain model redefinition.
- No GPT/Claude/vendor-specific tool branches.
- No approval, signature, finalization, governance override, or immutable history mutation tools.
- No IFRS/GAAP full-text catalog or automatic official heading replication.
- No trusted execution of external community/web content.

## Local Development

```text
pip install -e .
set CAJAS_API_BASE_URL=https://your-cajas-api.example
uvicorn cajas_mcp.app:app --host 127.0.0.1 --port 8000
```

Connect an MCP client to:

```text
http://127.0.0.1:8000/mcp
```

For stdio:

```text
set CAJAS_MCP_TRANSPORT=stdio
cajas-mcp
```
