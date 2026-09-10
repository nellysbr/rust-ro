import importlib.machinery
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest
from unittest import mock
import tempfile
import subprocess

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('installer', str(ROOT / 'ragzin-deploy'))
spec = importlib.util.spec_from_loader(loader.name, loader)
installer = importlib.util.module_from_spec(spec)
loader.exec_module(installer)
spec2 = importlib.util.spec_from_file_location('bootstrap', ROOT / 'bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(bootstrap)

class ArchiveTests(unittest.TestCase):
    def archive(self, extra=None):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as tar:
            for name in ['server', 'REVISION', 'native_functions_list.txt']:
                tar.addfile(tarfile.TarInfo(name), io.BytesIO())
            if extra is not None:
                tar.addfile(extra, io.BytesIO())
        stream.seek(0)
        return tarfile.open(fileobj=stream)

    def test_valid_archive(self):
        with self.archive() as archive:
            self.assertEqual(len(installer.validate_members(archive)), 3)

    def test_rejects_traversal_absolute_paths_and_root_scripts(self):
        for name in ['config/../../etc/sudoers', '/etc/sudoers', 'deploy.sh', 'server']:
            with self.subTest(name=name), self.archive(tarfile.TarInfo(name)) as archive:
                with self.assertRaises(ValueError):
                    installer.validate_members(archive)

    def test_rejects_symlinks_hardlinks_devices(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE]:
            member = tarfile.TarInfo('config/escape')
            member.type = kind
            member.linkname = '/etc/sudoers'
            with self.archive(member) as archive:
                with self.assertRaises(ValueError):
                    installer.validate_members(archive)

    def test_bootstrap_excludes_demo_accounts_preserves_static_data(self):
        dump = 'CREATE SCHEMA ragnarok;\nCOPY ragnarok.login (id) FROM stdin;\nsecret\n\\.\nCOPY ragnarok.item_db (id) FROM stdin;\n501\n\\.\nCOMMIT;\n'
        cleaned = bootstrap.clean_initial_dump(dump)
        self.assertNotIn('secret', cleaned)
        self.assertNotIn('COPY ragnarok.login', cleaned)
        self.assertIn('501\n\\.\nCOMMIT;', cleaned)



class UpstreamSeedTests(unittest.TestCase):
    def test_shipped_dump_does_not_import_sample_characters(self):
        dump = (ROOT.parent / 'db' / 'pg.sql').read_text()
        self.assertIn('insert into ragnarok.char ', dump)
        cleaned = bootstrap.clean_initial_dump(dump)
        self.assertNotIn('insert into ragnarok.char ', cleaned)
        self.assertNotIn("'admin1'", cleaned)
        self.assertIn('COPY ragnarok.item_db ', cleaned)
        self.assertIn('COPY ragnarok.mob_db ', cleaned)


class RollbackTests(unittest.TestCase):
    def test_failed_release_restores_previous_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'releases').mkdir()
            (base / 'incoming').mkdir()
            previous = base / 'releases' / ('a' * 40)
            previous.mkdir()
            (base / 'current').symlink_to(previous)
            sha = 'b' * 40
            with tarfile.open(base / 'incoming' / f'ragzin-{sha}.tar.gz', 'w:gz') as archive:
                for name, contents in [('server', b'not-a-binary'), ('REVISION', sha.encode()), ('native_functions_list.txt', b'')]:
                    member = tarfile.TarInfo(name)
                    member.size = len(contents)
                    archive.addfile(member, io.BytesIO(contents))
                member = tarfile.TarInfo('config')
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            calls = []
            def run(*args, **kwargs):
                calls.append(args)
            actual_open = open
            def safe_open(path, *args, **kwargs):
                if path == '/run/lock/ragzin-deploy.lock':
                    path = base / 'deploy.lock'
                return actual_open(path, *args, **kwargs)
            with mock.patch.object(installer, 'BASE', base), mock.patch.object(installer.os, 'geteuid', return_value=0), \
                    mock.patch.object(installer.sys, 'argv', ['ragzin-deploy', sha]), \
                    mock.patch('builtins.open', side_effect=safe_open), \
                    mock.patch.object(installer, 'run', side_effect=run), \
                    mock.patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
                    mock.patch.object(installer, 'healthy', side_effect=[False, True]):
                with self.assertRaisesRegex(RuntimeError, 'Nova release'):
                    installer.main()
            self.assertEqual((base / 'current').resolve(), previous)
            self.assertEqual(calls.count(('systemctl', 'start', 'ragzin.service')), 2)
            self.assertIn(('/usr/local/sbin/ragzin-backup',), calls)
            self.assertNotIn(('systemctl', 'enable', 'ragzin.service'), calls)

class FirstStartTests(unittest.TestCase):
    def test_first_deploy_starts_an_inactive_unloaded_unit(self):
        with mock.patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 3)), \
                mock.patch.object(installer, 'run') as run:
            installer.start_service()
        run.assert_called_once_with('systemctl', 'start', 'ragzin.service')

    def test_failed_unit_is_reset_before_start(self):
        with mock.patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(installer, 'run') as run:
            installer.start_service()
        self.assertEqual(run.call_args_list, [
            mock.call('systemctl', 'reset-failed', 'ragzin.service'),
            mock.call('systemctl', 'start', 'ragzin.service'),
        ])

if __name__ == '__main__':
    unittest.main()
