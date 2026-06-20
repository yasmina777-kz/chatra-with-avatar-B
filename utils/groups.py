GROUPS = [
    "ИСУ-21", "ИСУ-22", "ИСУ-23", "ИСУ-24",
]

def search_groups(query: str):
    if not query:
        return GROUPS
    return [g for g in GROUPS if query.upper() in g.upper()]