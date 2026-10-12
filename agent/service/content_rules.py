"""Content-only identifiers shared by policy, monitoring and telemetry."""
import ipaddress
import re

CATEGORIES = {'education', 'entertainment', 'social', 'games', 'age_inappropriate', 'unknown'}


def process_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9_ .()+-]{1,120}\.exe', value.lower()):
        raise ValueError('Expected executable basename')
    return value.lower()


def domain(value):
    if not isinstance(value, str):
        raise ValueError('Expected domain')
    value = value.strip().rstrip('.').lower().encode('idna').decode('ascii')
    if len(value) > 253 or len(value.split('.')) < 2 or any(
        not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in value.split('.')
    ):
        raise ValueError('Expected hostname without URL, path or port')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError('IP address is not a domain')


def validate_content(payload):
    apps = payload.get('apps', [])
    if not isinstance(apps, list):
        raise ValueError('apps must be a list')
    names, hashes = set(), set()
    for rule in apps:
        if not isinstance(rule, dict) or set(rule) - {'name', 'sha256', 'action'}:
            raise ValueError('Invalid app rule')
        name = process_name(rule.get('name'))
        sha = rule.get('sha256')
        if rule.get('action') not in {'allow', 'block'} or name in names:
            raise ValueError('Invalid or duplicate app rule')
        names.add(name)
        if sha is not None:
            if not isinstance(sha, str) or not re.fullmatch('[0-9a-fA-F]{64}', sha) or sha.lower() in hashes:
                raise ValueError('Invalid or duplicate SHA-256')
            hashes.add(sha.lower())
    rules = payload.get('domains', [])
    if rules == []:  # Signed week-two payload must remain byte-for-byte unchanged.
        return
    if not isinstance(rules, dict) or set(rules) - {'allow', 'block', 'blocked_categories', 'safe_search'}:
        raise ValueError('Invalid domain policy')
    lists = []
    for key in ('allow', 'block'):
        values = rules.get(key, [])
        if not isinstance(values, list) or len(values) > 1000:
            raise ValueError('Invalid domain list')
        normalized = [domain(item) for item in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError('Duplicate domain')
        lists.append(set(normalized))
    categories = rules.get('blocked_categories', [])
    if lists[0] & lists[1] or not isinstance(categories, list) or any(item not in CATEGORIES for item in categories):
        raise ValueError('Conflicting domain or unknown category')
    if type(rules.get('safe_search', False)) is not bool:
        raise ValueError('safe_search must be boolean')
