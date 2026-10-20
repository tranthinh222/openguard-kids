"""Exercise the shipped server dataset through the actual agent matcher, offline."""
import csv
from pathlib import Path
from types import SimpleNamespace

from service.dns.matcher import DomainMatcher


def test_shipped_categories_and_subdomains():
    path = Path(__file__).resolve().parents[2] / 'server/app/data/domain_categories.csv'
    with path.open(encoding='utf-8', newline='') as stream:
        mapping = {r['domain']: r['category'] for r in csv.DictReader(stream)}
    matcher = DomainMatcher({'domains': mapping})
    policy = SimpleNamespace(payload={'domains': {'blocked_categories': [
        'entertainment', 'social', 'games', 'age_inappropriate', 'unknown']}})
    for domain, category in mapping.items():
        if domain in matcher.safety_domains:
            assert matcher.decide(domain, policy) == ('allow', 'safety_exemption')
            continue
        expected = 'allow' if category == 'education' else 'block'
        assert matcher.decide(domain, policy) == (expected, category)
        assert matcher.decide('www.' + domain, policy) == (expected, category)
    assert matcher.decide('unclassified.example.test', policy) == ('block', 'unknown')
    policy.payload['domains']['allow'] = ['example.com']
    policy.payload['domains']['block'] = ['example.com']
    assert matcher.decide('example.com', policy) == ('allow', 'explicit_allow')
