"""Orchestration: enumerate deps -> rank by usage -> shortlist -> one Devin session.

Each run hands Devin a shortlist of the most-used (and not-recently-touched) libraries
and asks it to deep-dive one and make small, safe usage improvements. Status, the chosen
package, the resulting PR, and follow-up commits are synced back for reporting.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .devin import DevinApiError, DevinClient
from .github import GitHubClient, GitHubError, parse_opt_title
from .manifests import parse_manifest
from .metrics import Coverage, Report, build_report
from .models import Candidate, Dependency, OptimizeResult
from .prompts import build_optimization_prompt, build_optimization_title
from .selection import select_candidates
from .state import State
from .usage import UsageScanner

logger = logging.getLogger(__name__)


class Runner:
    def __init__(
        self,
        config: Config,
        *,
        devin: DevinClient | None = None,
        state: State | None = None,
        github: GitHubClient | None = None,
        usage: UsageScanner | None = None,
    ):
        self.config = config
        self.devin = devin or DevinClient(
            org_id=config.devin_org_id,
            api_base=config.devin_api_base,
            api_version=config.devin_api_version,
        )
        self.github = github or GitHubClient()
        self.usage = usage or UsageScanner(config)
        self.state = state or State.load(config.state_path)

    # -- discovery ---------------------------------------------------------

    def collect_dependencies(self) -> list[Dependency]:
        repo_root = Path(self.config.target_repo_path)
        deps: list[Dependency] = []
        for spec in self.config.manifests:
            deps.extend(
                parse_manifest(
                    repo_root,
                    spec.path,
                    include_optional=spec.include_optional,
                    include_dev=spec.include_dev,
                )
            )
        return self._apply_filters(deps)

    def _apply_filters(self, deps: list[Dependency]) -> list[Dependency]:
        ignore = {n.lower() for n in self.config.ignore}
        only = {n.lower() for n in self.config.only}
        result = []
        for dep in deps:
            lname = dep.name.lower()
            if lname in ignore:
                continue
            if only and lname not in only:
                continue
            result.append(dep)
        return result

    # -- selection ---------------------------------------------------------

    def shortlist(self, deps: list[Dependency] | None = None) -> list[Candidate]:
        """The candidates that would be put in front of Devin this run."""
        deps = deps if deps is not None else self.collect_dependencies()
        usage = self.usage.counts(deps)
        recently = self.state.recently_considered(self.config.cooldown_days)
        return select_candidates(
            deps, usage, recently, shortlist_size=self.config.shortlist_size
        )

    # -- triggering --------------------------------------------------------

    def optimize(self, *, dry_run: bool = False) -> OptimizeResult:
        deps = self.collect_dependencies()
        candidates = self.shortlist(deps)
        result = OptimizeResult(candidates=candidates)

        if not candidates:
            result.skipped_reason = "no candidate dependencies"
        elif dry_run:
            result.skipped_reason = "dry-run"
        else:
            self._trigger(candidates, result)

        if not dry_run:
            self.state.save()
            self._append_history(result, checked=len(deps))
        return result

    def _trigger(self, candidates: list[Candidate], result: OptimizeResult) -> None:
        prompt = build_optimization_prompt(candidates, self.config)
        try:
            session = self.devin.create_session(
                prompt,
                title=build_optimization_title(),
                tags=self.config.devin_tags,
                idempotent=self.config.devin_idempotent,
                max_acu_limit=self.config.devin_max_acu_limit,
            )
        except Exception as exc:  # noqa: BLE001 - surface any client error
            msg = f"failed to create Devin session: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            result.skipped_reason = msg
            return
        self.state.record_session(
            session.session_id, session.url, [c.dependency for c in candidates]
        )
        result.triggered = True
        result.session_id = session.session_id
        result.session_url = session.url

    def _append_history(self, result: OptimizeResult, *, checked: int) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "checked": checked,
            "shortlisted": len(result.candidates),
            "triggered": 1 if result.triggered else 0,
            "errors": len(result.errors),
        }
        path = Path(self.config.history_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    # -- reporting ---------------------------------------------------------

    def sync_statuses(self) -> int:
        """Refresh live status + PR + chosen package for every session. Returns count."""
        synced = 0
        for entry in self.state.sessions():
            try:
                status = self.devin.get_session(entry.session_id)
            except DevinApiError as exc:
                logger.warning("status sync failed for %s: %s", entry.session_id, exc)
                continue
            self.state.update_session_status(
                entry.session_id,
                status=status.status,
                status_detail=status.status_detail,
                pr_url=status.pr_url,
                pr_state=status.pr_state,
                acus_consumed=status.acus_consumed,
            )
            if status.pr_url:
                self._resolve_choice(entry.session_id, status.pr_url)
                self._sync_commits(entry.session_id, status.pr_url)
            synced += 1
        if synced:
            self.state.save()
        return synced

    def _resolve_choice(self, session_id: str, pr_url: str) -> None:
        """Read the PR title to learn which library Devin chose and mark it optimized."""
        try:
            title = self.github.pr_title(pr_url)
        except GitHubError as exc:
            logger.warning("pr title unavailable for %s: %s", session_id, exc)
            return
        name = parse_opt_title(title or "")
        if not name:
            return
        ecosystem = self._ecosystem_for(name)
        self.state.set_session_choice(session_id, ecosystem, name)
        self.state.mark_optimized(ecosystem, name)

    def _ecosystem_for(self, name: str) -> str:
        for dep in self.collect_dependencies():
            if dep.name.lower() == name.lower():
                return dep.ecosystem.value
        return "pypi"

    def _sync_commits(self, session_id: str, pr_url: str) -> None:
        try:
            stats = self.github.commit_stats(pr_url)
        except GitHubError as exc:
            logger.warning("commit stats unavailable for %s: %s", session_id, exc)
            return
        if stats is None:
            return
        self.state.update_session_commits(
            session_id,
            total_commits=stats.total_commits,
            followup_commits=stats.followup_commits,
            human_followup_commits=stats.human_followup_commits,
        )

    def load_history(self) -> list[dict]:
        path = Path(self.config.history_path)
        if not path.exists():
            return []
        records: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def build_report(self, *, coverage: bool = False) -> Report:
        cov: Coverage | None = None
        if coverage:
            total = len(self.collect_dependencies())
            cov = Coverage(
                total=total,
                optimized=self.state.optimized_count(),
                considered=self.state.considered_count(),
            )
        return build_report(
            self.state.sessions(),
            coverage=cov,
            history=self.load_history(),
        )
