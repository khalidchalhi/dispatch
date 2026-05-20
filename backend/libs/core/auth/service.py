from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol, cast

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from redis import asyncio as redis_async

from libs.core.auth.models import ApiKey, User
from libs.core.auth.repository import AuthRepository
from libs.core.auth.schemas import CurrentActor
from libs.core.config import Settings, get_settings
from libs.core.db.session import get_session_factory
from libs.core.db.uow import UnitOfWork
from libs.core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ValidationError,
)
from libs.core.logging import get_logger

logger = get_logger("core.auth")


class LoginAttemptStore(Protocol):
    async def is_locked(self, identifier: str) -> bool: ...

    async def register_failure(self, identifier: str) -> None: ...

    async def clear_failures(self, identifier: str) -> None: ...


class InMemoryLoginAttemptStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._attempts: dict[str, tuple[int, datetime]] = {}
        self._locks: dict[str, datetime] = {}

    async def is_locked(self, identifier: str) -> bool:
        now = datetime.now(UTC)
        lock_until = self._locks.get(identifier)
        if lock_until is None:
            return False
        if lock_until > now:
            return True
        self._locks.pop(identifier, None)
        return False

    async def register_failure(self, identifier: str) -> None:
        now = datetime.now(UTC)
        window_deadline = now + timedelta(seconds=self._settings.auth_login_attempt_window_seconds)
        attempts, expires_at = self._attempts.get(identifier, (0, window_deadline))

        if expires_at <= now:
            attempts = 0
            expires_at = window_deadline

        attempts += 1
        self._attempts[identifier] = (attempts, expires_at)

        if attempts >= self._settings.auth_lockout_max_attempts:
            self._locks[identifier] = now + timedelta(seconds=self._settings.auth_lockout_seconds)

    async def clear_failures(self, identifier: str) -> None:
        self._attempts.pop(identifier, None)
        self._locks.pop(identifier, None)


class RedisLoginAttemptStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis = cast(
            redis_async.Redis,
            redis_async.from_url(settings.redis_url, decode_responses=True),  # type: ignore[no-untyped-call]
        )
        self._fallback = InMemoryLoginAttemptStore(settings)

    def _fail_key(self, identifier: str) -> str:
        return f"auth:login:fail:{identifier.lower()}"

    def _lock_key(self, identifier: str) -> str:
        return f"auth:login:lock:{identifier.lower()}"

    async def is_locked(self, identifier: str) -> bool:
        try:
            return bool(await self._redis.exists(self._lock_key(identifier)))
        except Exception:
            logger.warning("auth.login_lock.redis_unavailable")
            return await self._fallback.is_locked(identifier)

    async def register_failure(self, identifier: str) -> None:
        try:
            fail_key = self._fail_key(identifier)
            lock_key = self._lock_key(identifier)
            pipe = self._redis.pipeline(transaction=True)
            pipe.incr(fail_key)
            pipe.expire(fail_key, self._settings.auth_login_attempt_window_seconds)
            results = await pipe.execute()
            attempts = int(results[0])

            if attempts >= self._settings.auth_lockout_max_attempts:
                await self._redis.set(lock_key, "1", ex=self._settings.auth_lockout_seconds)
        except Exception:
            logger.warning("auth.login_lock.redis_unavailable")
            await self._fallback.register_failure(identifier)

    async def clear_failures(self, identifier: str) -> None:
        try:
            await self._redis.delete(self._fail_key(identifier), self._lock_key(identifier))
        except Exception:
            logger.warning("auth.login_lock.redis_unavailable")
            await self._fallback.clear_failures(identifier)


@dataclass(slots=True)
class LoginResult:
    authenticated: bool
    requires_mfa: bool
    mfa_token: str | None = None
    session_cookie: str | None = None


@dataclass(slots=True)
class CreatedAPIKey:
    model: ApiKey
    plaintext_key: str


