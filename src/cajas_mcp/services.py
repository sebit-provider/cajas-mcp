from __future__ import annotations

import hashlib
import itertools
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any

from .adapters.external_context import ExternalContextProvider
from .schemas.assembly import AssemblyCandidate, ExternalContextSummary, Signal
from .schemas.raw import RawEntry
from .security.sanitizer import sanitize_external_query


@dataclass(frozen=True)
class AssemblyWeights:
    same_project: float = 0.16
    same_department: float = 0.10
    same_counterparty: float = 0.18
    date_proximity: float = 0.15
    description_similarity: float = 0.14
    amount_pattern: float = 0.08
    same_import_batch: float = 0.07
    same_source: float = 0.05
    event_hint_similarity: float = 0.04
    account_pattern: float = 0.03
    external_context: float = 0.05

    @property
    def total(self) -> float:
        return sum(self.__dict__.values())


DEFAULT_ASSEMBLY_WEIGHTS = AssemblyWeights()

INTRINSIC_FINAL_WEIGHT = 0.70
HISTORICAL_FINAL_WEIGHT = 0.25
EXTERNAL_FINAL_WEIGHT = 0.05


class AssemblyRecommendationEngine:
    def __init__(
        self,
        *,
        external_provider: ExternalContextProvider | None = None,
        weights: AssemblyWeights = DEFAULT_ASSEMBLY_WEIGHTS,
        cluster_threshold: float = 0.48,
        external_trigger_threshold: float = 0.62,
    ) -> None:
        self.external_provider = external_provider
        self.weights = weights
        self.cluster_threshold = cluster_threshold
        self.external_trigger_threshold = external_trigger_threshold

    async def recommend(
        self,
        raw_entries: list[dict[str, Any] | RawEntry],
        *,
        include_external_context: bool,
        historical_groups: list[dict[str, Any]] | None = None,
        history_available: bool = False,
    ) -> dict[str, Any]:
        entries = [entry if isinstance(entry, RawEntry) else RawEntry.model_validate(entry) for entry in raw_entries]
        if not entries:
            return {"candidates": [], "historical_pattern": {"available": False, "reason": "NO_RAW_ENTRIES"}}
        if len(entries) == 1:
            historical = self._historical_summary(entries, historical_groups or [], history_available=history_available)
            candidate = self._candidate_for_group(
                entries,
                historical=historical,
                external=ExternalContextSummary(available=False, used=False),
                external_trigger={"used": False, "reason": "SINGLE_RAW_ENTRY"},
                pair_relationships={},
            )
            candidate.warnings.append("Only one RAW entry was supplied; recommendation cannot compare related entries.")
            comparison = self._existing_judgment_comparison(entries, [[entry.id] for entry in entries])
            return {
                "candidates": [candidate.model_dump()],
                "historical_pattern": historical,
                "existing_judgment_comparison": comparison,
                "warnings": self._top_level_warnings(entries, comparison),
            }

        pair_relationships = self._pair_relationships(entries)
        pair_scores = {key: float(value.get("relationship_score") or 0.0) for key, value in pair_relationships.items()}
        groups = self._cluster(entries, pair_scores)
        candidates: list[AssemblyCandidate] = []
        for group in groups:
            historical = self._historical_summary(group, historical_groups or [], history_available=history_available)
            preliminary = self._candidate_for_group(
                group,
                historical=historical,
                external=ExternalContextSummary(available=False, used=False),
                external_trigger={"used": False, "reason": "PRELIMINARY"},
                pair_relationships=pair_relationships,
            )
            internal_confidence = max(preliminary.score_components.get("intrinsic", 0.0), preliminary.score_components.get("historical", 0.0))
            external, external_trigger = await self._maybe_external_context(group, internal_confidence, include_external_context)
            candidates.append(
                self._candidate_for_group(
                    group,
                    historical=historical,
                    external=external,
                    external_trigger=external_trigger,
                    pair_relationships=pair_relationships,
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        recommended_groups = [candidate.raw_entry_ids for candidate in candidates]
        comparison = self._existing_judgment_comparison(entries, recommended_groups)
        return {
            "candidates": [candidate.model_dump() for candidate in candidates],
            "historical_pattern": {
                "available": bool(history_available),
                "groups_checked": len(historical_groups or []),
                "reason": None if history_available else "NO_HISTORY",
            },
            "existing_judgment_comparison": comparison,
            "warnings": self._top_level_warnings(entries, comparison),
        }

    def _pair_relationships(self, entries: list[RawEntry]) -> dict[tuple[str, str], dict[str, Any]]:
        relationships: dict[tuple[str, str], dict[str, Any]] = {}
        for left, right in itertools.combinations(entries, 2):
            relationships[(left.id, right.id)] = self._transaction_relationship(left, right)
        return relationships

    def _cluster(self, entries: list[RawEntry], pair_scores: dict[tuple[str, str], float]) -> list[list[RawEntry]]:
        parent = {entry.id: entry.id for entry in entries}

        def find(raw_id: str) -> str:
            while parent[raw_id] != raw_id:
                parent[raw_id] = parent[parent[raw_id]]
                raw_id = parent[raw_id]
            return raw_id

        def union(a: str, b: str) -> None:
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_b] = root_a

        for (left_id, right_id), score in pair_scores.items():
            if score >= self.cluster_threshold:
                union(left_id, right_id)
        grouped: dict[str, list[RawEntry]] = {}
        for entry in entries:
            grouped.setdefault(find(entry.id), []).append(entry)
        return list(grouped.values())

    def _candidate_for_group(
        self,
        entries: list[RawEntry],
        *,
        historical: dict[str, Any],
        external: ExternalContextSummary,
        external_trigger: dict[str, Any],
        pair_relationships: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> AssemblyCandidate:
        signals = self._signals_for_group(entries, external=external)
        intrinsic = self._intrinsic_score(signals)
        relationship_summary = _relationship_summary(entries, pair_relationships or {}, self.cluster_threshold)
        historical_score = float(historical.get("score") or 0.0) if historical.get("available") else 0.0
        external_score = float(external.score or 0.0) if external.used else 0.0
        if historical.get("available"):
            score = (
                intrinsic * INTRINSIC_FINAL_WEIGHT
                + historical_score * HISTORICAL_FINAL_WEIGHT
                + external_score * EXTERNAL_FINAL_WEIGHT
            )
        else:
            score = intrinsic * (1.0 - EXTERNAL_FINAL_WEIGHT) + external_score * EXTERNAL_FINAL_WEIGHT
        raw_ids = [entry.id for entry in entries]
        digest = hashlib.sha1(",".join(sorted(raw_ids)).encode("utf-8")).hexdigest()[:12]
        reasons = self._reasons(signals, historical)
        warnings = self._warnings(entries, external, historical)
        return AssemblyCandidate(
            candidate_id=f"rec_{digest}",
            raw_entry_ids=raw_ids,
            score=round(score, 4),
            score_components={
                "intrinsic": round(intrinsic, 4),
                "historical": round(historical_score, 4),
                "external": round(external_score, 4),
            },
            relationship_score=relationship_summary["relationship_score"],
            evidence_coverage=relationship_summary["evidence_coverage"],
            confidence=relationship_summary["confidence"],
            relationship_types=relationship_summary["relationship_types"],
            pair_relationships=relationship_summary["pair_relationships"],
            nearest_relationships=relationship_summary["nearest_relationships"],
            signals=signals,
            historical_pattern=historical,
            reasons=reasons,
            warnings=warnings,
            external_context_trigger=external_trigger,
            external_context_used=external.used,
            mutation=False,
        )

    def _signals_for_group(self, entries: list[RawEntry], *, external: ExternalContextSummary) -> list[Signal]:
        return [
            self._transaction_relationship_signal(entries),
            self._same_field(entries, "project", "same_project", "RAW entries share the same project."),
            self._same_field(entries, "department", "same_department", "RAW entries share the same department."),
            self._same_counterparty(entries),
            self._date_proximity(entries),
            self._description_similarity(entries),
            self._amount_pattern(entries),
            self._same_field(entries, "import_batch_id", "same_import_batch", "RAW entries came from the same import batch."),
            self._same_field(entries, "source", "same_source", "RAW entries came from the same source."),
            self._event_hint_similarity(entries),
            self._account_pattern(entries),
            Signal(
                type="external_context",
                score=external.score,
                value={"used": external.used, "available": external.available, "trust": external.trust},
                available=external.available,
                explanation="External context is weak supporting context only and is never accounting evidence.",
            ),
        ]

    def _transaction_relationship_signal(self, entries: list[RawEntry]) -> Signal:
        if len(entries) < 2:
            return Signal(
                type="transaction_relationship",
                score=0.0,
                available=False,
                explanation="At least two RAW entries are required to measure a transaction relationship.",
            )
        relationships = [self._transaction_relationship(left, right) for left, right in itertools.combinations(entries, 2)]
        score = sum(float(item["relationship_score"]) for item in relationships) / len(relationships)
        coverage = sum(float(item["evidence_coverage"]) for item in relationships) / len(relationships)
        confidence = sum(float(item["confidence"]) for item in relationships) / len(relationships)
        relationship_types = sorted({rel_type for item in relationships for rel_type in item.get("relationship_types", [])})
        explanation = "RAW entries have observable transaction-level relationship signals."
        if not relationship_types or relationship_types == ["UNKNOWN_RELATIONSHIP"]:
            explanation = "No strong transaction lifecycle relationship was observed."
        return Signal(
            type="transaction_relationship",
            score=round(score, 4),
            value={
                "relationship_types": relationship_types,
                "evidence_coverage": round(coverage, 4),
                "confidence": round(confidence, 4),
                "pair_count": len(relationships),
            },
            explanation=explanation,
        )

    @staticmethod
    def _same_field(entries: list[RawEntry], field: str, signal_type: str, explanation: str) -> Signal:
        values = [str(getattr(entry, field) or "").strip().lower() for entry in entries]
        present = [value for value in values if value]
        if len(present) < 2:
            return Signal(type=signal_type, score=0.0, value=False, available=False, explanation=f"No comparable {field}.")
        same = len(set(present)) == 1 and len(present) == len(entries)
        return Signal(type=signal_type, score=1.0 if same else 0.0, value=same, explanation=explanation if same else f"{field} differs.")

    @staticmethod
    def _same_counterparty(entries: list[RawEntry]) -> Signal:
        values = [str(entry.counterparty_id or entry.counterpart_id or entry.counterparty_name or "").strip().lower() for entry in entries]
        present = [value for value in values if value]
        if len(present) < 2:
            return Signal(type="same_counterparty", score=0.0, value=False, available=False, explanation="No comparable counterparty.")
        same = len(set(present)) == 1 and len(present) == len(entries)
        return Signal(type="same_counterparty", score=1.0 if same else 0.0, value=same, explanation="Counterparty matches." if same else "Counterparty differs.")

    @staticmethod
    def _date_proximity(entries: list[RawEntry]) -> Signal:
        dates = [_parse_date(entry.tx_date or entry.entry_date) for entry in entries]
        dates = [value for value in dates if value is not None]
        if len(dates) < 2:
            return Signal(type="date_proximity", score=0.0, value=None, available=False, explanation="No comparable dates.")
        span = (max(dates) - min(dates)).days
        score = max(0.0, 1.0 - min(span, 60) / 60)
        return Signal(type="date_proximity", score=round(score, 4), value={"days_span": span}, explanation=f"Date span is {span} days.")

    @staticmethod
    def _description_similarity(entries: list[RawEntry]) -> Signal:
        texts = [_normalized_text(" ".join([entry.description or "", entry.memo or "", entry.event_hint_key or ""])) for entry in entries]
        texts = [text for text in texts if text]
        if len(texts) < 2:
            return Signal(type="description_similarity", score=0.0, value=None, available=False, explanation="No comparable descriptions.")
        scores = [SequenceMatcher(None, left, right).ratio() for left, right in itertools.combinations(texts, 2)]
        score = sum(scores) / len(scores)
        return Signal(type="description_similarity", score=round(score, 4), value={"pair_count": len(scores)}, explanation="Descriptions have textual similarity.")

    @staticmethod
    def _amount_pattern(entries: list[RawEntry]) -> Signal:
        amounts = [abs(float(entry.total_amount if entry.total_amount is not None else entry.amount or 0)) for entry in entries]
        amounts = [amount for amount in amounts if amount > 0]
        if len(amounts) < 2:
            return Signal(type="amount_pattern", score=0.0, value=None, available=False, explanation="No comparable amounts.")
        max_amount = max(amounts)
        min_amount = min(amounts)
        ratio = min_amount / max_amount if max_amount else 0.0
        repeated = len({round(amount, 2) for amount in amounts}) < len(amounts)
        score = 1.0 if repeated else max(0.0, min(1.0, ratio))
        return Signal(type="amount_pattern", score=round(score, 4), value={"repeated_amount": repeated, "min_max_ratio": round(ratio, 4)}, explanation="Amounts show a comparable pattern.")

    @staticmethod
    def _event_hint_similarity(entries: list[RawEntry]) -> Signal:
        hints = [str(entry.event_hint_key or "").strip().lower() for entry in entries if str(entry.event_hint_key or "").strip()]
        if len(hints) < 2:
            return Signal(type="event_hint_similarity", score=0.0, available=False, explanation="No comparable event hints.")
        score = 1.0 if len(set(hints)) == 1 and len(hints) == len(entries) else SequenceMatcher(None, " ".join(hints), hints[0]).ratio()
        return Signal(type="event_hint_similarity", score=round(score, 4), value={"hints": len(hints)}, explanation="Event hints are similar.")

    @staticmethod
    def _account_pattern(entries: list[RawEntry]) -> Signal:
        account_sets: list[set[str]] = []
        for entry in entries:
            accounts = {str(entry.debit_account_code or "").strip(), str(entry.credit_account_code or "").strip()}
            for line in entry.lines:
                if isinstance(line, dict):
                    accounts.add(str(line.get("account_code") or "").strip())
            account_sets.append({account for account in accounts if account})
        comparable = [accounts for accounts in account_sets if accounts]
        if len(comparable) < 2:
            return Signal(type="account_pattern", score=0.0, available=False, explanation="No comparable account pattern.")
        intersection = set.intersection(*comparable)
        union = set.union(*comparable)
        score = len(intersection) / len(union) if union else 0.0
        return Signal(type="account_pattern", score=round(score, 4), value={"shared_accounts": sorted(intersection)}, explanation="Account codes overlap.")

    def _transaction_relationship(self, left: RawEntry, right: RawEntry) -> dict[str, Any]:
        left_features = _transaction_features(left)
        right_features = _transaction_features(right)
        components: dict[str, float] = {}

        semantic = _concept_similarity(left_features["concepts"], right_features["concepts"])
        text_similarity = SequenceMatcher(None, left_features["text"], right_features["text"]).ratio() if left_features["text"] and right_features["text"] else None
        if semantic is not None or text_similarity is not None:
            components["semantic_relationship"] = max(semantic or 0.0, text_similarity or 0.0)

        account = _set_similarity(left_features["accounts"], right_features["accounts"])
        if left_features["accounts"] and right_features["accounts"]:
            components["account_relationship"] = account

        amount = _amount_similarity(left, right)
        if amount is not None:
            components["amount_relationship"] = amount

        temporal = _date_pair_score(left, right)
        if temporal is not None:
            components["temporal_relationship"] = temporal

        counterparty = _counterparty_pair_score(left, right)
        if counterparty is not None:
            components["counterparty_relationship"] = counterparty

        source = _source_pair_score(left, right)
        if source is not None:
            components["source_relationship"] = source

        lifecycle = _lifecycle_relationship_score(left_features, right_features)
        components["lifecycle_relationship"] = lifecycle["score"]

        weights = {
            "semantic_relationship": 0.20,
            "account_relationship": 0.18,
            "amount_relationship": 0.14,
            "temporal_relationship": 0.14,
            "counterparty_relationship": 0.12,
            "source_relationship": 0.07,
            "lifecycle_relationship": 0.15,
        }
        available_total = sum(weights[name] for name in components)
        score = sum(components[name] * weights[name] for name in components) / available_total if available_total else 0.0
        if (
            lifecycle["types"] == ["UNKNOWN_RELATIONSHIP"]
            and components.get("semantic_relationship", 0.0) < 0.35
            and components.get("counterparty_relationship") == 0.0
        ):
            score = min(score, 0.38)
        coverage = available_total / sum(weights.values())
        relationship_types = lifecycle["types"] or _fallback_relationship_types(components)
        confidence = score * 0.65 + coverage * 0.35
        return {
            "left_raw_entry_id": left.id,
            "right_raw_entry_id": right.id,
            "relationship_score": round(max(0.0, min(1.0, score)), 4),
            "evidence_coverage": round(max(0.0, min(1.0, coverage)), 4),
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "relationship_types": relationship_types,
            "components": {name: round(value, 4) for name, value in components.items()},
            "below_grouping_threshold": score < self.cluster_threshold,
        }

    def _intrinsic_score(self, signals: list[Signal]) -> float:
        by_type = {signal.type: signal.score for signal in signals}
        available = {signal.type: signal.available for signal in signals}
        intrinsic_weights = {k: v for k, v in self.weights.__dict__.items() if k != "external_context"}
        weighted = sum(by_type.get(name, 0.0) * weight for name, weight in intrinsic_weights.items() if available.get(name, True))
        total = sum(weight for name, weight in intrinsic_weights.items() if available.get(name, True)) or 1.0
        legacy_score = max(0.0, min(1.0, weighted / total))
        if available.get("transaction_relationship"):
            transaction_score = by_type.get("transaction_relationship", 0.0)
            return max(0.0, min(1.0, transaction_score * 0.55 + legacy_score * 0.45))
        return legacy_score

    def _historical_summary(
        self,
        entries: list[RawEntry],
        historical_groups: list[dict[str, Any]],
        *,
        history_available: bool,
    ) -> dict[str, Any]:
        if not history_available:
            return {"available": False, "reason": "NO_HISTORY", "score": 0.0}
        if not historical_groups:
            return {
                "available": True,
                "groups_checked": 0,
                "matched_groups": 0,
                "positive_matches": 0,
                "strong_matches": 0,
                "counterexamples": 0,
                "governance_quality": 0.0,
                "effective_support": 0.0,
                "score": 0.0,
                "examples": [],
            }
        comparisons = [self._compare_historical_group(entries, group) for group in historical_groups]
        comparisons.sort(key=lambda item: item["effective_support"], reverse=True)
        positives = [item for item in comparisons if item["similarity"] >= 0.55]
        strong = [item for item in comparisons if item["effective_support"] >= 0.72]
        counterexamples = [item for item in comparisons if item.get("counterexample")]
        if positives:
            base = sum(item["effective_support"] for item in positives[:5]) / min(len(positives), 5)
            frequency = min(1.0, math.log1p(len(positives)) / math.log1p(6))
            score = base * 0.75 + frequency * 0.25
        else:
            score = 0.0
        score = max(0.0, min(1.0, score - min(0.35, 0.06 * len(counterexamples))))
        governance_values = [float(item.get("governance_quality") or 0.0) for item in positives[:5]]
        governance_quality = sum(governance_values) / len(governance_values) if governance_values else 0.0
        summary: dict[str, Any] = {
            "available": True,
            "groups_checked": len(historical_groups),
            "matched_groups": len(positives),
            "positive_matches": len(positives),
            "strong_matches": len(strong),
            "counterexamples": len(counterexamples),
            "governance_quality": round(governance_quality, 4),
            "effective_support": round(score, 4),
            "score": round(score, 4),
            "examples": positives[:5] or comparisons[:3],
        }
        if counterexamples:
            summary["warning"] = f"Similar context was split across {len(counterexamples)} previous assembly group(s)."
        return summary

    def _compare_historical_group(self, entries: list[RawEntry], group: dict[str, Any]) -> dict[str, Any]:
        historical_entries = [RawEntry.model_validate(raw) for raw in group.get("raw_entries") or [] if isinstance(raw, dict)]
        candidate_features = _group_features(entries)
        historical_features = _group_features(historical_entries)
        matched: list[str] = []
        project = _set_similarity(candidate_features["projects"], historical_features["projects"])
        department = _set_similarity(candidate_features["departments"], historical_features["departments"])
        counterparty = _set_similarity(candidate_features["counterparties"], historical_features["counterparties"])
        accounts = _set_similarity(candidate_features["accounts"], historical_features["accounts"])
        description = SequenceMatcher(None, candidate_features["text"], historical_features["text"]).ratio() if candidate_features["text"] and historical_features["text"] else 0.0
        count_similarity = 0.0
        if entries and historical_entries:
            count_similarity = 1.0 - abs(len(entries) - len(historical_entries)) / max(len(entries), len(historical_entries))
        source = _set_similarity(candidate_features["sources"], historical_features["sources"])
        event_hint = _set_similarity(candidate_features["event_hints"], historical_features["event_hints"])
        relationship_type_similarity = _set_similarity(candidate_features["relationship_types"], historical_features["relationship_types"])
        relationship_score_similarity = 1.0 - abs(candidate_features["relationship_score"] - historical_features["relationship_score"])
        relationship_score_similarity = max(0.0, min(1.0, relationship_score_similarity))
        components = {
            "same_or_similar_project": project,
            "same_department_structure": department,
            "same_counterparty": counterparty,
            "similar_account_pattern": accounts,
            "similar_description": description,
            "similar_raw_count": count_similarity,
            "same_source_pattern": source,
            "similar_event_hint": event_hint,
            "similar_transaction_relationship_type": relationship_type_similarity,
            "similar_transaction_relationship_strength": relationship_score_similarity,
        }
        for name, value in components.items():
            if value >= 0.5:
                matched.append(name)
        similarity = (
            project * 0.08
            + department * 0.06
            + counterparty * 0.14
            + accounts * 0.18
            + description * 0.14
            + count_similarity * 0.06
            + source * 0.06
            + event_hint * 0.06
            + relationship_type_similarity * 0.14
            + relationship_score_similarity * 0.08
        )
        governance = _governance_quality(group)
        structural_similarity = max(0.0, min(1.0, similarity))
        effective_support = structural_similarity * governance["quality"]
        context_similarity = max(project, counterparty)
        counterexample = context_similarity >= 0.75 and similarity < 0.55
        return {
            "group_id": group.get("group_id"),
            "status": group.get("status"),
            "similarity": round(structural_similarity, 4),
            "governance_quality": round(governance["quality"], 4),
            "effective_support": round(effective_support, 4),
            "governance": governance,
            "matched_signals": matched,
            "raw_count": len(historical_entries),
            "has_valid_signature": bool(group.get("has_valid_signature")),
            "event": group.get("event"),
            "counterexample": bool(counterexample),
        }

    async def _maybe_external_context(
        self,
        entries: list[RawEntry],
        preliminary_score: float,
        include_external_context: bool,
    ) -> tuple[ExternalContextSummary, dict[str, Any]]:
        if not include_external_context or self.external_provider is None:
            return ExternalContextSummary(available=False, used=False), {"used": False, "reason": "USER_NOT_REQUESTED"}
        query_text = " ".join(" ".join([entry.description or "", entry.memo or "", entry.event_hint_key or ""]) for entry in entries)
        query = sanitize_external_query(query_text)
        if not query:
            return ExternalContextSummary(available=False, used=False, warning="No sanitized external query terms available."), {
                "used": False,
                "reason": "NO_SANITIZED_QUERY_TERMS",
            }
        has_unknown_terms = self._has_unknown_operational_terms(query)
        low_confidence = preliminary_score < self.external_trigger_threshold
        should_use = has_unknown_terms and (low_confidence or include_external_context)
        if not should_use:
            if low_confidence:
                return ExternalContextSummary(
                    available=True,
                    used=False,
                    warning="Internal confidence was low, but no sanitized operational terms suggested useful external context.",
                ), {
                    "used": False,
                    "reason": "LOW_INTERNAL_CONFIDENCE_NO_EXTERNAL_AMBIGUITY",
                }
            return ExternalContextSummary(available=True, used=False, warning="Internal confidence was sufficient; external context not used."), {
                "used": False,
                "reason": "INTERNAL_CONFIDENCE_SUFFICIENT",
            }
        reason = "UNKNOWN_OPERATIONAL_TERMS" if has_unknown_terms else "LOW_INTERNAL_CONFIDENCE"
        try:
            results = await self.external_provider.search(f"{query} operational relationship", limit=5)
            patterns = await self.external_provider.extract_work_patterns(results)
        except Exception as exc:
            return ExternalContextSummary(available=False, used=False, warning=f"External provider unavailable: {type(exc).__name__}"), {
                "used": False,
                "reason": reason,
                "error": type(exc).__name__,
            }
        if not results:
            return ExternalContextSummary(available=False, used=True, warning="External provider returned no usable results."), {
                "used": True,
                "reason": reason,
            }
        score = min(0.6, 0.12 + 0.08 * min(len(results), 5) + 0.04 * min(len(patterns), 3))
        return (
            ExternalContextSummary(
                available=True,
                used=True,
                score=round(score, 4),
                results=[result.__dict__ for result in results[:5]],
            ),
            {"used": True, "reason": reason},
        )

    @staticmethod
    def _has_unknown_operational_terms(query: str) -> bool:
        return any(token in query.lower() for token in ("aws", "azure", "gcp", "migration", "implementation", "gateway", "subscription"))

    @staticmethod
    def _reasons(signals: list[Signal], historical: dict[str, Any]) -> list[str]:
        strong = [signal for signal in signals if signal.available and signal.score >= 0.7 and signal.type != "external_context"]
        reasons = [signal.explanation for signal in strong[:5] if signal.explanation]
        if historical.get("available") and int(historical.get("positive_matches") or 0) > 0:
            reasons.append(
                f"{historical.get('positive_matches')} similar historical assembly group(s) support this grouping as an observation."
            )
        return reasons

    @staticmethod
    def _warnings(entries: list[RawEntry], external: ExternalContextSummary, historical: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        if any(str(entry.status or "").lower() == "assembled" for entry in entries):
            warnings.append("REANALYZING_EXISTING_ASSEMBLY: One or more RAW entries already belong to an Assembly. Recommendation will not modify existing judgment.")
        if historical.get("warning"):
            warnings.append(str(historical["warning"]))
        if external.warning:
            warnings.append(external.warning)
        if external.used:
            warnings.append("External community context is untrusted and is not accounting evidence.")
        return warnings

    @staticmethod
    def _existing_judgment_comparison(entries: list[RawEntry], recommended_groups: list[list[str]]) -> dict[str, Any]:
        assembled_entries = [entry for entry in entries if str(entry.assembled_event_id or "").strip()]
        if not assembled_entries:
            return {
                "available": False,
                "reason": "NO_EXISTING_ASSEMBLY",
                "mutation": False,
            }
        existing_by_event: dict[str, list[str]] = {}
        unassembled: list[str] = []
        for entry in entries:
            event_id = str(entry.assembled_event_id or "").strip()
            if event_id:
                existing_by_event.setdefault(event_id, []).append(entry.id)
            else:
                unassembled.append(entry.id)
        existing_groups = list(existing_by_event.values()) + [[raw_id] for raw_id in unassembled]
        score_details = _pairwise_partition_agreement(existing_groups, recommended_groups)
        classification = _classify_partition_change(existing_groups, recommended_groups, score_details)
        disagreement = classification != "AGREEMENT"
        coverage = len(assembled_entries) / len(entries) if entries else 0.0
        severity = "none"
        if disagreement:
            if score_details["agreement_score"] < 0.45 and coverage >= 0.8:
                severity = "medium"
            elif score_details["agreement_score"] < 0.75:
                severity = "low"
            else:
                severity = "info"
        return {
            "available": True,
            "classification": classification,
            "agreement_score": score_details["agreement_score"],
            "disagreement": disagreement,
            "coverage": round(coverage, 4),
            "existing_group_count": len(existing_groups),
            "recommendation_group_count": len([group for group in recommended_groups if group]),
            "existing_groups": [
                {"reference_type": "assembled_event_id", "reference_id": event_id, "raw_entry_ids": raw_ids}
                for event_id, raw_ids in existing_by_event.items()
            ],
            "recommended_groups": [{"raw_entry_ids": list(group)} for group in recommended_groups],
            "pair_counts": score_details["pair_counts"],
            "review_signal": {
                "recommended": bool(disagreement and severity in {"low", "medium"}),
                "severity": severity,
                "reason": "EXISTING_ASSEMBLY_DIFFERS_FROM_RECOMMENDATION" if disagreement else "EXISTING_ASSEMBLY_MATCHES_RECOMMENDATION",
                "meaning": "Human review may be useful. This is not an automatic correction and does not modify existing Assembly or Event records.",
            },
            "mutation": False,
        }

    @staticmethod
    def _top_level_warnings(entries: list[RawEntry], comparison: dict[str, Any]) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        if any(str(entry.status or "").lower() == "assembled" or str(entry.assembled_event_id or "").strip() for entry in entries):
            warnings.append(
                {
                    "code": "REANALYZING_EXISTING_ASSEMBLY",
                    "message": "One or more RAW entries already belong to an Assembly. Recommendation will not modify existing judgment.",
                }
            )
        if comparison.get("available") and comparison.get("disagreement"):
            warnings.append(
                {
                    "code": "EXISTING_ASSEMBLY_REVIEW_SIGNAL",
                    "message": "Existing human Assembly and MCP recommendation differ. Treat this as a review signal, not an error finding.",
                    "severity": (comparison.get("review_signal") or {}).get("severity"),
                }
            )
        return warnings


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    clean = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9가-힣\s]", " ", value.lower())).strip()


def _group_features(entries: list[RawEntry]) -> dict[str, Any]:
    accounts: set[str] = set()
    relationship_types: set[str] = set()
    relationship_scores: list[float] = []
    for entry in entries:
        accounts.update(str(code or "").strip() for code in entry.account_codes)
        accounts.add(str(entry.debit_account_code or "").strip())
        accounts.add(str(entry.credit_account_code or "").strip())
        for line in entry.lines:
            if isinstance(line, dict):
                accounts.add(str(line.get("account_code") or "").strip())
    if len(entries) >= 2:
        engine = AssemblyRecommendationEngine()
        for left, right in itertools.combinations(entries, 2):
            relationship = engine._transaction_relationship(left, right)
            relationship_scores.append(float(relationship.get("relationship_score") or 0.0))
            relationship_types.update(str(item) for item in relationship.get("relationship_types") or [])
    return {
        "projects": {str(entry.project or "").strip().lower() for entry in entries if str(entry.project or "").strip()},
        "departments": {str(entry.department or "").strip().lower() for entry in entries if str(entry.department or "").strip()},
        "counterparties": {
            str(entry.counterparty_id or entry.counterpart_id or entry.counterparty_name or "").strip().lower()
            for entry in entries
            if str(entry.counterparty_id or entry.counterpart_id or entry.counterparty_name or "").strip()
        },
        "accounts": {code for code in accounts if code},
        "sources": {str(entry.source or "").strip().lower() for entry in entries if str(entry.source or "").strip()},
        "event_hints": {str(entry.event_hint_key or "").strip().lower() for entry in entries if str(entry.event_hint_key or "").strip()},
        "text": _normalized_text(" ".join(" ".join([entry.description or "", entry.memo or "", entry.event_hint_key or ""]) for entry in entries)),
        "relationship_types": relationship_types,
        "relationship_score": sum(relationship_scores) / len(relationship_scores) if relationship_scores else 0.0,
    }


def _set_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _transaction_features(entry: RawEntry) -> dict[str, Any]:
    text = _normalized_text(" ".join([entry.description or "", entry.memo or "", entry.event_hint_key or ""]))
    accounts = set(str(code or "").strip() for code in entry.account_codes if str(code or "").strip())
    accounts.add(str(entry.debit_account_code or "").strip())
    accounts.add(str(entry.credit_account_code or "").strip())
    for line in entry.lines:
        if isinstance(line, dict):
            accounts.add(str(line.get("account_code") or "").strip())
    return {
        "text": text,
        "concepts": _transaction_concepts(text),
        "accounts": {account for account in accounts if account},
    }


def _transaction_concepts(text: str) -> set[str]:
    concepts: set[str] = set()
    mapping = {
        "매출채권": "receivable",
        "채권": "receivable",
        "회수": "collection",
        "입금": "collection",
        "매출": "revenue",
        "청구": "billing",
        "수익": "revenue",
        "선급": "prepayment",
        "선수": "deferred",
        "상각": "recognition",
        "인식": "recognition",
        "정산": "settlement",
        "조정": "adjustment",
        "취소": "reversal",
        "환입": "reversal",
        "구축": "implementation",
        "개발환경": "development_environment",
        "클라우드": "cloud",
        "운영": "operations",
        "이용권": "subscription",
        "라이선스": "license",
        "구독": "subscription",
        "산출물": "deliverable",
        "검수": "acceptance",
        "용역": "service",
        "외주": "procurement",
        "유지보수": "maintenance",
        "감사": "audit",
    }
    for key, value in mapping.items():
        if key in text:
            concepts.add(value)
    english = {
        "receivable",
        "collection",
        "payment",
        "revenue",
        "billing",
        "prepayment",
        "prepaid",
        "recognition",
        "settlement",
        "adjustment",
        "reversal",
        "implementation",
        "development",
        "environment",
        "cloud",
        "operations",
        "subscription",
        "license",
        "deliverable",
        "acceptance",
        "service",
        "procurement",
        "maintenance",
        "audit",
        "saas",
        "aws",
        "azure",
        "docker",
        "database",
    }
    tokens = set(text.split())
    for token in english:
        if token in tokens or token.replace("_", " ") in text:
            concepts.add(token)
    if "prepaid" in concepts:
        concepts.add("prepayment")
    if "development" in concepts and "environment" in concepts:
        concepts.add("development_environment")
    return concepts


def _concept_similarity(left: set[str], right: set[str]) -> float | None:
    if not left or not right:
        return None
    return len(left & right) / len(left | right)


def _amount_similarity(left: RawEntry, right: RawEntry) -> float | None:
    left_amount = abs(float(left.total_amount if left.total_amount is not None else left.amount or 0))
    right_amount = abs(float(right.total_amount if right.total_amount is not None else right.amount or 0))
    if left_amount <= 0 or right_amount <= 0:
        return None
    ratio = min(left_amount, right_amount) / max(left_amount, right_amount)
    return max(0.0, min(1.0, ratio))


def _date_pair_score(left: RawEntry, right: RawEntry) -> float | None:
    left_date = _parse_date(left.tx_date or left.entry_date)
    right_date = _parse_date(right.tx_date or right.entry_date)
    if left_date is None or right_date is None:
        return None
    span = abs((left_date - right_date).days)
    return max(0.0, 1.0 - min(span, 90) / 90)


def _counterparty_pair_score(left: RawEntry, right: RawEntry) -> float | None:
    left_value = str(left.counterparty_id or left.counterpart_id or left.counterparty_name or "").strip().lower()
    right_value = str(right.counterparty_id or right.counterpart_id or right.counterparty_name or "").strip().lower()
    if not left_value or not right_value:
        return None
    return 1.0 if left_value == right_value else 0.0


def _source_pair_score(left: RawEntry, right: RawEntry) -> float | None:
    left_values = [str(left.import_batch_id or "").strip().lower(), str(left.source or "").strip().lower()]
    right_values = [str(right.import_batch_id or "").strip().lower(), str(right.source or "").strip().lower()]
    comparable = [(a, b) for a, b in zip(left_values, right_values, strict=False) if a and b]
    if not comparable:
        return None
    return sum(1.0 if a == b else 0.0 for a, b in comparable) / len(comparable)


def _lifecycle_relationship_score(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    concepts = set(left["concepts"]) | set(right["concepts"])
    types: list[str] = []
    score = 0.0
    if {"revenue", "receivable", "collection"} & concepts and "collection" in concepts and ("revenue" in concepts or "receivable" in concepts):
        types.append("REVENUE_COLLECTION")
        score = max(score, 0.82)
    if "prepayment" in concepts and "recognition" in concepts:
        types.append("PREPAYMENT_RECOGNITION")
        score = max(score, 0.78)
    if "settlement" in concepts and ({"revenue", "billing", "payment", "collection"} & concepts):
        types.append("SETTLEMENT_SEQUENCE")
        score = max(score, 0.72)
    if {"adjustment", "reversal"} & concepts:
        types.append("REVERSAL_OR_ADJUSTMENT")
        score = max(score, 0.68)
    if {"implementation", "development_environment", "cloud", "operations", "subscription", "saas"} & concepts:
        if len({"implementation", "development_environment", "cloud", "operations", "subscription", "saas"} & concepts) >= 2:
            types.append("IMPLEMENTATION_OPERATION_SEQUENCE")
            score = max(score, 0.64)
    if "procurement" in concepts and ({"service", "deliverable", "acceptance"} & concepts):
        types.append("RELATED_PROCUREMENT")
        score = max(score, 0.62)
    if _concept_similarity(set(left["concepts"]), set(right["concepts"])) and (_concept_similarity(set(left["concepts"]), set(right["concepts"])) or 0.0) >= 0.5:
        types.append("SAME_OPERATION")
        score = max(score, 0.58)
    return {"score": score, "types": sorted(set(types)) or ["UNKNOWN_RELATIONSHIP"]}


def _fallback_relationship_types(components: dict[str, float]) -> list[str]:
    if components.get("amount_relationship", 0.0) >= 0.95 and components.get("temporal_relationship", 0.0) >= 0.75:
        return ["RECURRING_TRANSACTION"]
    if components.get("semantic_relationship", 0.0) >= 0.55:
        return ["SAME_OPERATION"]
    return ["UNKNOWN_RELATIONSHIP"]


def _relationship_summary(
    entries: list[RawEntry],
    pair_relationships: dict[tuple[str, str], dict[str, Any]],
    cluster_threshold: float,
) -> dict[str, Any]:
    ids = {entry.id for entry in entries}
    inside: list[dict[str, Any]] = []
    nearest: list[dict[str, Any]] = []
    for (left_id, right_id), relationship in pair_relationships.items():
        left_in = left_id in ids
        right_in = right_id in ids
        if left_in and right_in:
            inside.append(relationship)
        elif left_in or right_in:
            if float(relationship.get("relationship_score") or 0.0) > 0.0:
                other_id = right_id if left_in else left_id
                source_id = left_id if left_in else right_id
                nearest.append(
                    {
                        "raw_entry_id": source_id,
                        "related_raw_entry_id": other_id,
                        "relationship_score": relationship.get("relationship_score"),
                        "evidence_coverage": relationship.get("evidence_coverage"),
                        "confidence": relationship.get("confidence"),
                        "relationship_types": relationship.get("relationship_types") or [],
                        "below_grouping_threshold": float(relationship.get("relationship_score") or 0.0) < cluster_threshold,
                    }
                )
    selected = inside
    relationship_score = sum(float(item.get("relationship_score") or 0.0) for item in selected) / len(selected) if selected else 0.0
    coverage = sum(float(item.get("evidence_coverage") or 0.0) for item in selected) / len(selected) if selected else 0.0
    confidence = sum(float(item.get("confidence") or 0.0) for item in selected) / len(selected) if selected else 0.0
    relationship_types = sorted({rel_type for item in selected for rel_type in item.get("relationship_types", [])})
    nearest.sort(key=lambda item: float(item.get("relationship_score") or 0.0), reverse=True)
    return {
        "relationship_score": round(relationship_score, 4),
        "evidence_coverage": round(coverage, 4),
        "confidence": round(confidence, 4),
        "relationship_types": relationship_types,
        "pair_relationships": selected[:20],
        "nearest_relationships": nearest[:5],
    }


def _governance_quality(group: dict[str, Any]) -> dict[str, Any]:
    status = str(group.get("status") or "").strip().lower()
    event = group.get("event") if isinstance(group.get("event"), dict) else {}
    event_state = str((event or {}).get("state") or "").strip().lower()
    has_signature = bool(group.get("has_valid_signature"))
    confirmed = bool((event or {}).get("confirmed_at")) or event_state in {"confirmed", "final", "finalized"}
    finalized = status == "finalized" or event_state in {"final", "finalized"}
    if status == "voided" or event_state == "voided":
        quality = 0.0
        label = "VOIDED"
    elif finalized and has_signature:
        quality = 1.0
        label = "FINALIZED_WITH_SIGNATURE"
    elif finalized:
        quality = 0.92
        label = "FINALIZED"
    elif confirmed and has_signature:
        quality = 0.88
        label = "CONFIRMED_WITH_SIGNATURE"
    elif confirmed:
        quality = 0.78
        label = "CONFIRMED"
    elif has_signature:
        quality = 0.68
        label = "SIGNED_UNCONFIRMED"
    elif status == "assembled":
        quality = 0.52
        label = "ASSEMBLED_UNCONFIRMED"
    elif event_state in {"oriented", "draft"}:
        quality = 0.35
        label = "ORIENTED_OR_DRAFT"
    else:
        quality = 0.45
        label = "LIMITED_GOVERNANCE_METADATA"
    return {
        "quality": quality,
        "label": label,
        "assembly_status": status or None,
        "has_valid_signature": has_signature,
        "event_state": event_state or None,
        "event_confirmed": confirmed,
        "confirmed_at": (event or {}).get("confirmed_at"),
    }


def _pairwise_partition_agreement(existing_groups: list[list[str]], recommended_groups: list[list[str]]) -> dict[str, Any]:
    ids = sorted({raw_id for group in [*existing_groups, *recommended_groups] for raw_id in group})
    if len(ids) < 2:
        return {"agreement_score": 1.0, "pair_counts": {"total": 0, "agree": 0, "same_in_both": 0, "split_in_both": 0, "same_existing_split_recommended": 0, "split_existing_same_recommended": 0}}
    existing_index = _partition_index(existing_groups)
    recommended_index = _partition_index(recommended_groups)
    counts = {
        "total": 0,
        "agree": 0,
        "same_in_both": 0,
        "split_in_both": 0,
        "same_existing_split_recommended": 0,
        "split_existing_same_recommended": 0,
    }
    for left, right in itertools.combinations(ids, 2):
        same_existing = existing_index.get(left) == existing_index.get(right)
        same_recommended = recommended_index.get(left) == recommended_index.get(right)
        counts["total"] += 1
        if same_existing == same_recommended:
            counts["agree"] += 1
            counts["same_in_both" if same_existing else "split_in_both"] += 1
        elif same_existing:
            counts["same_existing_split_recommended"] += 1
        else:
            counts["split_existing_same_recommended"] += 1
    score = counts["agree"] / counts["total"] if counts["total"] else 1.0
    return {"agreement_score": round(score, 4), "pair_counts": counts}


def _classify_partition_change(existing_groups: list[list[str]], recommended_groups: list[list[str]], score_details: dict[str, Any]) -> str:
    counts = score_details.get("pair_counts") or {}
    if score_details.get("agreement_score") == 1.0:
        return "AGREEMENT"
    split_pairs = int(counts.get("same_existing_split_recommended") or 0)
    merge_pairs = int(counts.get("split_existing_same_recommended") or 0)
    if split_pairs and not merge_pairs:
        return "SUGGESTED_SPLIT"
    if merge_pairs and not split_pairs:
        return "SUGGESTED_MERGE"
    if split_pairs or merge_pairs:
        return "PARTIAL_OVERLAP"
    return "INSUFFICIENT_EVIDENCE"


def _partition_index(groups: list[list[str]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for i, group in enumerate(groups):
        for raw_id in group:
            index[str(raw_id)] = f"g{i}"
    return index
