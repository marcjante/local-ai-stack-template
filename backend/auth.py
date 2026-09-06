"""
auth.py

Dos formas de autenticarse, para que cada proyecto elija según necesite:

  - API key simple (X-API-Key): un secreto compartido, sin usuarios ni
    roles — lo que ya había. Sigue disponible en backend/main.py.

  - JWT con roles (Authorization: Bearer <token>): permite distinguir
    quién llama y con qué permisos, sin compartir un único secreto entre
    todo el mundo. Útil en cuanto haya más de un tipo de cliente (un
    frontend con usuarios, un servicio interno, n8n...).

Emite tokens con /auth/token (solo con la API key maestra, a modo de
"quien tiene la key raíz puede emitir tokens con el rol que quiera") y
protege endpoints con @require_role("admin") o @require_role("lector").
"""

import os
import functools
import time

import jwt
from flask import request, jsonify

JWT_SECRET = os.environ.get("JWT_SECRET", "changeme-in-.env")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = int(os.environ.get("JWT_EXPIRY_SECONDS", str(24 * 3600)))


def issue_token(subject: str, role: str) -> str:
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def require_role(*allowed_roles):
    """
    Exige un JWT válido en `Authorization: Bearer <token>` con uno de los
    roles permitidos. Si no se pasa ningún rol, solo exige que el token
    sea válido (cualquier rol vale).
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return jsonify({"error": "falta cabecera Authorization: Bearer <token>"}), 401
            token = header.removeprefix("Bearer ").strip()
            try:
                claims = decode_token(token)
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "token expirado"}), 401
            except jwt.InvalidTokenError as e:
                return jsonify({"error": f"token inválido: {e}"}), 401

            if allowed_roles and claims.get("role") not in allowed_roles:
                return jsonify({"error": f"rol '{claims.get('role')}' sin permiso, requiere uno de {allowed_roles}"}), 403

            request.jwt_claims = claims
            return fn(*args, **kwargs)
        return wrapper
    return decorator
