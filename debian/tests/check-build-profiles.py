#!/usr/bin/env python3
"""Check combined package profiles against dpkg and exercise native dispatch.

Run from any directory with Python, make and dpkg-dev installed. No SDK or GPU
is needed; compiler invocations are not part of these packaging checks.
"""

import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PREFIX = "pkg.tllama-server."
PACKAGES = {
    "cpu": {"tllama-server", "tllama-server-core", "tllama-server-backend-cpu"},
    "vulkan": {"tllama-server-backend-vulkan"},
    "rocm": {"tllama-server-backend-rocm10.1"},
    "cuda12.4": {"tllama-server-backend-cuda12.4"},
    "cuda12.9": {"tllama-server-backend-cuda12.9"},
    "cuda13.3": {"tllama-server-backend-cuda13.3"},
    "sycl": {"tllama-server-backend-sycl"},
}
DEPENDENCIES = {
    "cpu": {"libssl-dev", "libopenblas-dev"},
    "vulkan": {"libvulkan-dev", "glslc", "spirv-headers"},
    "rocm": {"amdrocm-core-sdk10.1"},
    "cuda12.4": {"nvidia-cuda-toolkit"},
    "cuda12.9": {"cuda-toolkit-12-9"},
    "cuda13.3": {"cuda-toolkit-13-3"},
    "sycl": {
        "intel-oneapi-compiler-dpcpp-cpp", "intel-oneapi-mkl-sycl-devel",
        "intel-oneapi-dnnl-devel", "intel-oneapi-tbb-devel", "libze-dev",
    },
}
GOALS = (
    "override_dh_auto_configure", "override_dh_auto_build",
    "override_dh_auto_install", "override_dh_shlibdeps", "override_dh_auto_clean",
)


def run_make(root, arguments, profiles=(), check=True):
    env = os.environ.copy()
    # Do not inherit an enclosing make jobserver or the caller's profile choice.
    env.pop("MAKEFLAGS", None)
    env.pop("MFLAGS", None)
    env.pop("MAKEOVERRIDES", None)
    env["DEB_BUILD_PROFILES"] = " ".join(profiles)
    return subprocess.run(
        ["make", "--no-print-directory", "--silent", *arguments],
        cwd=root, env=env, text=True, capture_output=True, check=check,
    )


def check_profile_matrix():
    components = list(PACKAGES)
    cases = [([], components), (["nocheck"], components)]
    for size in range(1, len(components) + 1):
        for selected in itertools.combinations(components, size):
            cases.append(([PREFIX + item + "-only" for item in selected], list(selected)))
    cases.extend((([PREFIX + "all"], components),
                  ([PREFIX + "all", PREFIX + "cpu-only", "nocheck"], components)))
    perl = r'''
use strict;
use warnings;
use JSON::PP;
use Dpkg::Control::Info;
use Dpkg::BuildProfiles qw(parse_build_profiles evaluate_restriction_formula);
use Dpkg::Deps qw(deps_parse);
my $cases = decode_json(do { local $/; <STDIN> });
my $control = Dpkg::Control::Info->new();
my @results;
for my $profiles (@$cases) {
    my @packages;
    for my $pkg ($control->get_packages()) {
        my @formula = parse_build_profiles($pkg->{'Build-Profiles'});
        push @packages, $pkg->{Package} if evaluate_restriction_formula(\@formula, $profiles);
    }
    my @fields;
    for my $field ('Build-Depends', 'Build-Conflicts') {
        my $deps = deps_parse($control->get_source()->{$field},
            build_dep => 1, reduce_profiles => 1, build_profiles => $profiles);
        die "Cannot parse $field" unless defined $deps;
        push @fields, $deps->output();
    }
    push @results, { packages => \@packages, depends => $fields[0], conflicts => $fields[1] };
}
print encode_json(\@results);
'''
    result = subprocess.run(
        ["perl", "-e", perl], cwd=ROOT, text=True, capture_output=True, check=True,
        input=json.dumps([profiles for profiles, _ in cases]),
    )
    for (profiles, expected), actual in zip(cases, json.loads(result.stdout), strict=True):
        selected = run_make(ROOT, [
            "-f", "debian/rules", "--eval", "profile-selection:;@echo $(COMPONENTS)",
            "profile-selection",
        ], profiles).stdout.split()
        assert selected == expected, (profiles, selected, expected)
        expected_packages = set().union(*(PACKAGES[item] for item in expected))
        assert set(actual["packages"]) == expected_packages, (profiles, actual)
        expected_deps = {"debhelper-compat", "cmake", "ninja-build", "pkgconf", "python3"}
        expected_deps.update(set().union(*(DEPENDENCIES[item] for item in expected)))
        actual_deps = {dep.strip().split()[0] for dep in actual["depends"].split(",")}
        assert actual_deps == expected_deps, (profiles, actual_deps, expected_deps)
        assert actual["conflicts"] == ("libamdhip64-dev" if "rocm" in expected else "")
    invalid = run_make(ROOT, ["-f", "debian/rules", "override_dh_auto_test"],
                       [PREFIX + "typo"], check=False)
    assert invalid.returncode != 0 and "unknown tllama-server build profile" in invalid.stderr
    return len(cases)


