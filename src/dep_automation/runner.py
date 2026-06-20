"""Orchestration: parse manifests -> find outdated deps -> trigger Devin sessions."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .devin import DevinApiError, DevinClient
from .github import GitHubClient, GitHubError
from .manifests import parse_manifest
from .metrics import Coverage, Report, build_report
from .models import (
    Dependency,
    OutdatedDependency,
    RunReport,
    TriggerResult,
)
from .prompts import build_prompt, build_title
from .registries import RegistryClient, RegistryError
from .state import State
from .versioning import classify_update, compare, satisfies

logger = logging.getLogger(__name__)


class Runner:
    def __init__(
        self,
        config: Config,
        *,
        registry: RegistryClient | None = None,
        devin: DevinClient | None = None,
        state: State | None = None,
        github: GitHubClient | None = None,
    ):
        self.config = config
        self.registry = registry or RegistryClient(allow_prerelease=config.allow_prerelease)
        self.devin = devin or DevinClient(
            org_id=config.devin_org_id,
            api_base=config.devin_api_base,
            api_version=config.devin_api_version,
        )
        self.github = github or GitHubClient()
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

    # -- outdated detection ------------------------------------------------

    def find_outdated(self, report: RunReport | None = None) -> list[OutdatedDependency]:
        report = report or RunReport()
        outdated: list[OutdatedDependency] = []
        for dep in self.collect_dependencies():
            report.checked += 1
            try:
                latest = self.registry.latest_version(dep.ecosystem, dep.name)
            except RegistryError as exc:
                msg = f"{dep.name} ({dep.ecosystem.value}): {exc}"
                logger.warning("registry lookup failed: %s", msg)
                report.errors.append(msg)
                continue
            od = self._evaluate(dep, latest)
            if od:
                outdated.append(od)
        report.outdated = outdated
        return outdated

    def _evaluate(self, dep: Dependency, latest: str) -> OutdatedDependency | None:
        in_range = satisfies(dep.ecosystem, latest, dep.constraint) if dep.constraint else True
        newer = True
        if dep.current_version:
            newer = compare(dep.ecosystem, latest, dep.current_version) > 0

        requires_change = not in_range
        if self.config.trigger_policy == "out-of-range":
            should_flag = requires_change
        else:  # "any-newer"
            should_flag = newer or requires_change

        if not should_flag:
            return None
        return OutdatedDependency(
            dependency=dep,
            latest_version=latest,
            update_kind=classify_update(dep.ecosystem, dep.current_version, latest),
            requires_manifest_change=requires_change,
        )

    # -- triggering --------------------------------------------------------

    def run(self, *, dry_run: bool = False) -> RunReport:
        report = RunReport()
        outdated = self.find_outdated(report)
        triggered_count = 0
        for od in outdated:
            if triggered_count >= self.config.max_sessions_per_run:
                report.results.append(
                    TriggerResult(
                        od, triggered=False, skipped_reason="max_sessions_per_run reached"
                    )
                )
                continue
            result = self._maybe_trigger(od, dry_run=dry_run)
            report.results.append(result)
            if result.triggered:
                triggered_count += 1

        if not dry_run:
            self.state.save()
            self._append_history(report)
        return report

    def _append_history(self, report: RunReport) -> None:
        """Append a one-line record of this run for throughput-over-time reporting."""
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "checked": report.checked,
            "outdated": len(report.outdated),
            "triggered": len(report.triggered),
            "errors": len(report.errors),
        }
        path = Path(self.config.history_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    # -- reporting ---------------------------------------------------------

    def sync_statuses(self) -> int:
        """Refresh live status + PR info for every tracked session. Returns count synced."""
        synced = 0
        for entry in self.state.entries():
            if not entry.session_id:
                continue
            try:
                status = self.devin.get_session(entry.session_id)
            except DevinApiError as exc:
                logger.warning("status sync failed for %s: %s", entry.name, exc)
                continue
            self.state.update_status(
                entry.ecosystem,
                entry.name,
                status=status.status,
                status_detail=status.status_detail,
                pr_url=status.pr_url,
                pr_state=status.pr_state,
                acus_consumed=status.acus_consumed,
            )
            if status.pr_url:
                self._sync_commits(entry.ecosystem, entry.name, status.pr_url)
            synced += 1
        if synced:
            self.state.save()
        return synced

    def _sync_commits(self, ecosystem: str, name: str, pr_url: str) -> None:
        """Best-effort: record how many follow-up commits the PR needed (rework signal)."""
        try:
            stats = self.github.commit_stats(pr_url)
        except GitHubError as exc:
            logger.warning("commit stats unavailable for %s: %s", name, exc)
            return
        if stats is None:
            return
        self.state.update_commits(
            ecosystem,
            name,
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
            run_report = RunReport()
            outdated = self.find_outdated(run_report)
            cov = Coverage(checked=run_report.checked, outdated=len(outdated))
        return build_report(
            self.state.entries(),
            coverage=cov,
            history=self.load_history(),
        )

    def _maybe_trigger(self, od: OutdatedDependency, *, dry_run: bool) -> TriggerResult:
        if self.state.already_triggered(od.ecosystem, od.name, od.latest_version):
            return TriggerResult(
                od, triggered=False, skipped_reason="already triggered for this version"
            )

        if dry_run:
            return TriggerResult(od, triggered=False, skipped_reason="dry-run")

        prompt = build_prompt(od, self.config)
        try:
            session = self.devin.create_session(
                prompt,
                title=build_title(od),
                tags=self.config.devin_tags,
                idempotent=self.config.devin_idempotent,
                max_acu_limit=self.config.devin_max_acu_limit,
            )
        except Exception as exc:  # noqa: BLE001 - surface any client error per-dependency
            msg = f"failed to create Devin session for {od.name}: {exc}"
            logger.error(msg)
            return TriggerResult(od, triggered=False, skipped_reason=msg)

        self.state.record(
            od.ecosystem,
            od.name,
            od.latest_version,
            session.session_id,
            session.url,
            update_kind=od.update_kind.value,
        )
        return TriggerResult(
            od,
            triggered=True,
            session_id=session.session_id,
            session_url=session.url,
        )
