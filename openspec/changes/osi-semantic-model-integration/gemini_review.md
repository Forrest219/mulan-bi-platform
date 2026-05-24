# Gemini Code Review — OSI Semantic Model Integration

**Review Date**: 2026-05-24
**Reviewer**: Gemini 2.5 Flash (Vertex AI)
**Files Reviewed**: proposal.md, design.md, tasks.md
**Context**: Mulan BI Platform, docs/ARCHITECTURE.md

---

## Review Summary

The proposal outlines the integration of OSI (Open Semantic Interchange) YAML as the standard for semantic model definitions within Mulan, aiming to unify metric definitions, standardize AI context, and improve NL2SQL capabilities. The overall direction is sound and addresses a critical problem of inconsistent semantic definitions. The design document provides a clear architectural overview and detailed module designs for the `osi_parser` and its integration with existing services. The tasks are well-defined and categorized into phases. However, several aspects require further clarification and refinement to ensure full consistency with Mulan's established architectural principles and to mitigate potential risks.

---

## Issues Found (P1/P2/P3 classification)

### P1 (Critical)

- **Persistence Solution for OSI YAML (Design Section 4.2):** The proposal suggests storing OSI YAML files directly in `backend/semantic_models/` and managing them via Git. While Git provides version control, managing file synchronization across multiple instances in production environments (beyond NFS) can be complex and error-prone. The suggestion of a webhook for hot-reloading needs a more robust and scalable solution for distributed deployments. This contradicts Mulan's typical pattern of using PostgreSQL for persistent data.
- **`bi_metric_definitions` Migration Strategy (Proposal Section 6 & Design Section 5):** The plan for dual-write and eventual migration is mentioned, but the complexity of migrating historical data from `bi_metric_definitions` (potentially with business logic embedded) to a new YAML format is likely underestimated. The proposal mentions "分批迁移" (phased migration) but lacks concrete details on the tooling or process for this potentially complex data transformation and validation. This is a significant data integrity risk.
- **OSI Schema Volatility (Proposal Section 6):** Acknowledging that OSI is still in Draft 0.2.0.dev and schema changes are possible poses a significant risk. The mitigation strategy of "双写策略 + schema 版本锁定；变化时通过 OSI converter 迁移" needs to be elaborated. How will schema changes be detected? What is the process for updating existing OSI YAML files to a new schema? This could lead to frequent, breaking changes if not handled robustly.

### P2 (Major)

- **`llm/nlq_service.py` Direct `osi_parser` Access (Design Section 3.3):** The `NLQService` directly accesses `osi_parser.parse(settings.OSI_YAML_PATH)` to get `filters`. This creates a direct dependency on the parser and YAML file path in the NLQ service, bypassing the `ContextAssembler` which is designed to provide standardized AI context. This could lead to inconsistent context assembly and violates the principle of separation of concerns. The `NLQService` should ideally consume contexts prepared by the `ContextAssembler`.
- **Hot Reloading Strategy (Design Section 4.2 & Open Questions):** The design proposes hot-reloading via file system watching. While feasible for development, in a production microservices environment, file system watching across multiple containers or instances is inefficient and unreliable. A more robust mechanism (e.g., a centralized configuration service, a message queue-based refresh mechanism, or an API endpoint to trigger a reload) is preferable for production. The "生产环境可配置开关" (production environment configurable switch) indicates an awareness, but a concrete production strategy is missing.
- **Error Handling and Fallback for OSI Parsing:** The `parser.py` snippet shows `self.validator.validate(data)`, but the design does not explicitly detail the error handling strategy when validation fails. What happens if a YAML file is malformed or invalid according to the schema? How does the system gracefully degrade or report these errors?
- **AI Context Standardization Completeness (Design Section 3.2):** While `ContextAssembler` is designed to provide `ai_context`, the example for `build_prompt` in `NLQService` still manually constructs filter rules from `model.metrics.filters`. This suggests the `ContextAssembler` might not be fully encapsulating all necessary AI context, or there's a potential for duplication/inconsistency in how AI context is assembled.

### P3 (Minor)

- **`osi_parser/models.py` Type Hinting:** The `OSIField` dataclass uses `dimension: Optional[dict] = None`. It would be more robust to define a specific dataclass for `Dimension` to ensure type safety and clearer structure, aligning with the "Types, Warnings & Linters" mandate.
- **`sync_to_db` Method in `MetricsService` (Design Section 3.1):** The method name `sync_to_db` in `MetricsService` is somewhat ambiguous during the dual-write phase. It should be clear that it's syncing to the *legacy* `bi_metric_definitions` table, perhaps `sync_to_legacy_metric_definitions_db`.
- **Logging for Dual Write (Design Section 5.2):** No explicit mention of logging for the dual-write process. It's crucial to log successes and failures of syncing to `bi_metric_definitions` to monitor the migration progress and identify issues.
- **Clarity on `ai_context` in OSI YAML (Proposal Section 4):** The example `ai_context` shows `instructions: "当查询销售额时，必须确保过滤掉 is_returned 为 true 的订单。"`. It would be beneficial to clarify if this `ai_context` is *always* for human consumption in prompts or if it can also contain machine-readable rules that could be directly translated into SQL by the NLQ service (to reduce LLM hallucination).

---

## Architecture Concerns

