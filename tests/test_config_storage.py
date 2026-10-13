import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workshop_app as app


class ConfigStorageTests(unittest.TestCase):
    def test_modes_copy_settings_and_survive_restart_without_moving_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = app.WorkshopService(root / 'user', program_dir=root / 'program')
            service.save_config({'config_name': 'Main', 'api_key': 'test-only-key'})
            database = service.database
            service.switch_config_storage('portable')
            self.assertEqual(service.config_path, root / 'program/config.json')
            self.assertEqual(service.config()['api_key'], 'test-only-key')
            self.assertNotIn('api_key', service.public_config())
            restarted = app.WorkshopService(root / 'user', program_dir=root / 'program')
            self.assertEqual(restarted.storage_mode, 'portable')
            self.assertEqual(restarted.database, database)
            restarted.save_config({'model': 'changed-model'})
            restarted.switch_config_storage('user')
            self.assertEqual(restarted.config_path, root / 'user/config.json')
            self.assertEqual(restarted.config()['model'], 'changed-model')
            self.assertEqual(restarted.config()['api_key'], 'test-only-key')
            self.assertEqual(restarted.profiles()[0]['name'], 'Main')
            final = app.WorkshopService(root / 'user', program_dir=root / 'program')
            self.assertEqual(final.storage_mode, 'user')

    def test_portable_folder_carries_mode_to_new_user(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = app.WorkshopService(root / 'user1', program_dir=root / 'program')
            service.save_config({'api_key': 'test-only-key'})
            service.switch_config_storage('portable')
            moved = app.WorkshopService(root / 'user2', program_dir=root / 'program')
            self.assertEqual(moved.storage_mode, 'portable')
            self.assertEqual(moved.config()['api_key'], 'test-only-key')

    def test_target_profiles_with_same_name_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = app.WorkshopService(root / 'user', program_dir=root / 'program')
            service.save_config({'config_name': 'Same', 'api_key': 'source-key'})
            target = root / 'program'
            target.mkdir()
            (target / 'providers.json').write_text(json.dumps({'profiles': {'Same': {**app.DEFAULT_CONFIG, 'config_name': 'Same', 'api_key': 'target-key'}}}), encoding='utf-8')
            service.switch_config_storage('portable')
            profiles = json.loads(service.providers_path.read_text('utf-8'))['profiles']
            self.assertEqual({p['api_key'] for p in profiles.values()}, {'source-key', 'target-key'})

    def test_permission_failure_and_running_job_keep_active_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = app.WorkshopService(root / 'user', program_dir=root / 'program')
            original = service.config_path
            with patch.object(app, 'atomic_bytes', side_effect=PermissionError('read only')):
                with self.assertRaisesRegex(ValueError, '无法写入'):
                    service.switch_config_storage('portable')
            self.assertEqual(service.config_path, original)
            self.assertEqual(service.storage_mode, 'user')
            service.job['running'] = True
            with self.assertRaisesRegex(ValueError, '等待任务结束'):
                service.switch_config_storage('portable')

    def test_legacy_config_is_migrated_to_user_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            legacy = root / 'legacy'
            legacy.mkdir()
            (legacy / 'config.json').write_text(json.dumps({**app.DEFAULT_CONFIG, 'api_key': 'legacy-key'}), encoding='utf-8')
            with patch.object(app, 'default_data_dir', return_value=legacy), patch.object(app, 'user_config_dir', return_value=root / 'user'):
                service = app.WorkshopService(program_dir=root / 'program')
            self.assertEqual(service.config_path, root / 'user/config.json')
            self.assertEqual(service.config()['api_key'], 'legacy-key')
            self.assertTrue((legacy / 'config.json').exists())
