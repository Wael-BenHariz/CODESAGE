"""
JWT Token Manager
Handles creation, validation, and refresh of JWT tokens.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from app.config import settings


class TokenManager:
    """
    JWT token manager for creating and validating access/refresh tokens.
    
    Uses HS256 algorithm with configurable expiration times.
    """

    def __init__(
        self,
        secret_key: str = None,
        algorithm: str = None,
        access_token_expire_minutes: int = None,
        refresh_token_expire_days: int = None,
    ):
        self.secret_key = secret_key or settings.SECRET_KEY
        self.algorithm = algorithm or settings.ALGORITHM
        self.access_token_expire_minutes = access_token_expire_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
        self.refresh_token_expire_days = refresh_token_expire_days or settings.REFRESH_TOKEN_EXPIRE_DAYS

    def create_access_token(
        self,
        subject: str,
        expires_delta: Optional[timedelta] = None,
        additional_claims: Optional[dict] = None,
    ) -> str:
        """
        Create a JWT access token.
        
        Args:
            subject: Token subject (typically user ID)
            expires_delta: Optional custom expiration time
            additional_claims: Extra claims to include in the token
            
        Returns:
            Encoded JWT token string
        """
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=self.access_token_expire_minutes)

        to_encode = {
            "sub": str(subject),
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        
        if additional_claims:
            to_encode.update(additional_claims)
        
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(
        self,
        subject: str,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """
        Create a JWT refresh token with longer expiration.
        
        Args:
            subject: Token subject (typically user ID)
            expires_delta: Optional custom expiration time
            
        Returns:
            Encoded JWT refresh token string
        """
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(days=self.refresh_token_expire_days)

        to_encode = {
            "sub": str(subject),
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "refresh",
        }
        
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def verify_token(
        self,
        token: str,
        token_type: Optional[str] = None,
    ) -> dict:
        """
        Verify and decode a JWT token.
        
        Args:
            token: JWT token string to verify
            token_type: Expected token type ('access' or 'refresh'), None for any
            
        Returns:
            Decoded token payload
            
        Raises:
            JWTError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
            )
            
            # Validate token type if specified
            if token_type and payload.get("type") != token_type:
                raise JWTError(f"Invalid token type, expected {token_type}")
            
            return payload
            
        except JWTError:
            raise

    def decode_token(self, token: str) -> Optional[dict]:
        """
        Decode a token without verification (for debugging).
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded payload or None if invalid
        """
        try:
            return jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"verify_signature": False},
            )
        except JWTError:
            return None

    def get_token_expiration(self, token: str) -> Optional[datetime]:
        """
        Get the expiration time of a token.
        
        Args:
            token: JWT token string
            
        Returns:
            Expiration datetime or None
        """
        payload = self.decode_token(token)
        if payload and "exp" in payload:
            return datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        return None


# Global token manager instance
token_manager = TokenManager()


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
    additional_claims: Optional[dict] = None,
) -> str:
    """Create an access token using the global token manager."""
    return token_manager.create_access_token(subject, expires_delta, additional_claims)


def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a refresh token using the global token manager."""
    return token_manager.create_refresh_token(subject, expires_delta)


def verify_token(
    token: str,
    token_type: Optional[str] = None,
) -> dict:
    """Verify a token using the global token manager."""
    return token_manager.verify_token(token, token_type)