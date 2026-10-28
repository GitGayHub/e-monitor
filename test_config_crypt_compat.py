"""Synthetic, offline checks for the staged authenticated configuration reader."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import config_crypt


class ConfigCryptCompatibilityTests(unittest.TestCase):
    def test_existing_format_and_default_writer_remain_compatible(self):
        plain = b'{"searches":[{"name":"synthetic"}]}'
        ciphertext = config_crypt.encrypt(plain, 'test-only')
        self.assertFalse(ciphertext.startswith(config_crypt.AUTH_MAGIC))
        self.assertEqual(plain, config_crypt.decrypt(ciphertext, 'test-only'))
        with self.assertRaises(ValueError):
            config_crypt.decrypt(ciphertext, 'test-only', require_authenticated=True)

    def test_authenticated_format_and_prototype_are_interoperable(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import hashlib

        plain = 'искусственные данные'.encode('utf-8')
        ciphertext = config_crypt.encrypt_authenticated(plain, 'test-only')
        self.assertEqual(plain, config_crypt.decrypt(ciphertext, 'test-only', require_authenticated=True))
        offset = len(config_crypt.AUTH_MAGIC)
        salt, nonce = ciphertext[offset:offset + 16], ciphertext[offset + 16:offset + 28]
        header = ciphertext[:offset + 28]
        key = hashlib.scrypt(b'test-only', salt=salt, n=2**15, r=8, p=1,
                             maxmem=128 * 1024 * 1024, dklen=32)
        self.assertEqual(plain, AESGCM(key).decrypt(nonce, ciphertext[offset + 28:], header))

    def test_tampering_wrong_password_truncation_and_downgrade_are_rejected_in_strict_mode(self):
        original = config_crypt.encrypt_authenticated(b'{"searches":[]}', 'test-only')
        variants = [original[:n] for n in (0, 8, len(config_crypt.AUTH_MAGIC), len(original) - 1)]
        for offset in (0, len(config_crypt.AUTH_MAGIC), len(config_crypt.AUTH_MAGIC) + 16, len(original) - 1):
            mutated = bytearray(original)
            mutated[offset] ^= 1
            variants.append(bytes(mutated))
        for variant in variants:
            with self.subTest(length=len(variant)), self.assertRaises(ValueError):
                config_crypt.decrypt(variant, 'test-only', require_authenticated=True)
        with self.assertRaises(ValueError):
            config_crypt.decrypt(original, 'wrong', require_authenticated=True)

    def test_cli_reads_new_format_and_does_not_overwrite_output_on_auth_failure(self):
        script = Path(config_crypt.__file__).resolve()
        with tempfile.TemporaryDirectory(prefix='emonitor-crypt-test-') as folder:
            folder = Path(folder)
            encrypted, output = folder / 'config.enc', folder / 'config.json'
            encrypted.write_bytes(config_crypt.encrypt_authenticated(b'{"searches":[]}', 'test-only'))
            env = {**os.environ, 'CONFIG_PASSPHRASE': 'test-only'}
            result = subprocess.run([sys.executable, str(script), 'decrypt', str(encrypted), str(output)],
                                    capture_output=True, env=env)
            self.assertEqual(0, result.returncode)
            self.assertEqual(b'{"searches":[]}', output.read_bytes())
            env['CONFIG_PASSPHRASE'] = 'wrong'
            result = subprocess.run([sys.executable, str(script), 'decrypt', str(encrypted), str(output)],
                                    capture_output=True, env=env)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(b'{"searches":[]}', output.read_bytes())

    def test_missing_crypto_dependency_does_not_break_legacy_and_v2_fails_closed(self):
        script = Path(config_crypt.__file__).resolve()
        with tempfile.TemporaryDirectory(prefix='emonitor-crypt-test-') as folder:
            folder = Path(folder)
            encrypted, output = folder / 'config.enc', folder / 'config.json'
            env = {**os.environ, 'CONFIG_PASSPHRASE': 'test-only'}
            plain = b'{"searches":[]}'
            encrypted.write_bytes(config_crypt.encrypt(plain, 'test-only'))
            legacy = subprocess.run([sys.executable, '-S', str(script), 'decrypt', str(encrypted), str(output)],
                                    capture_output=True, env=env)
            self.assertEqual(0, legacy.returncode)
            self.assertEqual(plain, output.read_bytes())
            encrypted.write_bytes(config_crypt.encrypt_authenticated(b'{"searches":[1]}', 'test-only'))
            authenticated = subprocess.run([sys.executable, '-S', str(script), 'decrypt', str(encrypted), str(output)],
                                           capture_output=True, env=env)
            self.assertNotEqual(0, authenticated.returncode)
            self.assertEqual(plain, output.read_bytes())


if __name__ == '__main__':
    unittest.main()
