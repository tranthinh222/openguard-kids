from service.content_rules import CATEGORIES, domain


def suffix_match(host, rule):
    return host == rule or host.endswith('.' + rule)


class DomainMatcher:
    def __init__(self, dataset=None):
        self.mapping = {}
        if dataset:
            self.update(dataset)

    def update(self, dataset):
        mapping = dataset.get('domains')
        if not isinstance(mapping, dict) or len(mapping) > 100000:
            raise ValueError('Invalid category dataset')
        normalized = {domain(key): value for key, value in mapping.items()}
        if any(value not in CATEGORIES for value in normalized.values()):
            raise ValueError('Unknown category')
        self.mapping = normalized

    def decide(self, host, policy):
        host = domain(host)
        rules = policy.payload.get('domains', {}) if policy else {}
        rules = rules if isinstance(rules, dict) else {}
        for action in ('allow', 'block'):
            if any(suffix_match(host, domain(rule)) for rule in rules.get(action, [])):
                return action, 'explicit_' + action
        category = next((self.mapping[key] for key in sorted(self.mapping, key=len, reverse=True)
                         if suffix_match(host, key)), 'unknown')
        return ('block' if category in rules.get('blocked_categories', []) else 'allow'), category
