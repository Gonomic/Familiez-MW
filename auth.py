import os
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

import jwt
import requests
from ldap3 import Server, Connection, ALL, BASE
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

_DISCOVERY_CACHE: Dict[str, Any] = {}
_JWKS_CACHE: Dict[str, Any] = {}

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_NONE = "none"


def _get_env_bool(name: str, default: str = "true") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _get_env_int(name: str, default: str) -> int:
    return int(os.getenv(name, default).strip())


def _get_env_csv(name: str, default: str) -> List[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_discovery_url() -> str:
    url = os.getenv("SYNOLOGY_OIDC_DISCOVERY_URL", "").strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SYNOLOGY_OIDC_DISCOVERY_URL is not configured",
        )
    return url


def _get_discovery_cache_ttl() -> int:
    return int(os.getenv("SYNOLOGY_OIDC_DISCOVERY_TTL", "3600"))


def _get_jwks_cache_ttl() -> int:
    return int(os.getenv("SYNOLOGY_JWKS_TTL", "3600"))


def _fetch_discovery() -> Dict[str, Any]:
    url = _get_discovery_url()
    verify_ssl = _get_env_bool("SYNOLOGY_OIDC_VERIFY_SSL", "true")
    response = requests.get(url, timeout=10, verify=verify_ssl)
    response.raise_for_status()
    return response.json()


def _get_discovery() -> Dict[str, Any]:
    now = time.time()
    ttl = _get_discovery_cache_ttl()
    cached = _DISCOVERY_CACHE.get("data")
    cached_at = _DISCOVERY_CACHE.get("timestamp", 0)
    if cached and (now - cached_at) < ttl:
        return cached
    discovery = _fetch_discovery()
    _DISCOVERY_CACHE["data"] = discovery
    _DISCOVERY_CACHE["timestamp"] = now
    return discovery


def _fetch_jwks(jwks_uri: str) -> Dict[str, Any]:
    verify_ssl = _get_env_bool("SYNOLOGY_OIDC_VERIFY_SSL", "true")
    response = requests.get(jwks_uri, timeout=10, verify=verify_ssl)
    response.raise_for_status()
    return response.json()


def _get_jwks() -> Dict[str, Any]:
    now = time.time()
    ttl = _get_jwks_cache_ttl()
    cached = _JWKS_CACHE.get("data")
    cached_at = _JWKS_CACHE.get("timestamp", 0)
    if cached and (now - cached_at) < ttl:
        return cached
    discovery = _get_discovery()
    jwks_uri = discovery.get("jwks_uri")
    if not jwks_uri:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="jwks_uri is missing from discovery document",
        )
    jwks = _fetch_jwks(jwks_uri)
    _JWKS_CACHE["data"] = jwks
    _JWKS_CACHE["timestamp"] = now
    return jwks