def check_dispatch():
    with tempfile.TemporaryDirectory(prefix="tllama-profile-check-") as directory:
        root = Path(directory)
        (root / "debian").mkdir()
        shutil.copy(ROOT / "debian/rules", root / "debian/rules")
        (root / "debian/build-component.mk").write_text(
            ".PHONY: " + " ".join(GOALS) + "\n" + " ".join(GOALS) + ":\n"
            "\t@printf 'CALL|%s|%s\\n' '$@' '$(DEB_BUILD_PROFILES)'\n"
            "\t@test '$(filter $(FAIL_PROFILE),$(DEB_BUILD_PROFILES))' = ''\n"
        )
        for profiles in ([], ["nocheck"], [PREFIX + "all", "nocheck"]):
            other = "nocheck " if "nocheck" in profiles else ""
            for goal in GOALS:
                result = run_make(root, ["-f", "debian/rules", goal], profiles)
                expected = [f"CALL|{goal}|{other}{PREFIX}{item}-only" for item in PACKAGES]
                assert result.stdout.splitlines() == expected, result
        failed = run_make(root, ["-f", "debian/rules", GOALS[1],
                                "FAIL_PROFILE=" + PREFIX + "rocm-only"], check=False)
        assert failed.returncode != 0
        assert len(failed.stdout.splitlines()) == 3, failed

        # Exercise the real metadata writer, including each CUDA driver floor.
        shutil.copy(ROOT / "debian/build-component.mk", root / "debian/build-component.mk")
        for name in ("changelog", "control"):
            shutil.copy(ROOT / "debian" / name, root / "debian" / name)
        for version, minimum in (("12.4", "525.60.13"), ("12.9", "525.60.13"), ("13.3", "580")):
            run_make(root, ["-f", "debian/build-component.mk", "override_dh_makeshlibs"],
                     [PREFIX + "cuda" + version + "-only"])
            metadata = (root / "debian/shlibs.local").read_text()
            assert f"libcuda 1 libcuda1 (>= {minimum})\n" in metadata
            assert "libggml-base 0 tllama-server-core (= 0.6.0~dev+" in metadata
        for component, expected in (("cpu", "hardening=+all"),
                                    ("sycl", "hardening=+all optimize=-lto")):
            flags = run_make(root, ["-f", "debian/build-component.mk", "--eval",
                                   "print-flags:;@echo $(DEB_BUILD_MAINT_OPTIONS)", "print-flags"],
                             [PREFIX + component + "-only"])
            assert flags.stdout.strip() == expected, flags


if __name__ == "__main__":
    count = check_profile_matrix()
    check_dispatch()
    print(f"Passed {count} profile cases, native dispatch, failure propagation and SDK metadata checks")