class AuthService:
    def __init__(self, settings: Settings, attempts: LoginAttemptStore | None = None) -> None:
        self._settings = settings
        self._session_factory = get_session_factory()
        self._attempts = attempts or RedisLoginAttemptStore(settings)

        self._password_hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost,
            parallelism=settings.argon2_parallelism,
        )
        self._session_serializer = URLSafeTimedSerializer(
            settings.secret_key,
            salt="dispatch-session",
        )
        self._mfa_login_serializer = URLSafeTimedSerializer(
            settings.secret_key,
            salt="dispatch-mfa-login",
        )
        self._mfa_enroll_serializer = URLSafeTimedSerializer(
            settings.secret_key,
            salt="dispatch-mfa-enroll",
        )
        self._mfa_cipher = Fernet(self._resolve_mfa_key(settings))

    @property
    def password_hasher(self) -> PasswordHasher:
        return self._password_hasher

    def hash_password(self, password: str) -> str:
        return self._password_hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        return self._verify_password(password_hash, password)

    async def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginResult:
        identifier = email.lower().strip()
        if await self._attempts.is_locked(identifier):
            raise RateLimitedError("Too many failed login attempts. Try again later.")

        async with self._session_factory() as session:
            repo = AuthRepository(session)
            user = await repo.get_user_by_email(identifier)

        if user is None:
            await self._attempts.register_failure(identifier)
            raise AuthenticationError("Invalid credentials")

        if not self._verify_password(user.password_hash, password):
            await self._attempts.register_failure(identifier)
            raise AuthenticationError("Invalid credentials")

        await self._attempts.clear_failures(identifier)

        if user.mfa_secret:
            mfa_token = self._mfa_login_serializer.dumps({"user_id": user.id})
            return LoginResult(authenticated=False, requires_mfa=True, mfa_token=mfa_token)

        cookie = await self._create_session_and_audit(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            action="auth.login",
            actor_type="user",
            actor_id=user.id,
        )
        return LoginResult(authenticated=True, requires_mfa=False, session_cookie=cookie)

    async def verify_mfa_login(
        self,
        *,
        mfa_token: str,
        code: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginResult:
        payload = self._deserialize_mfa_token(mfa_token, flow="login")
        user_id = payload.get("user_id")

        if not user_id:
            raise AuthenticationError("Invalid MFA token")

        async with self._session_factory() as session:
            repo = AuthRepository(session)
            user = await repo.get_user_by_id(user_id)

        if user is None or not user.mfa_secret:
            raise AuthenticationError("Invalid MFA token")

        if not self._verify_totp_code(user.mfa_secret, code):
            await self._attempts.register_failure(user.email)
            raise AuthenticationError("Invalid MFA code")

        await self._attempts.clear_failures(user.email)

        cookie = await self._create_session_and_audit(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            action="auth.login.mfa",
            actor_type="user",
            actor_id=user.id,
        )
        return LoginResult(authenticated=True, requires_mfa=False, session_cookie=cookie)

    async def logout(self, *, session_cookie: str | None) -> None:
        if not session_cookie:
            return

        token = self._unsign_session_cookie(session_cookie)
        if token is None:
            return

        token_hash = self._hash_secret(token)
        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            await repo.revoke_session_by_hash(token_hash)

    async def resolve_current_actor(
        self,
        *,
        authorization: str | None,
        session_cookie: str | None,
    ) -> CurrentActor:
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            user, api_key = await self._authenticate_api_key(token)
            return CurrentActor(actor_type="api_key", user=user, api_key=api_key)

        if session_cookie:
            user = await self._authenticate_session_cookie(session_cookie)
            return CurrentActor(actor_type="user", user=user)

        raise AuthenticationError("Authentication required")

    async def _authenticate_session_cookie(self, session_cookie: str) -> User:
        token = self._unsign_session_cookie(session_cookie)
        if token is None:
            raise AuthenticationError("Invalid session")

        token_hash = self._hash_secret(token)
        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            session_row = await repo.get_active_session_by_hash(token_hash)
            if session_row is None:
                raise AuthenticationError("Invalid session")

            await repo.touch_session_last_seen(session_row.id)
            user = await repo.get_user_by_id(session_row.user_id)
            if user is None:
                raise AuthenticationError("Invalid session")
            return user

    async def _authenticate_api_key(self, token: str) -> tuple[User, ApiKey]:
        prefix, key_hash = self._parse_and_hash_api_key(token)
        now = datetime.now(UTC)

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            candidates = await repo.get_api_key_candidates_by_prefix(prefix)
            match = next(
                (item for item in candidates if hmac.compare_digest(item.key_hash, key_hash)),
                None,
            )

            if match is None or match.revoked_at is not None:
                raise AuthenticationError("Invalid API key")

            if match.expires_at:
                expires_at = match.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= now:
                    raise AuthenticationError("API key expired")

            user = await repo.get_user_by_id(match.created_by)
            if user is None:
                raise AuthenticationError("Invalid API key")

            await repo.touch_api_key_last_used(match.id)
            return user, match

    async def _create_session_and_audit(
        self,
        *,
        user: User,
        ip_address: str | None,
        user_agent: str | None,
        action: str,
        actor_type: str,
        actor_id: str | None,
    ) -> str:
        raw_session_token = secrets.token_urlsafe(32)
        raw_csrf_token = secrets.token_urlsafe(24)
        session_hash = self._hash_secret(raw_session_token)
        csrf_hash = self._hash_secret(raw_csrf_token)

        expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.session_ttl_seconds)

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            session_row = await repo.create_user_session(
                user_id=user.id,
                session_token_hash=session_hash,
                csrf_token_hash=csrf_hash,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await repo.update_last_login(user.id)
            await repo.write_audit_log(
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                resource_type="user_session",
                resource_id=session_row.id,
                after_state={"expires_at": expires_at.isoformat()},
                ip_address=ip_address,
                user_agent=user_agent,
            )

        return self._session_serializer.dumps({"token": raw_session_token})

    def create_mfa_enrollment_token(self, *, user_id: str, encrypted_secret: str) -> str:
        return self._mfa_enroll_serializer.dumps(
            {
                "user_id": user_id,
                "encrypted_secret": encrypted_secret,
            }
        )

    def decode_mfa_enrollment_token(self, token: str) -> tuple[str, str]:
        payload = self._deserialize_mfa_token(token, flow="enroll")
        user_id = payload.get("user_id")
        encrypted_secret = payload.get("encrypted_secret")
        if not user_id or not encrypted_secret:
            raise ValidationError("Invalid MFA enrollment token")
        return user_id, encrypted_secret

    def encrypt_mfa_secret(self, secret: str) -> str:
        return self._mfa_cipher.encrypt(secret.encode("utf-8")).decode("utf-8")

    def decrypt_mfa_secret(self, encrypted_secret: str) -> str:
        try:
            return self._mfa_cipher.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise AuthenticationError("Invalid MFA secret") from exc

    def verify_totp(self, encrypted_secret: str, code: str) -> bool:
        secret = self.decrypt_mfa_secret(encrypted_secret)
        return pyotp.TOTP(secret).verify(code, valid_window=1)

    def generate_api_key_material(self) -> tuple[str, str, str, str]:
        prefix = secrets.token_hex(4)
        secret = secrets.token_hex(16)
        plaintext = f"ak_live_{prefix}_{secret}"
        hashed = self._hash_secret(plaintext)
        last4 = secret[-4:]
        return plaintext, prefix, last4, hashed

    def _verify_password(self, password_hash: str, password: str) -> bool:
        try:
            verified = self._password_hasher.verify(password_hash, password)
            return bool(verified)
        except VerifyMismatchError:
            return False

    def _deserialize_mfa_token(self, token: str, *, flow: str) -> dict[str, str]:
        serializer = self._mfa_login_serializer if flow == "login" else self._mfa_enroll_serializer
        max_age = (
            self._settings.mfa_challenge_ttl_seconds
            if flow == "login"
            else self._settings.mfa_enrollment_ttl_seconds
        )

        try:
            payload = serializer.loads(token, max_age=max_age)
        except (BadSignature, SignatureExpired) as exc:
            raise AuthenticationError("Invalid MFA token") from exc

        if not isinstance(payload, dict):
            raise AuthenticationError("Invalid MFA token")
        return payload

    def _verify_totp_code(self, encrypted_secret: str, code: str) -> bool:
        return self.verify_totp(encrypted_secret, code)

    def _unsign_session_cookie(self, session_cookie: str) -> str | None:
        try:
            payload = self._session_serializer.loads(
                session_cookie,
                max_age=self._settings.session_ttl_seconds,
            )
        except (BadSignature, SignatureExpired):
            return None

        if not isinstance(payload, dict):
            return None

        token = payload.get("token")
        return token if isinstance(token, str) else None

    def _parse_and_hash_api_key(self, token: str) -> tuple[str, str]:
        parts = token.split("_", 3)
        if len(parts) != 4 or parts[0] != "ak" or parts[1] != "live":
            raise AuthenticationError("Invalid API key")

        prefix = parts[2]
        secret = parts[3]
        if len(prefix) < 6 or len(secret) < 8:
            raise AuthenticationError("Invalid API key")
        return prefix, self._hash_secret(token)

    @staticmethod
    def _hash_secret(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _resolve_mfa_key(settings: Settings) -> bytes:
        if settings.mfa_kms_data_key and settings.mfa_kms_data_key.strip():
            encoded_key = settings.mfa_kms_data_key.strip().encode("utf-8")
            try:
                decoded = base64.urlsafe_b64decode(encoded_key)
            except binascii.Error as exc:
                raise ValidationError("MFA_KMS_DATA_KEY must be a valid Fernet key") from exc

            if len(decoded) != 32:
                raise ValidationError("MFA_KMS_DATA_KEY must decode to 32 bytes")
            return encoded_key

        digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)


class UserService:
    def __init__(self, auth_service: AuthService) -> None:
        self._auth = auth_service
        self._settings = auth_service._settings
        self._session_factory = get_session_factory()

    async def create_user(
        self,
        *,
        actor: CurrentActor,
        email: str,
        password: str,
        role: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> User:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            existing = await repo.get_user_by_email(email)
            if existing is not None:
                raise ConflictError("A user with this email already exists")

            password_hash = self._auth.hash_password(password)
            user = await repo.create_user(email=email, password_hash=password_hash, role=role)
            await repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="user.create",
                resource_type="user",
                resource_id=user.id,
                after_state={"email": user.email, "role": user.role},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return user

    async def list_users(self, *, actor: CurrentActor) -> list[User]:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")

        async with self._session_factory() as session:
            repo = AuthRepository(session)
            return await repo.list_users()

    async def get_user(self, *, actor: CurrentActor) -> User:
        return actor.user

    async def get_user_by_id(self, *, actor: CurrentActor, user_id: str) -> User:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")

        async with self._session_factory() as session:
            repo = AuthRepository(session)
            user = await repo.get_user_by_id(user_id)
            if user is None:
                raise NotFoundError("User not found")
            return user

    async def disable_user(
        self,
        *,
        actor: CurrentActor,
        user_id: str,
        reason: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            user = await repo.get_user_by_id(user_id)
            if user is None:
                raise NotFoundError("User not found")

            await repo.disable_user(user_id)
            await repo.revoke_sessions_for_user(user_id)
            await repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="user.disable",
                resource_type="user",
                resource_id=user_id,
                before_state={
                    "deleted_at": user.deleted_at.isoformat() if user.deleted_at else None
                },
                after_state={"deleted_at": datetime.now(UTC).isoformat(), "reason": reason},
                ip_address=ip_address,
                user_agent=user_agent,
            )

    async def reset_user_mfa(
        self,
        *,
        actor: CurrentActor,
        user_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            user = await repo.get_user_by_id(user_id)
            if user is None:
                raise NotFoundError("User not found")

            had_mfa = bool(user.mfa_secret)
            await repo.clear_mfa_secret(user.id)
            revoked = await repo.revoke_sessions_for_user(user.id)
            await repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="user.mfa.reset",
                resource_type="user",
                resource_id=user.id,
                before_state={"mfa_enabled": had_mfa},
                after_state={"mfa_enabled": False, "revoked_sessions": revoked},
                ip_address=ip_address,
                user_agent=user_agent,
            )

    async def change_password(
        self,
        *,
        actor: CurrentActor,
        current_password: str,
        new_password: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        user = actor.user
        if not self._auth.verify_password(user.password_hash, current_password):
            raise AuthenticationError("Current password is invalid")

        new_hash = self._auth.hash_password(new_password)

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            await repo.update_user_password_hash(user.id, new_hash)
            revoked = await repo.revoke_sessions_for_user(user.id)
            await repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=user.id,
                action="user.password.change",
                resource_type="user",
                resource_id=user.id,
                after_state={"revoked_sessions": revoked},
                ip_address=ip_address,
                user_agent=user_agent,
            )

    async def enroll_mfa_start(self, *, actor: CurrentActor) -> tuple[str, str]:
        secret = pyotp.random_base32()
        encrypted_secret = self._auth.encrypt_mfa_secret(secret)
        token = self._auth.create_mfa_enrollment_token(
            user_id=actor.user.id,
            encrypted_secret=encrypted_secret,
        )
        uri = pyotp.TOTP(secret).provisioning_uri(name=actor.user.email, issuer_name="dispatch")
        return token, uri

    async def verify_mfa_enrollment(
        self,
        *,
        actor: CurrentActor,
        enrollment_token: str,
        code: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        user_id, encrypted_secret = self._auth.decode_mfa_enrollment_token(enrollment_token)

        if user_id != actor.user.id:
            raise PermissionDeniedError("MFA enrollment token does not belong to this user")

        if not self._auth.verify_totp(encrypted_secret, code):
            raise ValidationError("Invalid MFA verification code")

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            await repo.set_mfa_secret(actor.user.id, encrypted_secret)
            await repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="auth.mfa.enroll",
                resource_type="user",
                resource_id=actor.user.id,
                after_state={"mfa_enabled": True},
                ip_address=ip_address,
                user_agent=user_agent,
            )

    async def create_api_key(
        self,
        *,
        actor: CurrentActor,
        name: str,
        expires_at: datetime | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CreatedAPIKey:
        plaintext, prefix, last4, hashed = self._auth.generate_api_key_material()

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            api_key = await repo.create_api_key(
                name=name,
                key_hash=hashed,
                key_prefix=prefix,
                key_last4=last4,
                created_by=actor.user.id,
                expires_at=expires_at,
            )
            await repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="api_key.create",
                resource_type="api_key",
                resource_id=api_key.id,
                after_state={
                    "key_prefix": prefix,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return CreatedAPIKey(model=api_key, plaintext_key=plaintext)

    async def rotate_api_key(
        self,
        *,
        actor: CurrentActor,
        api_key_id: str,
        name: str | None,
        expires_at: datetime | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CreatedAPIKey:
        plaintext, prefix, last4, hashed = self._auth.generate_api_key_material()

        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            old_key = await repo.get_api_key_for_user(actor.user.id, api_key_id)
            if old_key is None:
                raise NotFoundError("API key not found")

            await repo.revoke_api_key(old_key.id)

            api_key = await repo.create_api_key(
                name=name or old_key.name,
                key_hash=hashed,
                key_prefix=prefix,
                key_last4=last4,
                created_by=actor.user.id,
                expires_at=expires_at if expires_at is not None else old_key.expires_at,
            )
            await repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="api_key.rotate",
                resource_type="api_key",
                resource_id=api_key.id,
                after_state={"rotated_from": old_key.id, "key_prefix": prefix},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return CreatedAPIKey(model=api_key, plaintext_key=plaintext)

    async def revoke_api_key(
        self,
        *,
        actor: CurrentActor,
        api_key_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        async with UnitOfWork(self._session_factory) as uow:
            repo = AuthRepository(uow.require_session())
            api_key = await repo.get_api_key_for_user(actor.user.id, api_key_id)
            if api_key is None:
                raise NotFoundError("API key not found")

            await repo.revoke_api_key(api_key_id)
            await repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="api_key.revoke",
                resource_type="api_key",
                resource_id=api_key_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

    async def list_api_keys(self, *, actor: CurrentActor) -> list[ApiKey]:
        async with self._session_factory() as session:
            repo = AuthRepository(session)
            return await repo.list_api_keys_for_user(actor.user.id)


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    return AuthService(get_settings())


@lru_cache(maxsize=1)
def get_user_service() -> UserService:
    return UserService(get_auth_service())