def _find_jwk(kid: str, jwks: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    keys = jwks.get("keys", [])
    for key in keys:
        if key.get("kid") == kid:
            return key
    return None


def verify_sso_token(token: str) -> Dict[str, Any]:
    discovery = _get_discovery()
    issuer = discovery.get("issuer")
    jwks = _get_jwks()

    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        logger.warning("Invalid JWT header: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    jwk = _find_jwk(kid, jwks)
    if not jwk:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
    except Exception as exc:
        logger.warning("Failed to parse JWK: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    audience = os.getenv("SYNOLOGY_CLIENT_ID", "").strip()
    if not audience:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SYNOLOGY_CLIENT_ID is not configured",
        )

    try:
        leeway_seconds = _get_env_int("SYNOLOGY_JWT_LEEWAY", "120")
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[unverified_header.get("alg", "RS256")],
            audience=audience,
            issuer=issuer,
            leeway=leeway_seconds,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError as exc:
        logger.warning("Token validation failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    return auth_header.split(" ", 1)[1].strip()


def _normalize_username(username: str) -> str:
    normalized = str(username or "").strip()
    strip_domain = _get_env_bool("SYNOLOGY_STRIP_USERNAME_DOMAIN", "true")
    if strip_domain and "@" in normalized:
        normalized = normalized.split("@", 1)[0]
    return normalized


def _extract_username_from_claims(claims: Dict[str, Any]) -> str:
    username = (
        claims.get("preferred_username")
        or claims.get("username")
        or claims.get("user_name")
        or claims.get("upn")
        or claims.get("email")
        or claims.get("sub")
        or ""
    )
    return _normalize_username(str(username))


def _member_value_matches(value: Any, member_dn: str, username: str) -> bool:
    value_text = str(value or "").strip().lower()
    if not value_text:
        return False

    member_dn_lower = member_dn.lower()
    username_lower = username.lower()

    if value_text == member_dn_lower or value_text == username_lower:
        return True

    if f"uid={username_lower}," in value_text or f"cn={username_lower}," in value_text:
        return True

    return False


def _run_ldap_group_check(member_dn: str, group_dn: str) -> bool:
    """Check if a user (identified by member_dn) is member of a group using ldap3."""
    ldap_url = os.getenv("SYNOLOGY_LDAP_URL", "").strip()
    bind_dn = os.getenv("SYNOLOGY_LDAP_BIND_DN", "").strip()
    bind_password = os.getenv("SYNOLOGY_LDAP_BIND_PASSWORD", "").strip()

    if not ldap_url or not bind_dn or not bind_password:
        logger.warning("LDAP config incomplete: set SYNOLOGY_LDAP_URL, SYNOLOGY_LDAP_BIND_DN, and SYNOLOGY_LDAP_BIND_PASSWORD")
        return False

    timeout_seconds = _get_env_int("SYNOLOGY_LDAP_TIMEOUT", "8")
    member_attributes = _get_env_csv(
        "SYNOLOGY_LDAP_GROUP_MEMBER_ATTRIBUTES",
        "member,uniqueMember,memberUid",
    )
    username = _normalize_username(member_dn.split(",", 1)[0].split("=", 1)[-1])
    
    # ldap3 doesn't validate SSL by default for self-signed certs
    # Create server with get_info=ALL for better debugging
    try:
        server = Server(ldap_url, get_info=ALL, connect_timeout=timeout_seconds)
        conn = Connection(
            server,
            user=bind_dn,
            password=bind_password,
            auto_bind=True,
            receive_timeout=timeout_seconds
        )
        
        # Read group entry and inspect common member attributes used by Synology/LDAP variants
        conn.search(
            search_base=group_dn,
            search_filter="(objectClass=*)",
            search_scope=BASE,
            attributes=member_attributes,
        )

        is_member = False
        if conn.entries:
            attribute_map = conn.entries[0].entry_attributes_as_dict
            for attribute_name in member_attributes:
                for member_value in attribute_map.get(attribute_name, []) or []:
                    if _member_value_matches(member_value, member_dn, username):
                        is_member = True
                        break
                if is_member:
                    break

        conn.unbind()

        return is_member

    except Exception as exc:
        logger.warning("LDAP query failed for group %s: %s", group_dn, exc)
        return False


def get_user_ldap_role(username: str) -> Dict[str, Any]:
    username_value = _normalize_username(username)
    if not username_value:
        return {
            "username": "",
            "role": ROLE_NONE,
            "is_admin": False,
            "is_user": False,
            "groups": [],
        }

    member_dn_template = os.getenv(
        "SYNOLOGY_LDAP_MEMBER_DN_TEMPLATE",
        "uid={username},cn=users,dc=dekknet,dc=com",
    )
    member_dn = member_dn_template.format(username=username_value)

    admin_group_dn = os.getenv(
        "SYNOLOGY_LDAP_GROUP_ADMIN_DN",
        "cn=Familiez_Admin,cn=groups,dc=dekknet,dc=com",
    )
    user_group_dn = os.getenv(
        "SYNOLOGY_LDAP_GROUP_USER_DN",
        "cn=Familiez_Users,cn=groups,dc=dekknet,dc=com",
    )

    is_admin = _run_ldap_group_check(member_dn, admin_group_dn)
    is_user = _run_ldap_group_check(member_dn, user_group_dn)

    groups = []
    if is_admin:
        groups.append("Familiez_Admin")
    if is_user:
        groups.append("Familiez_Users")

    role = ROLE_ADMIN if is_admin else ROLE_USER if is_user else ROLE_NONE

    return {
        "username": username_value,
        "role": role,
        "is_admin": is_admin,
        "is_user": is_user,
        "groups": groups,
    }


def _extract_groups_from_claims(claims: Dict[str, Any]) -> List[str]:
    possible_group_values = []
    for key in ("groups", "group", "roles", "role"):
        raw_value = claims.get(key)
        if isinstance(raw_value, list):
            possible_group_values.extend(raw_value)
        elif isinstance(raw_value, str):
            possible_group_values.append(raw_value)

    normalized_groups: List[str] = []
    for group_value in possible_group_values:
        text = str(group_value or "").strip()
        if not text:
            continue
        if "," in text:
            normalized_groups.extend([part.strip() for part in text.split(",") if part.strip()])
        else:
            normalized_groups.append(text)

    return normalized_groups


def _group_matches(group_value: str, expected_name: str) -> bool:
    group_text = str(group_value or "").strip().lower()
    expected_text = str(expected_name or "").strip().lower()
    if not group_text or not expected_text:
        return False
    return group_text == expected_text or group_text.endswith(f"={expected_text}")


def _merge_claim_groups(access: Dict[str, Any], claims: Dict[str, Any]) -> Dict[str, Any]:
    admin_group_name = os.getenv("SYNOLOGY_LDAP_GROUP_ADMIN_NAME", "Familiez_Admin").strip()
    user_group_name = os.getenv("SYNOLOGY_LDAP_GROUP_USER_NAME", "Familiez_Users").strip()

    claim_groups = _extract_groups_from_claims(claims)
    is_admin_from_claims = any(_group_matches(group, admin_group_name) for group in claim_groups)
    is_user_from_claims = any(_group_matches(group, user_group_name) for group in claim_groups)

    is_admin = bool(access.get("is_admin") or is_admin_from_claims)
    is_user = bool(access.get("is_user") or is_user_from_claims or is_admin)

    combined_groups = list(access.get("groups") or [])
    if is_admin and admin_group_name not in combined_groups:
        combined_groups.append(admin_group_name)
    if is_user and user_group_name not in combined_groups:
        combined_groups.append(user_group_name)

    role = ROLE_ADMIN if is_admin else ROLE_USER if is_user else ROLE_NONE

    return {
        **access,
        "role": role,
        "is_admin": is_admin,
        "is_user": is_user,
        "groups": combined_groups,
    }


def resolve_ldap_role_from_claims(claims: Dict[str, Any]) -> Dict[str, Any]:
    username = _extract_username_from_claims(claims)
    access = get_user_ldap_role(username)
    return _merge_claim_groups(access, claims)


def require_sso_auth(request: Request) -> Dict[str, Any]:
    """FastAPI dependency that returns verified token claims.

    Usage:
        @app.get("/protected")
        def protected_route(user=Depends(require_sso_auth)):
            return {"user": user}
    """
    token = _extract_bearer_token(request)
    return verify_sso_token(token)


def exchange_authorization_code(code: str, code_verifier: str = "") -> Tuple[str, Dict[str, Any]]:
    """Exchange OAuth authorization code for JWT token and extract user info.
    
    Args:
        code: Authorization code from OAuth provider
        code_verifier: PKCE code verifier (optional, not used by Synology)
    
    Returns:
        Tuple of (id_token, user_info_dict) where user_info_dict contains
        username, role, groups, is_admin, is_user
    """
    discovery = _get_discovery()
    token_endpoint = discovery.get("token_endpoint")
    if not token_endpoint:
        logger.error("token_endpoint is missing from discovery document")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="token_endpoint is missing from discovery document",
        )
    
    client_id = os.getenv("SYNOLOGY_CLIENT_ID", "")
    if not client_id:
        logger.error("SYNOLOGY_CLIENT_ID is not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SYNOLOGY_CLIENT_ID is not configured",
        )
    
    # Get redirect URI from environment (must match what's configured on Synology)
    redirect_uri = os.getenv("SYNOLOGY_REDIRECT_URI", "http://localhost:5173/auth/callback")
    
    # Prepare token exchange request (Synology doesn't support PKCE)
    token_request = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    
    # Add client secret if configured (required by Synology)
    client_secret = os.getenv("SYNOLOGY_CLIENT_SECRET", "").strip()
    if client_secret:
        token_request["client_secret"] = client_secret
    
    verify_ssl = _get_env_bool("SYNOLOGY_OIDC_VERIFY_SSL", "true")
    
    try:
        # OAuth 2.0 requires application/x-www-form-urlencoded, not JSON
        response = requests.post(token_endpoint, data=token_request, timeout=10, verify=verify_ssl)
        response.raise_for_status()
        token_data = response.json()
        
        # Force output to stdout/logs with print (bypasses logger config)
        print(f"=== TOKEN EXCHANGE DEBUG ===")
        print(f"Keys: {list(token_data.keys())}")
        
        # Log what Synology returns to check for refresh_token support
        logger.info(f"Token response contains keys: {list(token_data.keys())}")
        if "expires_in" in token_data:
            logger.info(f"Token expires in: {token_data['expires_in']} seconds ({token_data['expires_in'] / 3600:.1f} hours)")
            print(f"expires_in: {token_data['expires_in']} seconds")
        if "refresh_token" in token_data:
            logger.info("Refresh token available in response (currently not used)")
        
        # Compare access_token vs id_token expiry claims - use print to bypass logger
        if "access_token" in token_data:
            print(f"Decoding access_token...")
            try:
                access_decoded = jwt.decode(token_data["access_token"], options={"verify_signature": False})
                access_exp = access_decoded.get("exp", 0)
                print(f"access_token exp: {access_exp}")
                logger.warning(f"access_token exp claim: {access_exp} (epoch)")
            except Exception as e:
                print(f"ERROR decoding access_token: {type(e).__name__}: {e}")
                logger.warning(f"Could not decode access_token: {type(e).__name__}: {e}")
        
        if "id_token" not in token_data:
            logger.error(f"Token response missing id_token (JWT)")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to obtain ID token from OAuth provider",
            )
        
        # Decode id_token to compare expiry
        id_token = token_data["id_token"]
        try:
            id_decoded = jwt.decode(id_token, options={"verify_signature": False})
            id_exp = id_decoded.get("exp", 0)
            logger.warning(f"id_token exp claim: {id_exp} (epoch)")
        except Exception as e:
            logger.warning(f"Could not decode id_token: {e}")
        
        # Extract user info and resolve LDAP role
        user_access = resolve_ldap_role_from_claims(id_decoded)
        
        logger.info(f"Token exchange successful for user: {user_access.get('username')} (role: {user_access.get('role')})")
        
        return id_token, user_access
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Token exchange request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status: {e.response.status_code}, body: {e.response.text}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token exchange failed",
        )

def require_admin_role(request: Request) -> None:
    """
    Helper function to check if the authenticated user has admin role.
    Raises HTTPException with 403 Forbidden if user is not admin.
    
    Use in endpoints:
        @app.post("/SomeWriteOp")
        def some_endpoint(request: Request, data: dict):
            require_admin_role(request)  # Add this line
            # ... rest of endpoint code ...
    """
    user_access = getattr(request.state, "user_access", {}) or {}
    is_admin = user_access.get("is_admin", False)
    
    if not is_admin:
        username = user_access.get("username", "unknown")
        role = user_access.get("role", "none")
        logger.warning(f"Access denied: user '{username}' with role '{role}' attempted write operation")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. Only admins can perform this operation (current role: {role})"
        )