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
        "intel-oneapi-compiler-dpcpp-cpp-2026.2", "intel-oneapi-mkl-sycl-devel-2026.2",
        "intel-oneapi-dnnl-devel-2026.1", "intel-oneapi-tbb-devel-2023.2",
        "intel-oneapi-openmp-2026.2", "libze-dev",
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
        package_version = subprocess.check_output(
            ["dpkg-parsechangelog", "--show-field", "Version"], cwd=root, text=True).strip()
        for version, minimum in (("12.4", "525.60.13"), ("12.9", "525.60.13"), ("13.3", "580")):
            run_make(root, ["-f", "debian/build-component.mk", "override_dh_makeshlibs"],
                     [PREFIX + "cuda" + version + "-only"])
            metadata = (root / "debian/shlibs.local").read_text()
            assert f"libcuda 1 libcuda1 (>= {minimum})\n" in metadata
            assert f"libggml-base 1 tllama-server-core (= {package_version})\n" in metadata
        for component, expected in (("cpu", "hardening=+all"),
                                    ("sycl", "hardening=+all optimize=-lto")):
            flags = run_make(root, ["-f", "debian/build-component.mk", "--eval",
                                   "print-flags:;@echo $(DEB_BUILD_MAINT_OPTIONS)", "print-flags"],
                             [PREFIX + component + "-only"])
            assert flags.stdout.strip() == expected, flags


def check_sycl_sdk_selection():
    # Exercise the actual make recipe with coinstalled SDK series and a hostile
    # shell environment. The fixture performs no compiler or GPU qualification.
    with tempfile.TemporaryDirectory(prefix="tllama-sycl-sdk-") as directory:
        root = Path(directory)
        (root / "debian").mkdir()
        for name in ("build-component.mk", "control", "changelog"):
            shutil.copy(ROOT / "debian" / name, root / "debian" / name)
        sdk = root / "oneapi"
        for name in ("compiler/2026.2/lib/libiomp5.so",
                     "mkl/2026.2/lib/cmake/mkl/MKLConfig.cmake",
                     "dnnl/2026.1/lib/cmake/dnnl/dnnl-config.cmake",
                     "tbb/2023.2/lib/cmake/tbb/TBBConfig.cmake",
                     "gcc/crtbeginS.o", "gcc/libstdc++.so"):
            path = sdk / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        tools = root / "bin"
        tools.mkdir()
        def executable(path, content):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            path.chmod(0o755)
        for compiler in ("icx", "icpx"):
            executable(sdk / "compiler/2026.2/bin" / compiler, "#!/bin/sh\nprintf 'fixture compiler\\n'\n")
        executable(tools / "pkgconf", "#!/bin/sh\nprintf '1.20.6\\n'\n")
        executable(tools / "dpkg-query", "#!/usr/bin/env python3\nimport sys\n"
                   "assert sys.argv[1] == '-W'\n"
                   "assert sys.argv[2] == r'-f=${binary:Package}\\t${Version}\\n', sys.argv\n"
                   "print('fixture packages recorded')\n")
        executable(tools / "dh_auto_configure", "#!/usr/bin/env python3\nimport json, os, sys\n"
                   "from pathlib import Path\n"
                   "Path('configured.json').write_text(json.dumps({'args':sys.argv[1:],"
                   "'libs':os.environ['LD_LIBRARY_PATH'], 'mkl':os.environ['MKLROOT']}))\n")
        env = os.environ.copy()
        for key in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"):
            env.pop(key, None)
        env.update(PATH=str(tools) + os.pathsep + env["PATH"],
                   DEB_BUILD_PROFILES=PREFIX + "sycl-only",
                   LD_LIBRARY_PATH="/foreign-sdk/lib", MKLROOT="/foreign-sdk/mkl")
        result = subprocess.run(["make", "--silent", "-f", "debian/build-component.mk",
                        "override_dh_auto_configure", "ONEAPI_ROOT=" + str(sdk),
                        "GNU_GCC_INSTALL_DIR=" + str(sdk / "gcc")],
                       cwd=root, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        configured = json.loads((root / "configured.json").read_text())
        assert configured["mkl"] == str(sdk / "mkl/2026.2")
        assert "/foreign-sdk" not in configured["libs"]
        assert "latest" not in configured["libs"]
        assert "-DMKL_THREADING=intel_thread" in configured["args"]
        assert "-DOMP_LIBRARY=" + str(sdk / "compiler/2026.2/lib/libiomp5.so") in configured["args"]
        assert "-DDNNL_DIR=" + str(sdk / "dnnl/2026.1/lib/cmake/dnnl") in configured["args"]
        versions = (root / "build-debian-sycl/oneapi-build-versions.txt").read_text()
        assert "fixture packages recorded" in versions and "fixture compiler" in versions
        assert "MKL_THREADING=intel_thread" in versions and "1.20.6" in versions


if __name__ == "__main__":
    count = check_profile_matrix()
    check_dispatch()
    check_sycl_sdk_selection()
    print(f"Passed {count} profile cases, native dispatch, failure propagation and SDK selection/metadata checks")
