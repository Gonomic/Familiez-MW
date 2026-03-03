import auth


def test_extract_username_from_claims_strips_domain_by_default(monkeypatch):
    monkeypatch.setenv("SYNOLOGY_STRIP_USERNAME_DOMAIN", "true")
    claims = {"preferred_username": "admin.user@dekknet.com"}

    username = auth._extract_username_from_claims(claims)

    assert username == "admin.user"


def test_extract_username_from_claims_can_keep_domain(monkeypatch):
    monkeypatch.setenv("SYNOLOGY_STRIP_USERNAME_DOMAIN", "false")
    claims = {"preferred_username": "admin.user@dekknet.com"}

    username = auth._extract_username_from_claims(claims)

    assert username == "admin.user@dekknet.com"


def test_member_value_matches_dn_and_memberuid():
    member_dn = "uid=admin.user,cn=users,dc=dekknet,dc=com"

    assert auth._member_value_matches(member_dn, member_dn, "admin.user")
    assert auth._member_value_matches("admin.user", member_dn, "admin.user")
    assert auth._member_value_matches("uid=admin.user,ou=people,dc=dekknet,dc=com", member_dn, "admin.user")


def test_merge_claim_groups_promotes_admin(monkeypatch):
    monkeypatch.setenv("SYNOLOGY_LDAP_GROUP_ADMIN_NAME", "Familiez_Admin")
    monkeypatch.setenv("SYNOLOGY_LDAP_GROUP_USER_NAME", "Familiez_Users")

    access = {
        "username": "admin.user",
        "role": "none",
        "is_admin": False,
        "is_user": False,
        "groups": [],
    }
    claims = {"groups": ["Familiez_Admin"]}

    merged = auth._merge_claim_groups(access, claims)

    assert merged["is_admin"] is True
    assert merged["is_user"] is True
    assert merged["role"] == "admin"
    assert "Familiez_Admin" in merged["groups"]


def test_resolve_ldap_role_from_claims_merges_claims(monkeypatch):
    monkeypatch.setenv("SYNOLOGY_STRIP_USERNAME_DOMAIN", "true")
    monkeypatch.setenv("SYNOLOGY_LDAP_GROUP_ADMIN_NAME", "Familiez_Admin")
    monkeypatch.setenv("SYNOLOGY_LDAP_GROUP_USER_NAME", "Familiez_Users")

    def fake_get_user_ldap_role(username):
        assert username == "admin.user"
        return {
            "username": username,
            "role": "none",
            "is_admin": False,
            "is_user": False,
            "groups": [],
        }

    monkeypatch.setattr(auth, "get_user_ldap_role", fake_get_user_ldap_role)

    claims = {"preferred_username": "admin.user@dekknet.com", "groups": ["Familiez_Admin"]}
    merged = auth.resolve_ldap_role_from_claims(claims)

    assert merged["role"] == "admin"
    assert merged["is_admin"] is True
