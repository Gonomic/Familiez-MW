# Familiez MW - Synology NAS productie checklist

Deze checklist is gericht op het probleem dat login wel lukt, maar de rol op `none` blijft staan (dus geen add/edit/delete rechten).

## 1) Runtime `.env` op NAS invullen

Zet in je NAS runtime-omgeving (Container Manager > Project > Environment) minimaal:

```env
# OIDC
SYNOLOGY_OIDC_DISCOVERY_URL=https://sso.jouwdomein.tld/webman/sso/.well-known/openid-configuration
SYNOLOGY_CLIENT_ID=<client-id>
SYNOLOGY_CLIENT_SECRET=<client-secret>
SYNOLOGY_REDIRECT_URI=https://familiez.jouwdomein.tld/auth/callback
SYNOLOGY_OIDC_VERIFY_SSL=true
SYNOLOGY_JWT_LEEWAY=120

# LDAP role mapping
SYNOLOGY_LDAP_URL=ldaps://<jouw-ldap-host>:636
SYNOLOGY_LDAP_BIND_DN=uid=<bind-user>,cn=users,dc=<domain>,dc=<tld>
SYNOLOGY_LDAP_BIND_PASSWORD=<bind-password>
SYNOLOGY_LDAP_GROUP_ADMIN_DN=cn=Familiez_Admin,cn=groups,dc=<domain>,dc=<tld>
SYNOLOGY_LDAP_GROUP_USER_DN=cn=Familiez_Users,cn=groups,dc=<domain>,dc=<tld>
SYNOLOGY_LDAP_MEMBER_DN_TEMPLATE=uid={username},cn=users,dc=<domain>,dc=<tld>
SYNOLOGY_LDAP_GROUP_ADMIN_NAME=Familiez_Admin
SYNOLOGY_LDAP_GROUP_USER_NAME=Familiez_Users
SYNOLOGY_LDAP_GROUP_MEMBER_ATTRIBUTES=member,uniqueMember,memberUid
SYNOLOGY_STRIP_USERNAME_DOMAIN=true
SYNOLOGY_LDAP_TIMEOUT=8
```

Let op:
- Als LDAP geen `uid` gebruikt maar bijvoorbeeld `cn`, pas `SYNOLOGY_LDAP_MEMBER_DN_TEMPLATE` aan.
- Als je username als `naam@domein` in token staat, laat `SYNOLOGY_STRIP_USERNAME_DOMAIN=true`.

## 2) MW image opnieuw bouwen en deployen

Via shell op de NAS in de map waar je compose-project staat:

```bash
docker compose build --no-cache mw
docker compose up -d mw
```

Als je FE ook herstart wilt meenemen:

```bash
docker compose up -d --force-recreate mw fe
```

## 3) Controleer of nieuwe env echt in de container zit

```bash
docker compose exec mw env | grep -E 'SYNOLOGY_(LDAP|OIDC|CLIENT|REDIRECT|STRIP|JWT)'
```

## 4) Controleer logs tijdens inloggen

```bash
docker compose logs -f mw
```

Zoek naar:
- `LDAP config incomplete`
- `LDAP query failed`
- `Access denied: user ... role 'none'`

## 5) Verifieer role endpoint handmatig

1. Log in op de app in browser.
2. Pak access token uit `localStorage` (key: `familiez_access_token`).
3. Test endpoint:

```bash
curl -s https://api.jouwdomein.tld/auth/me \
  -H "Authorization: Bearer <access_token>" | jq
```

Verwacht voor admin:

```json
{
  "username": "jouw.user",
  "role": "admin",
  "is_admin": true,
  "is_user": true,
  "groups": ["Familiez_Admin", "Familiez_Users"]
}
```

## 6) Veelvoorkomende oorzaken als role `none` blijft

- Verkeerde `SYNOLOGY_LDAP_MEMBER_DN_TEMPLATE` (uid/cn/ou mismatch).
- Groep-DN niet exact juist (`cn=... ,cn=groups,...`).
- LDAP gebruikt ander member-attribuut dan `member`.
- Token bevat username met domein, LDAP entry zonder domein.
- NAS draait nog oude image (geen rebuild of verkeerde tag).

## 7) Korte rollback

Als direct terug moet:

```bash
docker compose pull mw
docker compose up -d mw
```

(of herstel vorige image-tag als je met tags werkt)
