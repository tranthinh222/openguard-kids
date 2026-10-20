"""Curated category rules; CSV is the single source for API and report appendix."""
import csv
from pathlib import Path

from app.schemas.content_rules import CATEGORIES, normalize_domain


def load_dataset():
    domains = {}
    simulated = []
    with (Path(__file__).parents[1] / 'data' / 'domain_categories.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            domain = normalize_domain(row['domain'])
            category = row['category']
            if domain in domains or category not in CATEGORIES:
                raise ValueError(f'Invalid or duplicate category entry: {domain}')
            domains[domain] = category
            if row['test_only'] == 'true':
                simulated.append(domain)
    return {
        'version': 2,
        'categories': CATEGORIES,
        'domains': domains,
        'default_category': 'unknown',
        'rule_priority': ['explicit_allow', 'explicit_block', 'category', 'default_allow'],
        'match_subdomains': True,
        'test_only_domains': simulated,
    }


CATEGORY_DATASET = load_dataset()
