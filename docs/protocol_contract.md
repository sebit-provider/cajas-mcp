# CAJAS MCP Protocol Contract

## 1. Source Of Truth

The MCP server does not define a new CAJAS data model. It exposes a vendor-neutral protocol layer over existing CAJAS concepts:

```text
orgs = workspace / tenant
coa_profiles
chart_of_accounts / org_chart_of_accounts
raw_entries / raw_entry_lines
raw_groups / raw_group_items
assembly_signatures
accounting_events / event_lines
standards
standard_templates
interpretation_statements
event_standard_links
CWM
```

All tenant checks, role checks, validation, immutable protections, approval workflow, and audit behavior remain in CAJAS FastAPI and database triggers.

## 2. MCP Specification Baseline

Baseline specification: Model Context Protocol `2025-11-25`.

Primary references:

- MCP specification: https://modelcontextprotocol.io/specification/2025-11-25
- Transports: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- Lifecycle: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
- Authorization: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- Resources: https://modelcontextprotocol.io/specification/2025-11-25/server/resources
- Schema: https://modelcontextprotocol.io/specification/2025-11-25/schema
- Official Python SDK: https://github.com/modelcontextprotocol/python-sdk

Important current requirements and design implications:

- MCP uses JSON-RPC.
- Standard transports are `stdio` and Streamable HTTP.
- Streamable HTTP replaces the older HTTP+SSE transport.
- Streamable HTTP requires a single MCP endpoint path supporting HTTP `POST` and `GET`, for example `/mcp`.
- HTTP clients must include `MCP-Protocol-Version` on subsequent requests after initialization.
- Streamable HTTP servers must validate `Origin` when present.
- HTTP auth should follow MCP authorization, OAuth 2.1, RFC 9728 protected resource metadata, and bearer tokens in the `Authorization` header.
- Access tokens must not be placed in query strings.
- Resources may return text or base64 binary blobs.
- Tools should use structured output schemas when possible.
- List operations can use opaque cursor pagination.
- Long-running operations can use progress tokens; cancellation should be handled for in-progress requests where practical.

## 3. Transports

### Primary: Streamable HTTP

Production endpoint:

```text
https://sebit-mcp.com/mcp
```

Rationale:

- Official production transport.
- Works for GPT, Claude, Codex, and other MCP-compatible clients without vendor-specific tool variants.
- Allows Railway deployment behind HTTPS and custom domain.
- Supports remote auth, health checks, logs, and independent scaling.

### Secondary: stdio

Support value:

- Local development.
- Contract tests.
- MCP Inspector and local debugging.

Constraint:

- stdio must not become the production path.
- stdio auth should use environment variables or local dev config, not OAuth HTTP flow.

## 4. MCP Endpoint Contract

Recommended endpoints:

```text
GET/POST /mcp
GET      /health
GET      /ready
GET      /version
GET      /.well-known/oauth-protected-resource
GET      /.well-known/oauth-protected-resource/mcp
```

Notes:

- `/mcp` is the only MCP protocol endpoint.
- `/health` is shallow process health.
- `/ready` checks required configuration and optional CAJAS API reachability.
- `/version` returns server version and CAJAS API compatibility.
- Well-known endpoints are required if OAuth-based MCP authorization is enabled.

Avoid adding non-protocol domain endpoints to the MCP service. Business operations should be MCP tools/resources only.

## 5. Initialization And Capabilities

Server identity:

```json
{
  "name": "cajas-mcp",
  "title": "CAJAS MCP",
  "version": "0.1.0",
  "description": "Vendor-neutral MCP adapter for CAJAS accounting workflows"
}
```

Server capabilities:

```json
{
  "tools": {
    "listChanged": false
  },
  "resources": {
    "listChanged": false
  },
  "prompts": {
    "listChanged": false
  },
  "logging": {}
}
```

Initial version should not advertise MCP `tasks` unless durable background job support is implemented. Use progress notifications for long-running file preview/import where supported by the SDK and client.

## 6. Tool Naming Contract

Tool names are vendor-neutral and domain-stable:

```text
cajas.list_workspaces
cajas.list_profiles
cajas.get_coa
cajas.search_raw_entries
cajas.inspect_raw_file
cajas.preview_raw_import
cajas.import_raw_file
cajas.inspect_coa_file
cajas.preview_coa_import
cajas.import_coa
cajas.recommend_assembly
cajas.explain_assembly_recommendation
cajas.find_criterion_group
cajas.resolve_standard_reference
cajas.propose_criterion_group
cajas.propose_interpretation
```