- **Centralized Data vs. Distributed Files:** Mulan's architecture (`ARCHITECTURE.md`) generally relies on PostgreSQL for persistent data. Storing core semantic definitions in files (`backend/semantic_models/`) introduces a new pattern for critical business logic. While Git versioning is a benefit, the operational complexity of ensuring consistency across multiple running instances in production (especially if not using shared storage like NFS, which is not explicitly part of the Mulan deployment architecture) needs a more robust solution. This could become a single point of failure or inconsistency if not managed carefully.
- **Consistency with `backend/services/` Design:** The `osi_parser` module adheres to the `backend/services/` principle of being pure business logic without web framework dependencies. This is good.
- **Impact on Existing API Contracts:** The proposal states "无 API 变更" (No API changes), which is positive for backward compatibility. All changes are internal, demonstrating good encapsulation.
- **Single Source of Truth Enforcement:** The goal is to make OSI YAML the "single source of truth." The dual-write strategy and fallback mechanisms during migration need to be tightly controlled to prevent data discrepancies and ensure that `bi_metric_definitions` eventually becomes read-only or deprecated without side effects. The plan for how this is enforced (e.g., via code reviews, automated checks) is not fully detailed.

---

## Open Questions Assessment

1. **OSI YAML 持久化方案：文件系统还是 PostgreSQL BLOB/独立表？**
   - **Assessment:** P1 Critical. This is a fundamental architectural decision. The current proposal for file system + Git has operational challenges for production environments. Given Mulan's reliance on PostgreSQL for persistent data, exploring `PostgreSQL BLOB` or an `独立 osi_semantic_models 表` might align better with existing infrastructure and simplify deployment/synchronization. A clear, scalable production strategy is needed.

2. **是否需要版本化（semantic versioning of OSI documents）？**
   - **Assessment:** P2 Major. Given OSI schema volatility and the potential for changes, semantic versioning of individual OSI documents is crucial. This would allow for backward compatibility checks, migration strategies between versions, and prevent breaking changes for consumers of the semantic models. This needs to be addressed in the design.

3. **`bi_metric_definitions` 历史数据迁移时间线？**
   - **Assessment:** P2 Major. This needs a more concrete timeline and strategy. The scale of this migration, potential data transformations, and the validation process for ensuring accuracy are critical. This impacts the overall project timeline and risk.

4. **热重载策略：文件变化后是自动重载还是需要手动触发？**
   - **Assessment:** P2 Major. For production, automatic hot-reloading based on file system watches is problematic. A well-defined strategy (e.g., API-triggered refresh, event-driven updates) is required for robustness and consistency across distributed services.

5. **多租户支持：不同租户是否需要独立 OSI YAML？**
   - **Assessment:** P2 Major. This is a significant scalability and data isolation concern. If multi-tenancy is a future requirement, the design should at least consider how independent OSI YAMLs would be managed, stored, and accessed without major refactoring.

6. **`bi_metric_definitions` 迁移批次：历史数据量大，如何分批迁移？**
   - **Assessment:** P2 Major. Similar to question 3, detailed planning for phased migration, including data transformation scripts, validation steps, and rollback strategies, is essential.

---

## Recommendations

1. **Re-evaluate OSI YAML Persistence:** Strongly consider storing OSI YAML definitions in PostgreSQL (either as JSONB in a dedicated table or as text blobs) rather than raw files. This aligns with Mulan's existing data persistence patterns, simplifies deployment in containerized/distributed environments, and leverages PostgreSQL's transactional guarantees and backup mechanisms. If file-based is insisted upon, a robust, production-ready synchronization and hot-reloading mechanism needs to be fully designed.
2. **Detail `bi_metric_definitions` Migration:** Provide a comprehensive plan for migrating existing `bi_metric_definitions` to OSI YAML. This should include:
   - A tool/script for automated conversion.
   - A clear validation process to ensure semantic equivalence post-migration.
   - Phased rollout strategy with clear criteria for moving from dual-write to OSI-only.
   - A rollback plan in case of issues.
3. **Refine OSI Schema Versioning and Evolution:** Develop a clear strategy for handling OSI schema evolution, including:
   - How Mulan will consume specific versions of the OSI schema.
   - A process for migrating existing OSI YAML documents to newer schema versions.
   - Tools or guidelines for developers when the OSI schema changes.
4. **Centralize AI Context Assembly:** Ensure the `ContextAssembler` is the single point of truth for preparing all AI-related context (including filters) for the `NLQService`. The `NLQService` should not directly parse OSI YAML for filters. This promotes consistency and modularity.
5. **Robust Error Handling:** Explicitly define error handling strategies for OSI YAML parsing and validation failures. The system should provide clear error messages and gracefully degrade or prevent operations with invalid semantic models.
6. **Formalize Hot Reloading for Production:** If hot-reloading is a requirement, design a production-grade mechanism that doesn't rely on file system watching. Options include an API endpoint to trigger a refresh, or integration with a configuration management system.
7. **Address Open Questions:** Provide concrete answers and detailed design for all "Open Questions" from `proposal.md` and `design.md` before final approval. These are significant enough to impact implementation and stability.

---

## Approval Recommendation

**Request Changes**

The proposal addresses a critical need and presents a promising direction. However, the current design has significant gaps and risks, particularly concerning the persistence and synchronization of OSI YAML in a production environment, the migration strategy for existing data, and the handling of OSI schema evolution. Further detailed design and risk mitigation strategies are required for these critical areas before proceeding with implementation.