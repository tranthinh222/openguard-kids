import csv
from pathlib import Path

from app.services.domain_categories import CATEGORY_DATASET
from app.schemas.content_rules import CATEGORIES, normalize_domain


def test_category_dataset_submission_and_safe_fixtures():
    dataset = CATEGORY_DATASET
    assert dataset['version'] == 2
    assert len(dataset['domains']) >= 200
    assert set(dataset['domains'].values()) == set(CATEGORIES)
    assert sum(category == 'education' for category in dataset['domains'].values()) >= 20
    assert all(normalize_domain(domain) == domain for domain in dataset['domains'])
    fixtures = {domain for domain, category in dataset['domains'].items() if category == 'age_inappropriate'}
    assert fixtures == {'example.com', 'example.net', 'example.org', 'age-restricted.example.test'}
    assert set(dataset['test_only_domains']) == fixtures
    assert dataset['default_category'] == 'unknown'


def test_csv_is_unique_and_vietnam_is_prioritized():
    path = Path(__file__).parents[1] / 'app/data/domain_categories.csv'
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(CATEGORY_DATASET['domains'])
    assert sum(row['region'] == 'VN' for row in rows) >= 100
    assert all(row['source_url'].startswith('https://') for row in rows)
