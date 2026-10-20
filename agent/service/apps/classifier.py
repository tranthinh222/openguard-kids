def classify(name, sha256, rules):
    """A matching hash wins even when the executable has been renamed."""
    if sha256:
        for rule in rules:
            if (rule.get('sha256') or '').lower() == sha256:
                return rule['action'], 'sha256'
    for rule in rules:
        if rule['name'].lower() == name.lower():
            return rule['action'], 'process_name'
    return 'allow', 'default'
