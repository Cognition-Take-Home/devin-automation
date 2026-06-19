"""Orchestration: parse manifests -> find outdated deps -> trigger Devin sessions."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Config
from .devin import DevinClient
from .manifests import parse_manifest
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
    ):
        self.config = config
        self.registry = registry or RegistryClient(allow_prerelease=config.allow_prerelease)
        self.devin = devin or DevinClient(
            org_id=config.devin_org_id,
            api_base=config.devin_api_base,
            api_version=config.devin_api_version,
        )
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
        return report

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
            od.ecosystem, od.name, od.latest_version, session.session_id, session.url
        )
        return TriggerResult(
            od,
            triggered=True,
            session_id=session.session_id,
            session_url=session.url,
        )
