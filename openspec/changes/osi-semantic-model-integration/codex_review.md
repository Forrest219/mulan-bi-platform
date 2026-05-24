## Codex Architectural Assessment

### On Persistence Strategy

Gemini's P1 concern is valid. The proposed filesystem + Git approach is not architecturally sound as the production persistence strategy for Mulan.

The reason is not that YAML is a bad semantic model format. YAML is appropriate as the OSI interchange format and as a reviewable artifact. The issue is making files under `backend/semantic_models/` the runtime source of truth for mutable business semantics.

Mulan's current architecture is PostgreSQL-centered for persistent business state:

- `docs/ARCHITECTURE.md` §7 defines PostgreSQL 16 as the persistence layer, with JSONB as the normal pattern for structured metadata.
- Existing semantic, Tableau, metrics, governance, and LLM state all persist through PostgreSQL and Alembic-managed schemas.
- Production runs multiple Gunicorn/Uvicorn workers plus Celery workers. A local filesystem source of truth creates consistency, deployment, and reload problems across processes and instances.
- The existing semantic lifecycle includes review, approval, publish logs, rollback, sensitivity filtering, and audit history. Those workflows need transactional writes and queryable metadata, not ad hoc file writes.

Filesystem + Git is acceptable for development fixtures, bootstrap seed models, examples, and optional GitOps import/export. It is not a good default for production writes because:

- Containers are commonly immutable or ephemeral; app workers should not be required to write to the deployed code directory.
- Concurrent writes from API workers or Celery workers would require external locking beyond the design.
- Git pull/webhook/NFS synchronization is outside the documented production architecture.
- Per-tenant isolation is awkward in files but natural in PostgreSQL.
- RBAC, approval state, audit logs, rollback, active-version selection, and validation status are all database-shaped concerns.
- Backup/restore and disaster recovery would split across PostgreSQL and Git/NFS instead of using the platform's primary persistence boundary.

PostgreSQL BLOB alone is also not the best recommendation. A raw BLOB or opaque text column preserves YAML but loses most of the value Mulan needs from a governed semantic layer. The better design is a dedicated PostgreSQL-backed semantic model store that keeps the canonical OSI document plus extracted/queryable metadata.

Recommended shape:

- `bi_osi_semantic_models`
  - `id`, `tenant_id`, `name`, `osi_schema_version`, `status`
  - `yaml_content` as `TEXT`, not binary BLOB
  - `parsed_json` as `JSONB` for validated document structure and selective querying
  - `content_hash`, `active_version_id`, `created_by`, `updated_by`, timestamps
  - validation fields such as `validation_status`, `validation_errors_json`
- `bi_osi_semantic_model_versions`
  - immutable version snapshots with `yaml_content`, `parsed_json`, `content_hash`, `change_reason`, `created_by`, `created_at`
- Optional extraction/index tables later, only where justified:
  - metric index, dataset index, field index, alias/search index

This keeps OSI YAML intact as the import/export contract while aligning production persistence with Mulan's architecture.

### On ContextAssembler Centralization

Gemini's P2 concern is also real, though it is not the same severity as persistence.

The design currently says `NLQService` receives `ContextAssembler`, then the sample code directly calls `self.osi_parser.parse(settings.OSI_YAML_PATH)` for filters. That is a design smell for three reasons:

- It leaks storage and parsing concerns into the NLQ layer.
- It creates two context paths: `ContextAssembler` for `ai_context`, and ad hoc OSI parsing for filters.
- It bypasses the existing `docs/ARCHITECTURE.md` §6 context assembly contract, including token budgeting, field prioritization, and LLM safety filtering patterns already present in `semantic_maintenance/context_assembler.py`.

For P0, the direct parser dependency could be tolerated only as a short-lived spike if the implementation is explicitly marked temporary and hidden behind an interface. However, I would not approve it as the P0 target design because the fix is small and prevents a bad dependency from becoming the integration pattern.

The better P0 boundary is:

- `osi_parser` parses and validates OSI documents only.
- A repository/provider layer loads the active OSI model from the selected persistence backend.
- `ContextAssembler` or a closely named semantic context service exposes LLM-ready context:
  - `get_ai_context(model_name)`
  - `get_metric_filters(model_name, dialect)`
  - `build_nlq_semantic_context(model_name, dialect)` returning instructions, required filters, field context, and token-budgeted prompt blocks.
- `NLQService` consumes that assembled context and does not know whether it came from YAML files, PostgreSQL, cache, or future UI edits.

If the existing `ContextAssembler` is too tied to Tableau field context, create a narrow `SemanticContextProvider` or `OSISemanticContextAssembler` and have both semantic maintenance and NLQ depend on it. The important rule is that NLQ must not parse OSI documents or read configured YAML paths directly.

### Recommended Decisions

1. Use PostgreSQL as the production source of truth for OSI semantic models.

   Store canonical YAML as `TEXT`, parsed/validated structure as `JSONB`, and immutable version snapshots in a companion table. Do not use a binary BLOB as the primary design unless there is a concrete storage reason.

2. Keep filesystem + Git as an optional artifact workflow, not runtime persistence.

   It is useful for seed files, examples, local validation, CI schema checks, and import/export. It should not be the authoritative write path for production workers.

3. Add a semantic model repository boundary in P0.

   The parser should accept document content and return validated objects. A repository/provider should decide where the active document comes from. This keeps P0 able to start with file-backed fixtures while leaving the production backend as PostgreSQL without rewriting consumers.

4. Move OSI filters into centralized LLM context assembly in P0.

   `NLQService` should receive an assembled semantic context containing `ai_context.instructions` and required metric filters. It should not call `OSIParser` or read `settings.OSI_YAML_PATH`.

5. Make versioning and validation explicit.

   Every active OSI document should record `osi_schema_version`, `content_hash`, validation status/errors, and immutable version history. This directly mitigates the OSI Draft 0.2.0.dev volatility risk.

6. Replace "dual write to YAML then sync DB" with "DB transaction first, optional YAML export".

   During transition, writes should update the PostgreSQL OSI store and legacy `bi_metric_definitions` in one controlled service transaction where feasible. YAML export can be generated after commit for GitOps visibility, but should not be the transactional source.

7. Reframe hot reload as cache invalidation.

   With PostgreSQL persistence, hot reload becomes a cache/version invalidation problem. Use active version IDs, `updated_at`, or an event/outbox pattern. Filesystem watchers should remain development-only.

### Approval Recommendation

Request changes before implementation.

The OSI direction is sound, and the parser/module split is a reasonable starting point. The draft should be revised before P0 implementation to make PostgreSQL the production semantic model store and to centralize NLQ context assembly behind `ContextAssembler` or an equivalent provider. Filesystem + Git can remain as import/export and bootstrap support, but not as Mulan's production source of truth for governed semantic definitions.