Do not add model-specific names such as `openai_create_event`, `claude_assembly`, or `gpt_raw_import`.

Verb semantics:

| Verb | Meaning | Mutation |
|---|---|---:|
| `list` | Return a bounded list | no |
| `get` | Return one object/context | no |
| `search` | Query by filters/text | no |
| `inspect` | Analyze input only | no |
| `preview` | Compute likely mutation result | no |
| `recommend` | Non-binding candidate | no |
| `explain` | Explain existing candidate/result | no |
| `resolve` | Identify references/locators | no |
| `propose` | Prepare structured change candidate | no by default |
| `import` | Perform explicit mutation | yes |

## 7. Tool Description Safety Contract

Every tool touching accounting state must include explicit boundaries.

Example:

```text
Analyzes RAW entries and returns non-binding assembly candidates.

This tool does not:
- create an assembly
- modify RAW status
- create an Event
- approve accounting judgment
- sign or finalize anything
```

Mutation-sensitive tools must state:

- whether they write to CAJAS;
- whether they require a prior preview;
- what they cannot approve, sign, finalize, override, or delete;
- that backend authorization remains authoritative.

## 8. Structured-First Output

Tool results should return structured data as the primary output and human-readable explanation as secondary data.

Standard envelope:

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "explanation": "Short human-readable summary",
  "request_id": "req_..."
}
```

For tool execution errors:

```json
{
  "ok": false,
  "error": {
    "code": "COA_MAPPING_REQUIRED",
    "message": "Some rows require account mapping before import.",
    "retryable": false,
    "requires_user_action": true,
    "details": {}
  },
  "request_id": "req_..."
}
```

Protocol errors are reserved for MCP-level failures such as malformed JSON-RPC, unknown tool, incompatible protocol version, or transport failure. CAJAS domain errors should be returned as tool execution errors so clients/models can self-correct.

## 9. Level Metadata

Do not require the model to memorize L1/L2/L3.

Canonical representation:

```json
{
  "level": {
    "code": "L1",
    "meaning": "EXTERNAL_STANDARD"
  }
}
```

Level meanings:

| Code | Meaning |
---|---|
| `L1` | `EXTERNAL_STANDARD` |
| `L2` | `INTERNAL_POLICY` |
| `L3` | `TEMPORARY_OR_SUBJECTIVE` |

Criterion Group level and Interpretation level are independent fields:

```json
{
  "criterion_group_level": {
    "code": "L1",
    "meaning": "EXTERNAL_STANDARD"
  },
  "interpretation_level": {
    "code": "L2",
    "meaning": "INTERNAL_POLICY"
  }
}
```

## 10. Criterion Name Provenance

CAJAS L1 criterion names must not be presented as official IFRS/GAAP headings unless that is verified and licensed.

Provenance enum:

| Value | Meaning |
---|---|
| `CAJAS_AUTHORED` | Name/description written by CAJAS |
| `USER_AUTHORED` | Name/description supplied by user |
| `INTERNAL_POLICY` | Internal policy label |
| `OFFICIAL_LICENSED` | Official source text or heading with verified right to store/use |
| `UNKNOWN` | Legacy or unresolved provenance |

Recommended L1 group shape:

```json
{
  "framework": "IFRS",
  "code": "IFRS 15.22-30",
  "name": "계약 내 수행 항목 식별",
  "name_origin": "CAJAS_AUTHORED",
  "description_origin": "CAJAS_AUTHORED",
  "official_text_included": false,
  "official_heading_included": false,
  "level": {
    "code": "L1",
    "meaning": "EXTERNAL_STANDARD"
  }
}
```

## 11. Standard Reference Resolver Contract

`cajas.resolve_standard_reference` identifies external standard locators. It does not store IFRS/GAAP text.

Output:

```json
{
  "framework": "IFRS",
  "reference_code": "IFRS 15.22-30",
  "confidence": 0.88,
  "source_url": "https://...",
  "official_text_included": false,
  "official_heading_included": false,
  "suggested_cajas_name": "계약 내 수행 항목 식별",
  "suggested_cajas_description": "CAJAS-authored short summary.",
  "requires_review": true
}
```

Forbidden:

- copying IFRS/GAAP full text into CAJAS;
- automatically cataloging official headings as CAJAS titles;
- using external community content as accounting standard authority.

## 12. Authentication Contract

### Recommended Production Pattern

Use OAuth-based MCP authentication for the public remote service, with CAJAS MCP as an OAuth protected resource. The MCP server validates tokens issued for `https://sebit-mcp.com/mcp`, then obtains or maps to a CAJAS API access token/session through a CAJAS-supported mechanism.

