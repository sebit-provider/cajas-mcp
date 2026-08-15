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

    async def recommend(self, raw_entries: list[dict[str, Any] | RawEntry], *, include_external_context: bool) -> dict[str, Any]:
        entries = [entry if isinstance(entry, RawEntry) else RawEntry.model_validate(entry) for entry in raw_entries]
        if not entries:
            return {"candidates": [], "historical_pattern": {"available": False, "reason": "No RAW entries supplied."}}
        if len(entries) == 1:
            candidate = self._candidate_for_group(entries, external=ExternalContextSummary(available=False, used=False))
            candidate.warnings.append("Only one RAW entry was supplied; recommendation cannot compare related entries.")
            return {"candidates": [candidate.model_dump()], "historical_pattern": {"available": False, "reason": "Not implemented in public MCP PoC."}}

        pair_scores = self._pair_scores(entries)
        groups = self._cluster(entries, pair_scores)
        candidates: list[AssemblyCandidate] = []
        for group in groups:
            preliminary = self._candidate_for_group(group, external=ExternalContextSummary(available=False, used=False))
            external = await self._maybe_external_context(group, preliminary.score, include_external_context)
            candidates.append(self._candidate_for_group(group, external=external))
        candidates.sort(key=lambda item: item.score, reverse=True)
        return {
            "candidates": [candidate.model_dump() for candidate in candidates],
            "historical_pattern": {
                "available": False,
                "score": 0.0,
                "reason": "No read-only CAJAS API currently exposes historical raw_group/raw_group_items patterns to the public MCP boundary.",
            },
        }

    def _pair_scores(self, entries: list[RawEntry]) -> dict[tuple[str, str], float]:
        scores: dict[tuple[str, str], float] = {}
        for left, right in itertools.combinations(entries, 2):
            signals = self._signals_for_group([left, right], external=ExternalContextSummary(available=False, used=False))
            scores[(left.id, right.id)] = self._weighted_score(signals)
        return scores

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

    def _candidate_for_group(self, entries: list[RawEntry], *, external: ExternalContextSummary) -> AssemblyCandidate:
        signals = self._signals_for_group(entries, external=external)
        score = self._weighted_score(signals)
        raw_ids = [entry.id for entry in entries]
        digest = hashlib.sha1(",".join(sorted(raw_ids)).encode("utf-8")).hexdigest()[:12]
        reasons = self._reasons(signals)
        warnings = self._warnings(entries, external)
        return AssemblyCandidate(
            candidate_id=f"rec_{digest}",
            raw_entry_ids=raw_ids,
            score=round(score, 4),
            signals=signals,
            reasons=reasons,
            warnings=warnings,
            external_context_used=external.used,
            mutation=False,
        )

    def _signals_for_group(self, entries: list[RawEntry], *, external: ExternalContextSummary) -> list[Signal]:
        return [
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

    def _weighted_score(self, signals: list[Signal]) -> float:
        by_type = {signal.type: signal.score for signal in signals}
        weighted = sum(by_type.get(name, 0.0) * weight for name, weight in self.weights.__dict__.items())
        return max(0.0, min(1.0, weighted / self.weights.total))

    async def _maybe_external_context(
        self,
        entries: list[RawEntry],
        preliminary_score: float,
        include_external_context: bool,
    ) -> ExternalContextSummary:
        if not include_external_context or self.external_provider is None:
            return ExternalContextSummary(available=False, used=False)
        query_text = " ".join(" ".join([entry.description or "", entry.memo or "", entry.event_hint_key or ""]) for entry in entries)
        query = sanitize_external_query(query_text)
        if not query:
            return ExternalContextSummary(available=False, used=False, warning="No sanitized external query terms available.")
        should_use = preliminary_score < self.external_trigger_threshold or self._has_unknown_operational_terms(query)
        if not should_use:
            return ExternalContextSummary(available=True, used=False, warning="Internal confidence was sufficient; external context not used.")
        try:
            results = await self.external_provider.search(f"{query} operational relationship", limit=5)
            patterns = await self.external_provider.extract_work_patterns(results)
        except Exception as exc:
            return ExternalContextSummary(available=False, used=False, warning=f"External provider unavailable: {type(exc).__name__}")
        if not results:
            return ExternalContextSummary(available=False, used=True, warning="External provider returned no usable results.")
        score = min(0.6, 0.12 + 0.08 * min(len(results), 5) + 0.04 * min(len(patterns), 3))
        return ExternalContextSummary(
            available=True,
            used=True,
            score=round(score, 4),
            results=[result.__dict__ for result in results[:5]],
        )

    @staticmethod
    def _has_unknown_operational_terms(query: str) -> bool:
        return any(token in query.lower() for token in ("aws", "azure", "gcp", "migration", "implementation", "gateway", "subscription"))

    @staticmethod
    def _reasons(signals: list[Signal]) -> list[str]:
        strong = [signal for signal in signals if signal.available and signal.score >= 0.7 and signal.type != "external_context"]
        return [signal.explanation for signal in strong[:5] if signal.explanation]

    @staticmethod
    def _warnings(entries: list[RawEntry], external: ExternalContextSummary) -> list[str]:
        warnings: list[str] = []
        if any(str(entry.status or "").lower() == "assembled" for entry in entries):
            warnings.append("One or more RAW entries are already assembled; recommendation remains non-binding.")
        if external.warning:
            warnings.append(external.warning)
        if external.used:
            warnings.append("External community context is untrusted and is not accounting evidence.")
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

