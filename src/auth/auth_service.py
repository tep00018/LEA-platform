"""Registration, login and login tokens."""

import logging
from typing import Dict, List, Optional, Tuple

from src.auth.tokens import TokenStore
from src.core.validation import is_valid_username
from src.storage.redis_client import LEARedisClient

logger = logging.getLogger(__name__)

MAX_PASSWORD_LENGTH = 128


class AuthService:
    def __init__(self, redis_url: str):
        self.redis_client = LEARedisClient(redis_url)
        self.tokens = TokenStore(self.redis_client)

    def login_user(self, username: str, password: str) -> Tuple[bool, Optional[str], str]:
        """Check credentials; on success issue a login token. Returns (ok, token, message)."""
        if len(password or "") > MAX_PASSWORD_LENGTH or not self.redis_client.verify_credentials(username, password):
            # Only a well-formed username is logged: a password typed into the wrong field isn't
            logger.info(f"Failed login for {username if is_valid_username(username) else '<invalid username>'}")
            return False, None, "Invalid username or password"
        token, _expires = self.tokens.issue(username)
        return True, token, f"Welcome back, {username}!"

    def register_user(self, username: str, password: str, full_name: str,
                      selected_courses: List[str] = None) -> Tuple[bool, str]:
        if not is_valid_username(username):
            return False, "Usernames must be 3-32 characters: letters, numbers, dots, dashes or underscores."
        if len(password or "") > MAX_PASSWORD_LENGTH:
            return False, f"Passwords can be at most {MAX_PASSWORD_LENGTH} characters."
        return self.redis_client.create_user(username, password, full_name, enrolled_courses=selected_courses)

    def validate_session(self, token: str) -> Optional[str]:
        """The username a login token belongs to, or None if it's unknown or expired."""
        return self.tokens.validate(token)

    def logout(self, token: str) -> None:
        self.tokens.revoke(token)

    def get_user_data(self, username: str) -> Dict:
        try:
            return {
                "username": username,
                "enrolled_courses": self.redis_client.get_user_courses(username),
                "progress": self.redis_client.get_user_progress(username),
            }
        except Exception as e:
            logger.error(f"Error getting user data for {username}: {e}")
            return {"username": username, "enrolled_courses": [], "progress": {}}
