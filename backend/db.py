import os
import json
import secrets
import hashlib
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "users.json")

class Database:
    def __init__(self):
        self.load()

    def load(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.users = data.get("users", {})
                    self.sessions = data.get("sessions", {})
            except Exception:
                self.users = {}
                self.sessions = {}
        else:
            self.users = {}
            self.sessions = {}

    def save(self):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "users": self.users,
                "sessions": self.sessions
            }, f, ensure_ascii=False, indent=2)

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def register(self, username, password):
        if username in self.users:
            return False, "이미 존재하는 아이디입니다."
        self.users[username] = {
            "password": self._hash_password(password),
            "created_at": datetime.now().isoformat()
        }
        self.save()
        return True, "가입 성공"

    def login(self, username, password):
        user = self.users.get(username)
        if not user or user.get("password") != self._hash_password(password):
            return None
        
        # 이전 세션 정리 (선택사항)
        session_token = secrets.token_hex(32)
        self.sessions[session_token] = {
            "username": username,
            "created_at": datetime.now().isoformat()
        }
        self.save()
        return session_token

    def google_login(self, email, name, picture=None):
        if email not in self.users:
            self.users[email] = {
                "name": name,
                "picture": picture,
                "auth_provider": "google",
                "created_at": datetime.now().isoformat()
            }
        else:
            # Update user info if they already exist
            self.users[email]["name"] = name
            self.users[email]["picture"] = picture
            if "auth_provider" not in self.users[email]:
                self.users[email]["auth_provider"] = "google"
        
        session_token = secrets.token_hex(32)
        self.sessions[session_token] = {
            "username": email,
            "created_at": datetime.now().isoformat()
        }
        self.save()
        return session_token

    def get_user_from_session(self, token):
        session = self.sessions.get(token)
        if session:
            return session["username"]
        return None

    def logout(self, token):
        if token in self.sessions:
            del self.sessions[token]
            self.save()

db = Database()
