import sys
import os
import hashlib

# New writes remain in the legacy format until every reader and writer has
# been upgraded and a separate, coordinated migration enables authentication.
AUTH_MAGIC = b"EMONITOR-CONFIG-V2\x00"
AUTH_SALT_BYTES = 16
AUTH_NONCE_BYTES = 12
AUTH_TAG_BYTES = 16


def _authenticated_key(passphrase, salt):
    if not isinstance(passphrase, str) or not passphrase:
        raise ValueError("Passphrase required for authenticated encryption")
    return hashlib.scrypt(passphrase.encode('utf-8'), salt=salt, n=2**15, r=8,
                          p=1, maxmem=128 * 1024 * 1024, dklen=32)


def encrypt_authenticated(data: bytes, passphrase: str) -> bytes:
    """Create a V2 envelope; callers must explicitly opt in to migration."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(AUTH_SALT_BYTES)
    nonce = os.urandom(AUTH_NONCE_BYTES)
    header = AUTH_MAGIC + salt + nonce
    return header + AESGCM(_authenticated_key(passphrase, salt)).encrypt(nonce, data, header)


def _decrypt_authenticated(data: bytes, passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    header_size = len(AUTH_MAGIC) + AUTH_SALT_BYTES + AUTH_NONCE_BYTES
    if len(data) < header_size + AUTH_TAG_BYTES:
        raise ValueError("Invalid authenticated ciphertext")
    salt = data[len(AUTH_MAGIC):len(AUTH_MAGIC) + AUTH_SALT_BYTES]
    nonce = data[len(AUTH_MAGIC) + AUTH_SALT_BYTES:header_size]
    try:
        return AESGCM(_authenticated_key(passphrase, salt)).decrypt(nonce, data[header_size:], data[:header_size])
    except InvalidTag as exc:
        raise ValueError("Ciphertext authentication failed") from exc

def get_keystream(key, length):
    keystream = bytearray()
    counter = 0
    while len(keystream) < length:
        ctx = hashlib.sha256()
        ctx.update(key)
        ctx.update(counter.to_bytes(4, 'big'))
        keystream.extend(ctx.digest())
        counter += 1
    return keystream[:length]

def encrypt(data: bytes, passphrase: str) -> bytes:
    salt = os.urandom(16)
    key = hashlib.sha256(passphrase.encode('utf-8') + salt).digest()
    keystream = get_keystream(key, len(data))
    ciphertext = bytes(a ^ b for a, b in zip(data, keystream))
    return salt + ciphertext

def decrypt(data: bytes, passphrase: str, *, require_authenticated: bool = False) -> bytes:
    if data.startswith(AUTH_MAGIC):
        return _decrypt_authenticated(data, passphrase)
    if require_authenticated:
        raise ValueError("Authenticated ciphertext required")
    if len(data) < 16:
        raise ValueError("Data is too short to be valid ciphertext")
    salt = data[:16]
    ciphertext = data[16:]
    key = hashlib.sha256(passphrase.encode('utf-8') + salt).digest()
    keystream = get_keystream(key, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, keystream))

def main():
    if len(sys.argv) < 5:
        # Check if environment variable is set
        passphrase = os.environ.get("CONFIG_PASSPHRASE")
        if not passphrase:
            print("Usage: python config_crypt.py <encrypt|decrypt> <input_file> <output_file> [passphrase]")
            print("Or set CONFIG_PASSPHRASE environment variable.")
            sys.exit(1)
        action = sys.argv[1]
        input_file = sys.argv[2]
        output_file = sys.argv[3]
    else:
        action = sys.argv[1]
        input_file = sys.argv[2]
        output_file = sys.argv[3]
        passphrase = sys.argv[4]

    if action not in ("encrypt", "decrypt"):
        print(f"Error: Unknown action '{action}' (must be 'encrypt' or 'decrypt')")
        sys.exit(1)

    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        sys.exit(1)

    try:
        with open(input_file, "rb") as f:
            data = f.read()

        if action == "encrypt":
            out_data = encrypt(data, passphrase)
        else:
            out_data = decrypt(data, passphrase)

        with open(output_file, "wb") as f:
            f.write(out_data)

        print(f"Success: {action}ed '{input_file}' to '{output_file}'.")
    except Exception as e:
        print(f"Error during {action}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
