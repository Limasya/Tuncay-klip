"""
API Key yönetimi (IP_PART6 Bölüm 33.6).

- Plaintext anahtar asla saklanmaz; yalnızca SHA-256 hash tutulur.
- Plaintext yalnızca oluşturma anında bir kez döndürülür.
- Timing-safe karşılaştırma kullanılır.
- Zero-downtime rotasyon için istemci başına 2 aktif anahtar desteklenir.
- 90 gün sonra otomatik expire, 75. günde uyarı.
"""
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

KEY_PREFIX = "ip_"
DEFAULT_TTL_DAYS = 90
WARN_BEFORE_DAYS = 15  # => 75. günde uyarı
MAX_ACTIVE_KEYS_PER_CLIENT = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_api_key() -> tuple[str, str]:
    """
    Yeni bir API anahtarı üretir.

    Returns:
        (plaintext_key, sha256_hash) — plaintext yalnızca bir kez gösterilir,
        depolamada yalnızca hash tutulur.
    """
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def verify_api_key(presented: str, stored_hash: str) -> bool:
    """Sunulan plaintext anahtarı, saklanan hash ile timing-safe karşılaştırır."""
    digest = hashlib.sha256(presented.encode()).hexdigest()
    return secrets.compare_digest(digest, stored_hash)


@dataclass
class ApiKey:
    """Depolanan bir API anahtarı kaydı (plaintext içermez)."""

    key_hash: str
    client_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    created_at: datetime = field(default_factory=_now)
    expires_at: datetime = field(
        default_factory=lambda: _now() + timedelta(days=DEFAULT_TTL_DAYS)
    )
    revoked: bool = False
    last_used_at: Optional[datetime] = None

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        return (now or _now()) >= self.expires_at

    def is_active(self, now: Optional[datetime] = None) -> bool:
        return not self.revoked and not self.is_expired(now)

    def needs_rotation_warning(self, now: Optional[datetime] = None) -> bool:
        """Süre dolmasına WARN_BEFORE_DAYS'ten az kaldıysa True (75. gün)."""
        now = now or _now()
        return self.is_active(now) and (self.expires_at - now) <= timedelta(
            days=WARN_BEFORE_DAYS
        )


class ApiKeyStore:
    """
    Basit, thread-safe olmayan in-memory API key deposu.

    Production'da bu arayüz bir DB tablosuyla (models/database.py) değiştirilir;
    ancak imza aynı kalır. Yaşam döngüsü: create → active → rotate → revoke.
    """

    def __init__(self) -> None:
        self._keys: dict[str, ApiKey] = {}  # key_hash -> ApiKey

    # -- oluşturma / rotasyon -------------------------------------------------
    def create(
        self,
        client_id: str,
        scopes: Iterable[str] = (),
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> tuple[str, ApiKey]:
        """
        Yeni anahtar oluşturur ve depoya ekler.

        Zero-downtime rotasyon: istemci başına en fazla MAX_ACTIVE_KEYS_PER_CLIENT
        aktif anahtar tutulur; limit aşılırsa en eski aktif anahtar iptal edilir.

        Returns:
            (plaintext_key, ApiKey) — plaintext yalnızca burada döner.
        """
        active = self.active_for_client(client_id)
        if len(active) >= MAX_ACTIVE_KEYS_PER_CLIENT:
            oldest = min(active, key=lambda k: k.created_at)
            oldest.revoked = True

        raw, digest = generate_api_key()
        record = ApiKey(
            key_hash=digest,
            client_id=client_id,
            scopes=frozenset(scopes),
            expires_at=_now() + timedelta(days=ttl_days),
        )
        self._keys[digest] = record
        return raw, record

    # -- doğrulama ------------------------------------------------------------
    def authenticate(self, presented: str) -> Optional[ApiKey]:
        """
        Sunulan plaintext anahtarı doğrular.

        Returns:
            Aktif eşleşen ApiKey ya da None (bulunamadı/expired/revoked).
        """
        digest = hashlib.sha256(presented.encode()).hexdigest()
        record = self._keys.get(digest)
        if record is None:
            return None
        # timing-safe teyit (dictionary lookup zaten hash bazlı ama tutarlılık için)
        if not verify_api_key(presented, record.key_hash):
            return None
        if not record.is_active():
            return None
        record.last_used_at = _now()
        return record

    # -- yönetim --------------------------------------------------------------
    def revoke(self, key_hash: str) -> bool:
        record = self._keys.get(key_hash)
        if record is None:
            return False
        record.revoked = True
        return True

    def active_for_client(self, client_id: str) -> list[ApiKey]:
        return [
            k for k in self._keys.values()
            if k.client_id == client_id and k.is_active()
        ]

    def keys_needing_rotation(self) -> list[ApiKey]:
        return [k for k in self._keys.values() if k.needs_rotation_warning()]

    def purge_expired(self) -> int:
        """Süresi dolmuş/iptal edilmiş anahtarları depodan siler; silinen sayısı döner."""
        to_delete = [h for h, k in self._keys.items() if not k.is_active()]
        for h in to_delete:
            del self._keys[h]
        return len(to_delete)