This avoids raw token passthrough problems in the MCP authorization spec.

### Transitional Pattern

For private beta, bearer token forwarding can be supported only if:

- the token is a CAJAS API token intended for CAJAS API;
- the MCP service validates the token by calling CAJAS auth endpoints before any tool execution;
- tokens are never logged;
- the pattern is documented as beta-only until a proper OAuth resource-server flow exists.

### Patterns Compared

| Pattern | Pros | Cons | Recommendation |
|---|---|---|---|
| Bearer token forwarding | Simple, works with existing CAJAS auth | MCP spec warns against token passthrough/confused deputy if audience is wrong | beta only |
| OAuth-based MCP auth | Spec-aligned, remote-client friendly, supports scopes | Requires authorization metadata and token validation | production target |
| MCP-specific API token mapping | Easy for CLI/server clients | Weaker UX, token lifecycle burden | optional service integration path |
| Service account delegation | Easy backend integration | Breaks user authority boundary unless carefully delegated | avoid for user data tools |

### Required Context

Each CAJAS API call must carry:

```text
Authorization: Bearer <CAJAS-compatible access token>
x-org-id: <workspace/org id>
x-request-id: <generated request id>
```

The CAJAS backend remains responsible for validating membership and role.

## 13. Error Contract

Domain error envelope:

```json
{
  "error": {
    "code": "CAJAS_PERMISSION_DENIED",
    "message": "The user cannot import CoA for this workspace.",
    "retryable": false,
    "requires_user_action": true,
    "details": {
      "required_permission": "admin"
    }
  }
}
```

Categories:

| Code | Meaning |
|---|---|
| `AUTH_REQUIRED` | No usable identity |
| `PERMISSION_DENIED` | Authenticated but not allowed |
| `ORG_NOT_FOUND` | Workspace unavailable or inaccessible |
| `RESOURCE_NOT_FOUND` | Object not found in accessible tenant |
| `INVALID_INPUT` | Schema/domain input invalid |
| `INVALID_FILE` | File unreadable or unsupported |
| `FILE_TOO_LARGE` | Size limit exceeded |
| `COA_CONFLICT` | CoA profile/code conflict |
| `COA_MAPPING_REQUIRED` | Account mapping unresolved |
| `IMPORT_PREVIEW_REQUIRED` | Import attempted without preview |
| `IMPORT_UNRESOLVED` | Preview still contains unresolved rows |
| `ASSEMBLY_CONFLICT` | RAW entries cannot be grouped as requested |
| `IMMUTABLE_OBJECT` | Object is confirmed/signed/immutable |
| `EXTERNAL_PROVIDER_UNAVAILABLE` | External context provider unavailable |
| `RATE_LIMITED` | CAJAS or external provider rate limit |
| `CAJAS_API_UNAVAILABLE` | Upstream CAJAS API unavailable |
| `INTERNAL_ERROR` | Unexpected MCP server error |

Retry policy:

- Auth, permission, immutable, unresolved mapping: not retryable without user action.
- CAJAS API 429/503 and external provider 429/503: retryable with backoff.
- File validation errors: not retryable unless input changes.

## 14. Mutation Boundary

Allowed by MCP:

```text
READ
SEARCH
INSPECT
ANALYZE
PREVIEW
RECOMMEND
PROPOSE
PREPARE
```

Not exposed by MCP:

```text
FINAL ACCOUNTING APPROVAL
SIGNATURE
FINALIZE ASSEMBLY
CONFIRM EVENT
OVERRIDE GOVERNANCE
DELETE CONFIRMED EVENT
MODIFY IMMUTABLE HISTORY
```

Even if CAJAS backend has endpoints for signing, confirming, finalizing, approval, or deletion, the public MCP catalog must not expose them.

## 15. Observability Contract

Log fields:

```json
{
  "request_id": "...",
  "mcp_session_id": "...",
  "tool_name": "cajas.preview_raw_import",
  "duration_ms": 1234,
  "status": "ok",
  "org_id": "org_...",
  "user_id_hash": "sha256:...",
  "cajas_api_status": 200,
  "external_provider": "stack_exchange",
  "external_latency_ms": 220
}
```

Do not log:

- raw accounting descriptions;
- file contents;
- customer names;
- bearer tokens;
- Supabase keys;
- external provider secrets;
- full prompt or model output.

