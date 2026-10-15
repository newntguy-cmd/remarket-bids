"""수집 결과를 비밀번호로 잠가서 저장하고 읽는 도구.

환경변수 SITE_PASSWORD 가 있으면 docs/*.enc (암호화) 로 저장하고 평문 json 은 지웁니다.
없으면 예전처럼 평문 json 으로 저장합니다(비밀번호를 정하기 전 임시 상태).
형식: "RMK1" + 소금(16) + IV(12) + AES-256-GCM(gzip(JSON)). 키는 PBKDF2-SHA256 20만 회.
"""
import gzip
import hashlib
import json
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"RMK1"
ITER = 200_000


def _key(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, ITER, 32)


def encrypt(data, pw):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(pw, salt)).encrypt(iv, gzip.compress(data, 9), MAGIC)
    return MAGIC + salt + iv + ct


def decrypt(blob, pw):
    if blob[:4] != MAGIC:
        raise ValueError("형식이 맞지 않는 파일")
    salt, iv, ct = blob[4:20], blob[20:32], blob[32:]
    return gzip.decompress(AESGCM(_key(pw, salt)).decrypt(iv, ct, MAGIC))


def password():
    return os.environ.get("SITE_PASSWORD", "")


def load(base):
    """docs/<base>.enc 또는 docs/<base>.json 을 읽어 dict 로 돌려줍니다. 없으면 None."""
    pw = password()
    enc, plain = f"docs/{base}.enc", f"docs/{base}.json"
    if pw and os.path.exists(enc):
        try:
            return json.loads(decrypt(open(enc, "rb").read(), pw))
        except Exception as e:  # 비밀번호가 바뀌었거나 파일이 깨진 경우: 덮어쓰지 않고 멈춥니다.
            sys.exit(f"{enc} 를 열지 못했습니다(비밀번호가 바뀌었는지 확인하세요): {e}")
    if os.path.exists(plain):
        return json.load(open(plain, encoding="utf-8"))
    return None


def save(base, obj):
    pw = password()
    enc, plain = f"docs/{base}.enc", f"docs/{base}.json"
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    os.makedirs("docs", exist_ok=True)
    if pw:
        with open(enc, "wb") as f:
            f.write(encrypt(raw, pw))
        if os.path.exists(plain):
            os.remove(plain)
    else:
        with open(plain, "wb") as f:
            f.write(raw)
