"""Device-free tests: no InputPlumber, no D-Bus, no PyYAML needed."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[1] / 'src'
loader = SourceFileLoader('pad_mouse', str(SOURCE / 'pad-mouse'))
pad_mouse = module_from_spec(spec_from_loader(loader.name, loader))
loader.exec_module(pad_mouse)


def gamepad(name, **source):
    return {'name': name, 'source_event': {'gamepad': source}, 'target_events': []}


OURS = [gamepad('stick', axis={'name': 'RightStick'}),
        gamepad('r1', button='RightBumper'),
        gamepad('r2', trigger={'name': 'RightTrigger', 'deadzone': 0.25})]


class Merge(unittest.TestCase):
    def test_keeps_unrelated_mappings_and_replaces_ours(self):
        base = {'name': 'Default', 'mapping': [
            gamepad('paddle', button='LeftTop'),
            gamepad('old r1', button='RightBumper'),
            gamepad('stick to wasd', axis={'name': 'RightStick', 'direction': 'left'}),
            gamepad('dial', dial={'name': 'RightStickDial', 'direction': 'clockwise'}),
            {'name': 'key', 'source_event': {'keyboard': 'KeyF1'}, 'target_events': []},
        ]}
        merged = pad_mouse.merge(base, OURS)
        self.assertEqual([m['name'] for m in merged['mapping']],
                         ['paddle', 'dial', 'key', 'stick', 'r1', 'r2'])
        self.assertEqual(merged['name'], pad_mouse.PROFILE_NAME)
        self.assertEqual(base['name'], 'Default', 'input must not change')
        self.assertEqual(len(base['mapping']), 5)

    def test_adds_mouse_only_to_pinned_targets(self):
        self.assertNotIn('target_devices', pad_mouse.merge({'mapping': []}, OURS))
        merged = pad_mouse.merge({'target_devices': ['xbox-elite']}, OURS)
        self.assertEqual(merged['target_devices'], ['xbox-elite', 'mouse'])


class Decision(unittest.TestCase):
    def test_desktop_sessions(self):
        for compositor in ('kwin_wayland', 'labwc'):
            self.assertTrue(pad_mouse.should_emulate([compositor, 'bash'], False))

    def test_gaming_mode_wins_even_with_a_second_screen_desktop(self):
        # Names as the kernel truncates them in /proc/<pid>/comm.
        for gamescope in ('gamescope-sessi', 'gamescope-wl', 'gamescope'):
            self.assertFalse(pad_mouse.should_emulate(['kwin_wayland', gamescope], False))

    def test_no_desktop_or_switched_off(self):
        self.assertFalse(pad_mouse.should_emulate(['bash'], False))
        self.assertFalse(pad_mouse.should_emulate(['labwc'], True))


class Restore(unittest.TestCase):
    """The profile that was active before must come back."""

    def run_restore(self, active, saved):
        calls = []
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(pad_mouse, 'runtime_dir', return_value=Path(directory)), \
                mock.patch.object(pad_mouse, 'call', side_effect=lambda *a: calls.append(a[1:])):
            if saved is not None:
                (Path(directory) / 'previous.json').write_text(saved)
            pad_mouse.restore('/device', {'ProfileName': active})
        return calls

    def test_leaves_other_profiles_alone(self):
        self.assertEqual(self.run_restore('Default', None), [])

    def test_prefers_saved_file_then_saved_text_then_stock(self):
        ours = pad_mouse.PROFILE_NAME
        existing = str(SOURCE / 'mappings.yaml')
        self.assertEqual(self.run_restore(ours, f'{{"path": "{existing}", "yaml": "x"}}'),
                         [('LoadProfilePath', existing)])
        self.assertEqual(self.run_restore(ours, '{"path": "", "yaml": "x"}'),
                         [('LoadProfileFromYaml', 'x')])
        self.assertEqual(self.run_restore(ours, None),
                         [('LoadProfilePath', pad_mouse.STOCK_PROFILE)])


class Controller(unittest.TestCase):
    def devices(self, **names):
        return {f'/ip/{path}': {'Name': name, 'Capabilities': list(pad_mouse.NEEDED) if full else []}
                for path, (name, full) in names.items()}

    def test_prefers_the_handhelds_own_controller(self):
        devices = self.devices(CompositeDevice0=('Xbox pad', True), CompositeDevice1=('AYN Thor', True))
        self.assertEqual(pad_mouse.choose_device(devices, 'AYN Thor'), '/ip/CompositeDevice1')

    def test_falls_back_to_the_first_capable_controller(self):
        devices = self.devices(CompositeDevice0=('Keys', False), CompositeDevice2=('Pad', True))
        self.assertEqual(pad_mouse.choose_device(devices, 'Unlisted model'), '/ip/CompositeDevice2')
        self.assertIsNone(pad_mouse.choose_device(devices, 'x', override='Missing pad'))


class Mappings(unittest.TestCase):
    def test_shipped_file(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML not installed here')
        mapping = yaml.safe_load((SOURCE / 'mappings.yaml').read_text())['mapping']
        got = {pad_mouse.source_key(m): m['target_events'][0]['mouse'] for m in mapping}
        self.assertIn('motion', got['axis', 'RightStick'])
        self.assertEqual(got['button', 'RightBumper'], {'button': 'Left'})
        self.assertEqual(got['trigger', 'RightTrigger'], {'button': 'Right'})


if __name__ == '__main__':
    unittest.main()
