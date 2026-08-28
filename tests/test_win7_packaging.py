import ast
import json
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import win7_portable
from tools.win7_portable import (
    APP_VERSION,
    EXE_NAME,
    PORTABLE_NAME,
    HostFacts,
    PackagingError,
    RuntimeFile,
    UCRT_FILE_VERSION,
    VC_RUNTIME_FILE_VERSION,
    audit_pe_dependency_closure,
    audit_pyinstaller_provenance,
    audit_portable_tree,
    collect_app_local_runtime,
    create_portable_zip,
    create_wheelhouse_lock,
    forbidden_binary_reason,
    forbidden_binary_provenance_signatures,
    read_pe_machine,
    run_packaged_executable_checks,
    normalize_packaged_vc_runtime,
    read_pe_imports,
    sha256_file,
    validate_build_host,
    validate_wheelhouse,
    write_release_metadata,
    write_acceptance_template,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _win7_host(executable=r"C:\Python38\python.exe"):
    return HostFacts(
        system="Windows",
        windows_release="7",
        windows_version="6.1.7601",
        service_pack="SP1",
        machine="AMD64",
        pointer_bits=64,
        python_version=(3, 8, 10),
        executable=executable,
    )


def _write_runtime_roots(base):
    ucrt_root = base / "ucrt"
    vc_root = base / "vc142"
    ucrt_root.mkdir()
    vc_root.mkdir()
    for name in win7_portable.REQUIRED_UCRT_FILES:
        (ucrt_root / name).write_bytes(_minimal_pe())
    for name in win7_portable.REQUIRED_VC_FILES:
        (vc_root / name).write_bytes(_minimal_pe())
    return ucrt_root, vc_root


def _runtime_version_reader(path):
    name = Path(path).name.casefold()
    if (
        name == "ucrtbase.dll"
        or name.startswith("api-ms-win-crt-")
        or name.startswith("api-ms-win-core-")
    ):
        return UCRT_FILE_VERSION
    return VC_RUNTIME_FILE_VERSION


def _write_fake_wheel(directory, distribution, version, requires=(), tag="py3-none-any"):
    wheel_name = "{}-{}-{}.whl".format(
        distribution.replace("-", "_"), version, tag
    )
    path = directory / wheel_name
    metadata = [
        "Metadata-Version: 2.1",
        "Name: {}".format(distribution),
        "Version: {}".format(version),
    ]
    metadata.extend("Requires-Dist: {}".format(item) for item in requires)
    metadata.append("")
    with zipfile.ZipFile(str(path), "w") as archive:
        archive.writestr(
            "{}-{}.dist-info/METADATA".format(
                distribution.replace("-", "_"), version
            ),
            "\n".join(metadata),
        )
    return path


def _minimal_pe(import_name="KERNEL32.dll", delay_import_name=None, machine=0x8664):
    blob = bytearray(0x400)
    blob[:2] = b"MZ"
    struct.pack_into("<I", blob, 0x3C, 0x80)
    blob[0x80:0x84] = b"PE\0\0"
    file_header = 0x84
    struct.pack_into("<H", blob, file_header, machine)
    struct.pack_into("<H", blob, file_header + 2, 1)
    struct.pack_into("<H", blob, file_header + 16, 0xF0)
    optional = file_header + 20
    struct.pack_into("<H", blob, optional, 0x20B)
    struct.pack_into("<Q", blob, optional + 24, 0x140000000)
    struct.pack_into("<I", blob, optional + 108, 16)
    struct.pack_into("<II", blob, optional + 112 + 8, 0x1000, 40)
    section = optional + 0xF0
    blob[section : section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", blob, section + 8, 0x200, 0x1000, 0x200, 0x200)
    struct.pack_into("<IIIII", blob, 0x200, 1, 0, 0, 0x1030, 0x1040)
    encoded_name = import_name.encode("ascii") + b"\0"
    blob[0x230 : 0x230 + len(encoded_name)] = encoded_name
    if delay_import_name:
        struct.pack_into("<II", blob, optional + 112 + 13 * 8, 0x1080, 64)
        struct.pack_into("<IIIIIIII", blob, 0x280, 1, 0x10C0, 0, 0, 0, 0, 0, 0)
        encoded_delay = delay_import_name.encode("ascii") + b"\0"
        blob[0x2C0 : 0x2C0 + len(encoded_delay)] = encoded_delay
    return bytes(blob)


class BuildHostPolicyTests(unittest.TestCase):
    def test_exact_win7_sp1_python_org_host_is_accepted(self):
        self.assertEqual(validate_build_host(_win7_host(), {}), _win7_host())

    def test_windows_11_and_wrong_python_are_rejected(self):
        facts = HostFacts(
            "Windows", "11", "10.0.22621", "", "AMD64", 64, (3, 14, 0), "C:/Python314/python.exe"
        )
        with self.assertRaisesRegex(PackagingError, "Windows 7"):
            validate_build_host(facts, {})

    def test_explicit_cross_build_accepts_win11_only_with_exact_python(self):
        facts = HostFacts(
            "Windows",
            "11",
            "10.0.22631",
            "",
            "AMD64",
            64,
            (3, 8, 10),
            r"C:\Python3810\python.exe",
        )
        self.assertEqual(
            validate_build_host(
                facts,
                {},
                allow_win11_cross_build=True,
            ),
            facts,
        )

        wrong_python = HostFacts(
            "Windows",
            "11",
            "10.0.22631",
            "",
            "AMD64",
            64,
            (3, 8, 20),
            r"C:\Python3820\python.exe",
        )
        with self.assertRaisesRegex(PackagingError, "3.8.10"):
            validate_build_host(
                wrong_python,
                {},
                allow_win11_cross_build=True,
            )

    def test_cross_build_still_rejects_conda_and_non_windows_hosts(self):
        with self.assertRaisesRegex(PackagingError, "Conda"):
            validate_build_host(
                HostFacts(
                    "Windows",
                    "11",
                    "10.0.22631",
                    "",
                    "AMD64",
                    64,
                    (3, 8, 10),
                    r"C:\Miniconda3\python.exe",
                ),
                {"CONDA_PREFIX": r"C:\Miniconda3"},
                allow_win11_cross_build=True,
            )
        with self.assertRaisesRegex(PackagingError, "必须是 Windows"):
            validate_build_host(
                HostFacts(
                    "Linux",
                    "",
                    "",
                    "",
                    "x86_64",
                    64,
                    (3, 8, 10),
                    "/opt/python/bin/python",
                ),
                {},
                allow_win11_cross_build=True,
            )

    def test_missing_kb2533623_loader_api_is_rejected(self):
        facts = HostFacts(
            "Windows",
            "7",
            "6.1.7601",
            "SP1",
            "AMD64",
            64,
            (3, 8, 10),
            r"C:\Python38\python.exe",
            False,
        )
        with self.assertRaisesRegex(PackagingError, "KB2533623"):
            validate_build_host(facts, {})

    def test_conda_host_is_rejected_even_when_versions_match(self):
        with self.assertRaisesRegex(PackagingError, "Conda"):
            validate_build_host(
                _win7_host(r"C:\Miniconda3\python.exe"),
                {"CONDA_PREFIX": r"C:\Miniconda3"},
            )

    def test_conflicting_windows_release_and_nt_version_are_rejected(self):
        inconsistent = HostFacts(
            "Windows", "7", "10.0.19045", "SP1", "AMD64", 64, (3, 8, 10), "C:/Python38/python.exe"
        )
        with self.assertRaisesRegex(PackagingError, "NT 6.1"):
            validate_build_host(inconsistent, {})


class RuntimePolicyTests(unittest.TestCase):
    def test_private_vc_copies_are_replaced_by_audited_root_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            portable = Path(temp_dir)
            root_runtime = portable / "msvcp140.dll"
            root_runtime.write_bytes(b"audited-vc142")
            qt_private = portable / "PyQt5" / "Qt5" / "bin" / "MSVCP140.dll"
            qt_private.parent.mkdir(parents=True)
            qt_private.write_bytes(b"old-qt-runtime")
            matplotlib_private = (
                portable
                / "matplotlib.libs"
                / "msvcp140-0123456789abcdef.dll"
            )
            matplotlib_private.parent.mkdir()
            matplotlib_private.write_bytes(b"old-matplotlib-runtime")

            report = normalize_packaged_vc_runtime(portable)

            alias = portable / matplotlib_private.name
            self.assertFalse(qt_private.exists())
            self.assertFalse(matplotlib_private.exists())
            self.assertEqual(alias.read_bytes(), b"audited-vc142")
            self.assertIn(alias.name, report["root_compatibility_aliases"])

    def test_complete_exact_runtime_is_collected_for_app_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ucrt_root, vc_root = _write_runtime_roots(Path(temp_dir))
            files = collect_app_local_runtime(
                ucrt_root, vc_root, version_reader=_runtime_version_reader
            )

        self.assertEqual(
            {item.path.name.casefold() for item in files},
            win7_portable.REQUIRED_UCRT_FILES | win7_portable.REQUIRED_VC_FILES,
        )
        self.assertEqual({item.family for item in files}, {"ucrt", "vc142"})

    def test_complete_ucrt_and_only_required_vc_dlls_are_collected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ucrt_root, vc_root = _write_runtime_roots(Path(temp_dir))
            core_forwarder = ucrt_root / "api-ms-win-core-console-l1-1-0.dll"
            vc_concurrency = vc_root / "concrt140.dll"
            core_forwarder.write_bytes(_minimal_pe())
            vc_concurrency.write_bytes(_minimal_pe())
            files = collect_app_local_runtime(
                ucrt_root, vc_root, version_reader=_runtime_version_reader
            )

        names = {item.path.name.casefold() for item in files}
        self.assertIn(core_forwarder.name.casefold(), names)
        self.assertNotIn(vc_concurrency.name.casefold(), names)
        self.assertEqual(
            names.intersection({"concrt140.dll", "vccorlib140.dll"}),
            set(),
        )

    def test_missing_ucrt_stops_before_packaging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ucrt_root, vc_root = _write_runtime_roots(Path(temp_dir))
            (ucrt_root / "ucrtbase.dll").unlink()
            with self.assertRaisesRegex(PackagingError, "UCRT.*不完整"):
                collect_app_local_runtime(
                    ucrt_root, vc_root, version_reader=_runtime_version_reader
                )

    def test_sdk_19041_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ucrt_root, vc_root = _write_runtime_roots(Path(temp_dir))

            def version_reader(path):
                if Path(path).parent == ucrt_root:
                    return (10, 0, 19041, 0)
                return VC_RUNTIME_FILE_VERSION

            with self.assertRaisesRegex(PackagingError, "10.0.19041.0"):
                collect_app_local_runtime(ucrt_root, vc_root, version_reader=version_reader)

    def test_x86_runtime_dll_is_rejected_even_when_version_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ucrt_root, vc_root = _write_runtime_roots(Path(temp_dir))
            (vc_root / "vcruntime140.dll").write_bytes(_minimal_pe(machine=0x014C))
            with self.assertRaisesRegex(PackagingError, "不是 x64 PE"):
                collect_app_local_runtime(
                    ucrt_root, vc_root, version_reader=_runtime_version_reader
                )

    def test_vc_redist_uses_actual_30157_file_version(self):
        self.assertEqual(VC_RUNTIME_FILE_VERSION, (14, 29, 30157, 0))

    def test_mkl_and_icu75_are_rejected(self):
        self.assertIn("MKL", forbidden_binary_reason(Path("mkl_rt.dll")))
        self.assertIn("ICU 75", forbidden_binary_reason(Path("icuuc75.dll")))

    def test_binary_provenance_does_not_match_secondary(self):
        self.assertEqual(
            forbidden_binary_provenance_signatures(b"Qt secondary screen"),
            tuple(),
        )
        self.assertEqual(
            forbidden_binary_provenance_signatures(b"C:\\Miniconda3\\Library"),
            ("\\miniconda",),
        )


class WheelhouseTests(unittest.TestCase):
    def _create_locked_wheelhouse(self, root):
        requirements = root / "requirements.txt"
        requirements.write_text("packaging==23.1\ndemo==1.0\n", encoding="utf-8")
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        _write_fake_wheel(wheelhouse, "packaging", "23.1")
        demo = _write_fake_wheel(
            wheelhouse, "demo", "1.0", requires=("packaging>=23",)
        )
        create_wheelhouse_lock(wheelhouse, requirements)
        return requirements, wheelhouse, demo

    def test_lock_records_actual_wheel_hashes_and_validates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            requirements, wheelhouse, _ = self._create_locked_wheelhouse(Path(temp_dir))
            manifest = validate_wheelhouse(wheelhouse, requirements)
            lock_text = (wheelhouse / win7_portable.RESOLVED_REQUIREMENTS).read_text(
                encoding="utf-8"
            )

        self.assertEqual(len(manifest["wheels"]), 2)
        self.assertIn("--hash=sha256:", lock_text)
        self.assertIn("--only-binary=:all:", lock_text)

    def test_changed_wheel_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            requirements, wheelhouse, demo = self._create_locked_wheelhouse(Path(temp_dir))
            with demo.open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(PackagingError, "SHA-256"):
                validate_wheelhouse(wheelhouse, requirements)

    def test_unpinned_transitive_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements = root / "requirements.txt"
            requirements.write_text("packaging==23.1\ndemo==1.0\n", encoding="utf-8")
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            _write_fake_wheel(wheelhouse, "packaging", "23.1")
            _write_fake_wheel(wheelhouse, "demo", "1.0", requires=("missing-lib>=1",))
            with self.assertRaisesRegex(PackagingError, "传递依赖"):
                create_wheelhouse_lock(wheelhouse, requirements)

    def test_extra_unpinned_wheel_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements = root / "requirements.txt"
            requirements.write_text("packaging==23.1\n", encoding="utf-8")
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            _write_fake_wheel(wheelhouse, "packaging", "23.1")
            _write_fake_wheel(wheelhouse, "unrequested", "1.0")
            with self.assertRaisesRegex(PackagingError, "未固定依赖"):
                create_wheelhouse_lock(wheelhouse, requirements)

    def test_win32_wheel_tag_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requirements = root / "requirements.txt"
            requirements.write_text(
                "packaging==23.1\ndemo==1.0\n", encoding="utf-8"
            )
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            _write_fake_wheel(wheelhouse, "packaging", "23.1")
            _write_fake_wheel(
                wheelhouse, "demo", "1.0", tag="cp38-cp38-win32"
            )
            with self.assertRaisesRegex(PackagingError, "不兼容 CPython 3.8 win_amd64"):
                create_wheelhouse_lock(wheelhouse, requirements)

    def test_download_is_binary_only_no_deps_and_targeted_to_cp38(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "tools.win7_portable.subprocess.run"
        ) as run, patch(
            "tools.win7_portable.create_wheelhouse_lock", return_value={"wheels": []}
        ):
            requirements = Path(temp_dir) / "requirements.txt"
            requirements.write_text("demo==1.0\n", encoding="utf-8")
            win7_portable.prepare_wheelhouse(
                Path(temp_dir) / "wheelhouse", requirements, python_executable="python"
            )
            command = run.call_args.args[0]

        self.assertIn("--only-binary=:all:", command)
        self.assertIn("--no-deps", command)
        self.assertEqual(command[command.index("--python-version") + 1], "38")
        self.assertEqual(command[command.index("--platform") + 1], "win_amd64")


class PortableAuditTests(unittest.TestCase):
    def test_pe_import_parser_reads_import_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "sample.exe"
            binary.write_bytes(_minimal_pe("KERNEL32.dll", "USER32.dll"))
            self.assertEqual(
                read_pe_imports(binary), ("KERNEL32.dll", "USER32.dll")
            )
            self.assertEqual(read_pe_machine(binary), 0x8664)

    def test_dependency_closure_uses_packaged_and_win7_system_dlls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            portable = root / "portable"
            system32 = root / "system32"
            portable.mkdir()
            system32.mkdir()
            (portable / "app.exe").write_bytes(b"app")
            (portable / "local.dll").write_bytes(b"local")
            (system32 / "kernel32.dll").write_bytes(b"system")

            imports = {
                "app.exe": ("local.dll", "kernel32.dll"),
                "local.dll": tuple(),
            }
            report = audit_pe_dependency_closure(
                portable,
                system_dirs=(system32,),
                import_reader=lambda path: imports[path.name],
            )

        self.assertEqual(report["native_file_count"], 2)

    def test_unresolved_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            portable = Path(temp_dir) / "portable"
            portable.mkdir()
            (portable / "app.exe").write_bytes(b"app")
            with self.assertRaisesRegex(PackagingError, "missing.dll"):
                audit_pe_dependency_closure(
                    portable,
                    system_dirs=(),
                    import_reader=lambda _path: ("missing.dll",),
                )

    def test_dependency_in_unrelated_subdirectory_is_not_treated_as_reachable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            portable = Path(temp_dir) / "portable"
            unrelated = portable / "other"
            unrelated.mkdir(parents=True)
            (portable / "app.exe").write_bytes(b"app")
            (unrelated / "nested.dll").write_bytes(b"nested")
            with self.assertRaisesRegex(PackagingError, "传统搜索不可达"):
                audit_pe_dependency_closure(
                    portable,
                    system_dirs=(),
                    import_reader=lambda path: (
                        ("nested.dll",) if path.name == "app.exe" else tuple()
                    ),
                )

    def test_openblas_must_be_in_portable_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ucrt_root, vc_root = _write_runtime_roots(root)
            runtime_files = collect_app_local_runtime(
                ucrt_root, vc_root, version_reader=_runtime_version_reader
            )
            portable = root / "portable"
            platform_dir = portable / "PyQt5" / "Qt5" / "plugins" / "platforms"
            platform_dir.mkdir(parents=True)
            (portable / EXE_NAME).write_bytes(b"exe")
            (platform_dir / "qwindows.dll").write_bytes(b"plugin")
            for qt_dll in ("Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll"):
                (portable / qt_dll).write_bytes(b"qt")
            for runtime in runtime_files:
                (portable / runtime.path.name).write_bytes(runtime.path.read_bytes())
            nested = portable / "numpy.libs"
            nested.mkdir()
            (nested / "libopenblas64_test.dll").write_bytes(b"blas")

            with self.assertRaisesRegex(PackagingError, "OpenBLAS.*根目录"):
                audit_portable_tree(
                    portable,
                    runtime_files,
                    system_dirs=(),
                    version_reader=_runtime_version_reader,
                    import_reader=lambda _path: tuple(),
                    machine_reader=lambda _path: 0x8664,
                    compatibility_reader=lambda _path: (
                        0x8664,
                        (0, 0),
                        (0, 0),
                    ),
                )

    def test_release_manifest_zip_and_hashes_are_generated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            portable = root / PORTABLE_NAME
            portable.mkdir()
            exe = portable / EXE_NAME
            exe.write_bytes(b"exe")
            runtime_source = root / "ucrtbase.dll"
            runtime_source.write_bytes(b"ucrt")
            runtime = RuntimeFile(
                runtime_source,
                "ucrt",
                UCRT_FILE_VERSION,
                sha256_file(runtime_source),
            )
            wheel_manifest = {
                "wheels": [
                    {
                        "filename": "demo-1.0-py3-none-any.whl",
                        "name": "demo",
                        "normalized_name": "demo",
                        "version": "1.0",
                        "sha256": "0" * 64,
                    }
                ],
                "source_requirements_sha256": "1" * 64,
                "resolved_requirements_sha256": "2" * 64,
            }
            manifest = write_release_metadata(
                portable,
                _win7_host(),
                wheel_manifest,
                (runtime,),
                {"pe_dependency_closure": {"native_file_count": 1}},
            )
            acceptance_path = root / win7_portable.ACCEPTANCE_RECORD
            acceptance = write_acceptance_template(acceptance_path, portable)
            (portable / "performance.db").write_bytes(b"unexpected")
            with self.assertRaisesRegex(PackagingError, "多余"):
                win7_portable._verify_candidate_payload(portable, manifest)
            (portable / "performance.db").unlink()
            output_zip = root / (PORTABLE_NAME + ".zip")
            digest = create_portable_zip(portable, output_zip)
            with zipfile.ZipFile(str(output_zip)) as archive:
                names = set(archive.namelist())

        self.assertEqual(manifest["release_status"], "candidate_requires_clean_win7_vm_acceptance")
        self.assertEqual(manifest["build_mode"], "native_win7")
        self.assertFalse(acceptance["win11_regression_passed"])
        self.assertIn("wheelhouse", manifest)
        self.assertEqual(len(digest), 64)
        self.assertIn(PORTABLE_NAME + "/" + win7_portable.RELEASE_MANIFEST, names)
        self.assertIn(PORTABLE_NAME + "/" + win7_portable.RELEASE_HASHES, names)


class ReleaseFinalizationTests(unittest.TestCase):
    def _candidate(self, root):
        project_root = root / "project"
        portable = project_root / "dist" / PORTABLE_NAME
        portable.mkdir(parents=True)
        (portable / EXE_NAME).write_bytes(b"candidate-exe")
        runtime_source = root / "ucrtbase.dll"
        runtime_source.write_bytes(b"ucrt")
        runtime = RuntimeFile(
            runtime_source,
            "ucrt",
            UCRT_FILE_VERSION,
            sha256_file(runtime_source),
        )
        wheel_manifest = {
            "wheels": [
                {
                    "filename": "demo-1.0-py3-none-any.whl",
                    "name": "demo",
                    "normalized_name": "demo",
                    "version": "1.0",
                    "sha256": "0" * 64,
                }
            ],
            "source_requirements_sha256": "1" * 64,
            "resolved_requirements_sha256": "2" * 64,
        }
        manifest = write_release_metadata(
            portable,
            _win7_host(),
            wheel_manifest,
            (runtime,),
            {"pe_dependency_closure": {"native_file_count": 1}},
        )
        acceptance_path = project_root / "dist" / win7_portable.ACCEPTANCE_RECORD
        record = win7_portable.write_acceptance_template(acceptance_path, portable)
        return project_root, portable, manifest, acceptance_path, record

    def test_candidate_payload_rejects_unlisted_runtime_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _, portable, manifest, _, _ = self._candidate(Path(temp_dir))
            (portable / "performance.db").write_bytes(b"not-release-data")

            with self.assertRaisesRegex(PackagingError, "多余"):
                win7_portable._verify_candidate_payload(portable, manifest)

    def test_finalize_requires_complete_acceptance_and_then_creates_formal_zip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root, portable, _, acceptance_path, record = self._candidate(
                Path(temp_dir)
            )
            with patch("tools.win7_portable.validate_build_host"):
                with self.assertRaisesRegex(PackagingError, "验收记录未完成"):
                    win7_portable.finalize_release(project_root, acceptance_path)

            record.update(
                {
                    "tested_utc": "2026-08-28T12:00:00+08:00",
                    "tester": "release-test",
                    "win7_sp1_x64_confirmed": True,
                    "kb2533623_confirmed": True,
                    "target_has_no_python": True,
                    "target_has_no_vc_ucrt_install": True,
                    "diagnose_passed": True,
                    "smoke_test_passed": True,
                    "functional_checks_passed": True,
                    "win11_regression_passed": True,
                }
            )
            acceptance_path.write_text(
                json.dumps(record, ensure_ascii=False), encoding="utf-8"
            )
            with patch("tools.win7_portable.validate_build_host"):
                final_zip = win7_portable.finalize_release(
                    project_root, acceptance_path
                )

            manifest = json.loads(
                (portable / win7_portable.RELEASE_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(final_zip.is_file())
            self.assertTrue(Path(str(final_zip) + ".sha256").is_file())
            self.assertEqual(
                manifest["release_status"], "accepted_clean_win7_vm"
            )
            self.assertTrue(manifest["acceptance"]["win11_regression_passed"])

    def test_packaged_checks_cannot_borrow_build_python_or_sdk_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            portable = Path(temp_dir) / "portable"
            portable.mkdir()
            executable = portable / EXE_NAME
            executable.write_bytes(b"exe")
            seen_paths = []

            def fake_runner(command, **kwargs):
                seen_paths.append(kwargs["env"]["PATH"])
                if command[-1] == "--diagnose":
                    (portable / "startup_diagnostic.log").write_text(
                        "ok", encoding="utf-8"
                    )
                return __import__("subprocess").CompletedProcess(command, 0, b"", b"")

            results = run_packaged_executable_checks(
                portable,
                {
                    "PATH": r"C:\Python38;C:\SDK14393;C:\VC142",
                    "SystemRoot": r"C:\Windows",
                    "WIN7_UCRT_ROOT": r"C:\SDK14393",
                    "WIN7_VC_RUNTIME_ROOT": r"C:\VC142",
                },
                runner=fake_runner,
            )

        self.assertEqual(len(results), 2)
        self.assertTrue(all("Python38" not in value for value in seen_paths))
        self.assertTrue(all("SDK14393" not in value for value in seen_paths))


class PackagingConfigurationTests(unittest.TestCase):
    def test_spec_is_onedir_collect_v131_without_upx(self):
        spec = (PROJECT_ROOT / "PerformanceApp.spec").read_text(encoding="utf-8")
        self.assertIn("exclude_binaries=True", spec)
        self.assertIn("coll = COLLECT(", spec)
        self.assertIn("name=PORTABLE_NAME", spec)
        self.assertIn("upx=False", spec)
        self.assertNotIn("runtime_tmpdir", spec)
        self.assertEqual(APP_VERSION, "1.3.1")

    def test_all_known_matplotlib_py38_transitives_are_explicitly_pinned(self):
        pins = win7_portable.parse_pinned_requirements(
            PROJECT_ROOT / "requirements-win7-build.txt"
        )
        for required in (
            "importlib-resources",
            "zipp",
            "contourpy",
            "cycler",
            "fonttools",
            "kiwisolver",
            "packaging",
            "pillow",
            "pyparsing",
            "python-dateutil",
            "six",
        ):
            self.assertIn(required, pins)

    def test_tool_source_parses_with_python_38_grammar(self):
        source = (PROJECT_ROOT / "tools" / "win7_portable.py").read_text(
            encoding="utf-8"
        )
        ast.parse(source, feature_version=(3, 8))

    def test_full_tests_are_a_hard_gate_before_pyinstaller(self):
        source = (PROJECT_ROOT / "tools" / "win7_portable.py").read_text(
            encoding="utf-8"
        )
        test_gate = source.index('str(project_root / "run_tests.py")')
        pyinstaller = source.index('"PyInstaller"', test_gate)
        self.assertLess(test_gate, pyinstaller)

    def test_old_conda_environment_file_was_removed(self):
        self.assertFalse((PROJECT_ROOT / "environment-win7.yml").exists())

    def test_cross_build_flag_is_explicit_and_candidate_only(self):
        parser = win7_portable.create_argument_parser()
        arguments = parser.parse_args(
            [
                "build",
                "--wheelhouse",
                "wheelhouse",
                "--ucrt-root",
                "ucrt",
                "--vc-runtime-root",
                "vc",
                "--allow-win11-cross-build",
            ]
        )
        self.assertTrue(arguments.allow_win11_cross_build)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            portable = root / PORTABLE_NAME
            portable.mkdir()
            (portable / EXE_NAME).write_bytes(b"exe")
            runtime_source = root / "ucrtbase.dll"
            runtime_source.write_bytes(b"ucrt")
            manifest = write_release_metadata(
                portable,
                _win7_host(),
                {"wheels": []},
                (
                    RuntimeFile(
                        runtime_source,
                        "ucrt",
                        UCRT_FILE_VERSION,
                        sha256_file(runtime_source),
                    ),
                ),
                {},
                build_mode="win11_cross_build",
            )
        self.assertEqual(
            manifest["release_status"],
            "experimental_win11_cross_build_requires_win7_runtime_test",
        )

    def test_toc_provenance_checks_paths_without_matching_secondary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work = Path(temp_dir)
            (work / "safe.toc").write_text(
                repr(
                    [
                        (
                            "matplotlib.axes._secondary_axes",
                            r"C:\Python3810\Lib\site-packages\matplotlib\axes\_secondary_axes.py",
                            "PYMODULE",
                        )
                    ]
                ),
                encoding="utf-8",
            )
            report = audit_pyinstaller_provenance(work)
            self.assertEqual(report["toc_files_checked"], 1)

            (work / "unsafe.toc").write_text(
                repr([("Qt5Core.dll", r"C:\Miniconda3\Library\bin\Qt5Core.dll", "BINARY")]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PackagingError, "miniconda"):
                audit_pyinstaller_provenance(work)


if __name__ == "__main__":
    unittest.main()
