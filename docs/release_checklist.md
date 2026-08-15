# CAJAS MCP Public Release Checklist

## 1. Secrets And Sensitive Data

Before public GitHub release, verify the repository does not include:

- Supabase service role key.
- Production JWT.
- CAJAS database credentials.
- Railway tokens.
- Stack Exchange secret.
- Customer data.
- Private CAJAS source code.
- Private schema dump.
- Internal production hostnames not intended for publication.
- `.env` files.
- Local logs.
- Test files containing real accounting data.

Use secret scanning before first push.

## 2. Required Public Files

- `README.md`
- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `.env.example`
- `.gitignore`
- `pyproject.toml`
- `Dockerfile`
- `railway.toml`

## 3. README Required Sections

- What is CAJAS MCP?
- Architecture.
- Supported capabilities.
- What CAJAS MCP intentionally cannot do.
- Installation.
- Local development.
- Remote deployment.
- Configuration.
- Authentication.
- Connecting from MCP clients.
- Example tool calls.
- Security model.
- Accounting judgment boundary.
- License.
- Contributing.

Client examples should be vendor-neutral first. ChatGPT, Claude, Codex, and generic MCP examples can be separate subsections.

## 4. SECURITY.md Plan

Include:

- vulnerability reporting process;
- placeholder reporting email/address if no official address is confirmed;
- secret exposure policy;
- auth bypass policy;
- tenant isolation risk;
- MCP tool escalation risk;
- prompt injection risk;
- malicious file risk;
- SSRF risk;
- immutable accounting record mutation risk;
- expected response timeline placeholder.

Do not invent a real report email if CAJAS/SEBIT has not confirmed one.

## 5. Automated Tests

Minimum test suite:

- protocol contract tests;
- tool schema tests;
- CAJAS API client tests;
- auth tests;
- tenant isolation tests;
- permission tests;
- file parser tests;
- malicious file tests;
- assembly recommendation tests;
- external prompt injection tests;
- criterion provenance tests;
- immutable mutation rejection tests;
- Streamable HTTP smoke test;
- stdio dev smoke test;
- ChatGPT-compatible remote MCP smoke test;
- Claude-compatible remote MCP smoke test.

Do not unit test proprietary model response quality. Test protocol behavior and structured outputs.

## 6. CI Plan

GitHub Actions:

```text
lint
type check
unit tests
security checks
package build
Docker build
```

No production deploy secrets hard-coded in GitHub Actions.

Railway production deploy should use Railway GitHub integration and Railway environment variables.

## 7. Implementation Order

### Phase 0: Protocol Skeleton

- Public repo scaffold.
- FastMCP/ASGI skeleton.
- `/mcp`, `/health`, `/ready`, `/version`.
- capabilities resource.
- no CAJAS mutations.

### Phase 1: Read-Only CAJAS Tools/Resources

- `CajasClient`.
- workspace/profile/CoA/raw/event/standard/CWM read tools.
- judgment context resource.
- auth bridge.

### Phase 2: RAW File Import

- file adapter.
- CSV/XLSX validation.
- inspect/preview/import raw tools.
- existing Smart Import API reuse.

### Phase 3: CoA Import Preview/Import

- CoA inspect.
- new CAJAS API dry-run service required.
- approved import through existing CoA upload service.

### Phase 4: Assembly Recommendation + Stack Exchange

- deterministic recommendation service.
- historical CAJAS similarity.
- Stack Exchange provider through external context abstraction.
- untrusted content sanitizer.

Status: partially implemented. Historical Assembly context is organization-local and read-only through CAJAS API. Stack Exchange remains optional.

### Phase 5: Criterion Reference/Interpretation Proposal

- standard reference resolver.
- criterion provenance.
- group/template reuse proposal.
- no official text catalog.

### Phase 6: Public Railway Deployment + `sebit-mcp.com`

- Dockerfile.
- Railway config.
- custom domain.
- OAuth protected resource metadata.
- observability and health checks.

### Phase 7: GitHub Public Release

- docs complete.
- security review.
- license finalized.
- secret scan clean.
- CI green.

## DECISIONS REQUIRED BEFORE IMPLEMENTATION

1. Production auth target: full OAuth protected-resource flow first, or beta bearer-forwarding first.
2. Public domain shape: `https://sebit-mcp.com/mcp` now, or subdomain from day one.
3. CoA import default: create a new UPLOAD_ERP profile/version by default, or allow merging into an existing profile after preview.
4. Whether MCP may create an assembly session after recommendation, or only return recommendation/proposal payloads.
5. Whether external context search result summaries are persisted in CAJAS audit/recommendation history, or kept ephemeral with only source URLs logged.
6. Official vulnerability reporting contact for `SECURITY.md`.
7. License final choice: recommended Apache-2.0, but owner approval required.
