"""Deterministic tests for the default system metric sampler."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import atlas_richie.sentinel.ports.system_metric_sampler as sampler_module
from atlas_richie.sentinel.ports.system_metric_sampler import (
    DefaultSystemMetricSampler,
    SystemSnapshot,
)
from atlas_richie.sentinel.primitives.clock import ManualClock


class DefaultSystemMetricSamplerTest(unittest.TestCase):
    """System-rate windows use monotonic time while samples retain wall time."""

    def test_process_rss_is_reported_in_bytes_on_linux(self) -> None:
        with TemporaryDirectory() as directory:
            statm = Path(directory) / "statm"
            statm.write_text("1024 12 0 0 0 0 0\n", encoding="ascii")
            with (
                patch.object(sampler_module, "_PROC_SELF_STATM", statm),
                patch.object(sampler_module.os, "sysconf", return_value=4096),
            ):
                snapshot = DefaultSystemMetricSampler().sample()

        self.assertEqual(snapshot.memory_bytes, 12 * 4096)

    def test_process_rss_is_unavailable_when_procfs_data_is_invalid(self) -> None:
        with TemporaryDirectory() as directory:
            statm = Path(directory) / "statm"
            statm.write_text("malformed\n", encoding="ascii")
            with (
                patch.object(sampler_module, "_PROC_SELF_STATM", statm),
                patch.object(sampler_module.os, "sysconf", return_value=4096),
            ):
                snapshot = DefaultSystemMetricSampler().sample()

        self.assertIsNone(snapshot.memory_bytes)

    def test_system_snapshot_preserves_existing_positional_constructor(self) -> None:
        snapshot = SystemSnapshot(None, None, None, 0.0, None, 123, True)

        self.assertTrue(snapshot.degraded)
        self.assertIsNone(snapshot.memory_bytes)
        self.assertIsNone(snapshot.memory_ratio)

    def test_system_snapshot_rejects_invalid_measurements(self) -> None:
        fields = (
            "cpu_usage",
            "load",
            "event_loop_lag_ms",
            "in_flight_qps",
            "completed_qps",
            "memory_ratio",
        )
        for field_name in fields:
            for invalid_value in (-1, float("inf"), float("nan"), True, 10**1000):
                with (
                    self.subTest(field=field_name, value=invalid_value),
                    self.assertRaises(ValueError),
                ):
                    SystemSnapshot(
                        cpu_usage=invalid_value if field_name == "cpu_usage" else None,
                        load=invalid_value if field_name == "load" else None,
                        event_loop_lag_ms=(
                            invalid_value if field_name == "event_loop_lag_ms" else None
                        ),
                        in_flight_qps=(
                            invalid_value if field_name == "in_flight_qps" else None
                        ),
                        completed_qps=(
                            invalid_value if field_name == "completed_qps" else None
                        ),
                        at_ns=0,
                        memory_ratio=(
                            invalid_value if field_name == "memory_ratio" else None
                        ),
                    )

    def test_system_snapshot_validates_timestamps_flags_and_memory_bytes(self) -> None:
        valid = SystemSnapshot(
            cpu_usage=1,
            load=0,
            event_loop_lag_ms=0,
            in_flight_qps=0,
            completed_qps=0,
            at_ns=0,
            memory_ratio=1.2,
            memory_bytes=0,
        )
        self.assertEqual(valid.memory_ratio, 1.2)

        invalid_snapshots = (
            {"at_ns": -1},
            {"at_ns": True},
            {"degraded": 1},
            {"memory_bytes": -1},
            {"memory_bytes": True},
            {"memory_bytes": 1.5},
            {"cpu_usage": 1.01},
        )
        for changes in invalid_snapshots:
            with self.subTest(changes=changes):
                fields = {
                    "cpu_usage": None,
                    "load": None,
                    "event_loop_lag_ms": None,
                    "in_flight_qps": None,
                    "completed_qps": None,
                    "at_ns": 0,
                    "degraded": False,
                    "memory_bytes": None,
                    "memory_ratio": None,
                }
                fields.update(changes)
                with self.assertRaises((TypeError, ValueError)):
                    SystemSnapshot(**fields)

    def test_memory_ratio_uses_tightest_visible_cgroup_v2_limit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mount = root / "cgroup"
            parent = mount / "workload"
            process = parent / "worker"
            process.mkdir(parents=True)
            (mount / "memory.max").write_text("8000", encoding="ascii")
            (parent / "memory.max").write_text("5000", encoding="ascii")
            (process / "memory.max").write_text("max", encoding="ascii")
            cgroup_file = root / "proc-cgroup"
            cgroup_file.write_text("0::/workload/worker\n", encoding="ascii")
            mountinfo_file = root / "mountinfo"
            mountinfo_file.write_text(
                f"29 23 0:26 / {mount} rw - cgroup2 cgroup rw\n",
                encoding="ascii",
            )
            statm = root / "statm"
            statm.write_text("1024 12 0 0 0 0 0\n", encoding="ascii")

            with (
                patch.object(sampler_module, "_PROC_SELF_CGROUP", cgroup_file),
                patch.object(sampler_module, "_PROC_SELF_MOUNTINFO", mountinfo_file),
                patch.object(sampler_module, "_PROC_SELF_STATM", statm),
                patch.object(sampler_module.os, "sysconf", return_value=100),
                patch.object(
                    sampler_module, "_CGROUP_V2_CPU_MAX", root / "missing-cpu"
                ),
                patch.object(
                    sampler_module, "_CGROUP_V1_CPU_QUOTA", root / "missing-quota"
                ),
                patch.object(
                    sampler_module, "_CGROUP_V1_CPU_PERIOD", root / "missing-period"
                ),
            ):
                snapshot = DefaultSystemMetricSampler().sample()

        self.assertEqual(snapshot.memory_bytes, 1200)
        self.assertEqual(snapshot.memory_ratio, 1200 / 5000)

    def test_memory_ratio_is_unavailable_without_a_verified_finite_limit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mount = root / "cgroup"
            mount.mkdir()
            (mount / "memory.max").write_text("max", encoding="ascii")
            cgroup_file = root / "proc-cgroup"
            cgroup_file.write_text("0::/\n", encoding="ascii")
            mountinfo_file = root / "mountinfo"
            mountinfo_file.write_text(
                f"29 23 0:26 / {mount} rw - cgroup2 cgroup rw\n",
                encoding="ascii",
            )
            with (
                patch.object(sampler_module, "_PROC_SELF_CGROUP", cgroup_file),
                patch.object(sampler_module, "_PROC_SELF_MOUNTINFO", mountinfo_file),
            ):
                self.assertIsNone(sampler_module._read_effective_memory_limit_bytes())

    def test_memory_limit_supports_cgroup_v1_and_ignores_unlimited_sentinel(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mount = root / "memory"
            parent = mount / "workload"
            process = parent / "worker"
            process.mkdir(parents=True)
            (mount / "memory.limit_in_bytes").write_text("12000", encoding="ascii")
            (parent / "memory.limit_in_bytes").write_text("7000", encoding="ascii")
            (process / "memory.limit_in_bytes").write_text(
                str(sampler_module._CGROUP_V1_MEMORY_LIMIT_UNLIMITED_THRESHOLD_BYTES),
                encoding="ascii",
            )
            cgroup_file = root / "proc-cgroup"
            cgroup_file.write_text("7:memory:/workload/worker\n", encoding="ascii")
            mountinfo_file = root / "mountinfo"
            mountinfo_file.write_text(
                f"29 23 0:26 / {mount} rw - cgroup cgroup rw,memory\n",
                encoding="ascii",
            )

            with (
                patch.object(sampler_module, "_PROC_SELF_CGROUP", cgroup_file),
                patch.object(sampler_module, "_PROC_SELF_MOUNTINFO", mountinfo_file),
            ):
                limit = sampler_module._read_effective_memory_limit_bytes()

        self.assertEqual(limit, 7000)

    def test_completed_qps_uses_injected_monotonic_clock(self) -> None:
        clock = ManualClock()
        sampler = DefaultSystemMetricSampler(clock=clock)

        initial = sampler.sample()
        self.assertIsNone(initial.completed_qps)
        self.assertGreater(initial.at_ns, 0)

        sampler.record_complete(success=True)
        sampler.record_complete(success=True)
        sampler.record_complete(success=False)
        clock.advance(2.0)

        first_rate = sampler.sample()
        self.assertEqual(first_rate.completed_qps, 1.0)
        self.assertEqual(first_rate.in_flight_qps, 0.0)

        sampler.record_complete(success=True)
        sampler.record_complete(success=True)
        clock.advance(1.0)

        next_rate = sampler.sample()
        self.assertEqual(next_rate.completed_qps, 2.0)

    def test_cpu_usage_is_normalized_by_cgroup_v2_quota(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cpu_max = root / "cpu.max"
            cpu_max.write_text("50000 100000", encoding="ascii")
            clock = ManualClock()
            sampler = DefaultSystemMetricSampler(clock=clock)

            with (
                patch.object(sampler_module, "_CGROUP_V2_CPU_MAX", cpu_max),
                patch.object(
                    sampler_module,
                    "_CGROUP_V1_CPU_QUOTA",
                    root / "missing-quota",
                ),
                patch.object(
                    sampler_module,
                    "_CGROUP_V1_CPU_PERIOD",
                    root / "missing-period",
                ),
                patch.object(
                    sampler_module.time,
                    "process_time_ns",
                    side_effect=(0, 250_000_000),
                ),
            ):
                first = sampler.sample()
                clock.advance(1.0)
                second = sampler.sample()

        self.assertIsNone(first.cpu_usage)
        self.assertEqual(second.cpu_usage, 0.5)

    def test_cpu_usage_uses_cgroup_v1_quota_when_v2_is_absent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            quota = root / "cpu.cfs_quota_us"
            period = root / "cpu.cfs_period_us"
            quota.write_text("25000", encoding="ascii")
            period.write_text("100000", encoding="ascii")
            clock = ManualClock()
            sampler = DefaultSystemMetricSampler(clock=clock)

            with (
                patch.object(sampler_module, "_CGROUP_V2_CPU_MAX", root / "missing-v2"),
                patch.object(sampler_module, "_CGROUP_V1_CPU_QUOTA", quota),
                patch.object(sampler_module, "_CGROUP_V1_CPU_PERIOD", period),
                patch.object(
                    sampler_module.time,
                    "process_time_ns",
                    side_effect=(0, 125_000_000),
                ),
            ):
                sampler.sample()
                clock.advance(1.0)
                snapshot = sampler.sample()

        self.assertEqual(snapshot.cpu_usage, 0.5)

    def test_cpu_usage_is_unavailable_without_a_verified_quota(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cpu_max = root / "cpu.max"
            cpu_max.write_text("max 100000", encoding="ascii")
            clock = ManualClock()
            sampler = DefaultSystemMetricSampler(clock=clock)

            with (
                patch.object(sampler_module, "_CGROUP_V2_CPU_MAX", cpu_max),
                patch.object(
                    sampler_module,
                    "_CGROUP_V1_CPU_QUOTA",
                    root / "missing-quota",
                ),
                patch.object(
                    sampler_module,
                    "_CGROUP_V1_CPU_PERIOD",
                    root / "missing-period",
                ),
                patch.object(
                    sampler_module.time,
                    "process_time_ns",
                    side_effect=(0, 500_000_000),
                ),
            ):
                sampler.sample()
                clock.advance(1.0)
                snapshot = sampler.sample()

        self.assertIsNone(snapshot.cpu_usage)

    def test_cpu_usage_respects_a_narrower_process_cpu_affinity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cpu_max = root / "cpu.max"
            cpu_max.write_text("400000 100000", encoding="ascii")
            clock = ManualClock()
            sampler = DefaultSystemMetricSampler(clock=clock)

            with (
                patch.object(sampler_module, "_CGROUP_V2_CPU_MAX", cpu_max),
                patch.object(
                    sampler_module,
                    "_CGROUP_V1_CPU_QUOTA",
                    root / "missing-quota",
                ),
                patch.object(
                    sampler_module,
                    "_CGROUP_V1_CPU_PERIOD",
                    root / "missing-period",
                ),
                patch.object(
                    sampler_module.os,
                    "sched_getaffinity",
                    return_value={0, 1},
                    create=True,
                ),
                patch.object(
                    sampler_module.time,
                    "process_time_ns",
                    side_effect=(0, 1_500_000_000),
                ),
            ):
                sampler.sample()
                clock.advance(1.0)
                snapshot = sampler.sample()

        self.assertEqual(snapshot.cpu_usage, 0.75)


if __name__ == "__main__":
    unittest.main()
