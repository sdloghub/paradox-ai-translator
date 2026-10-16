"""Release templates deliberately contain no account credentials or local paths."""


def release_settings():
    from workshop_app import DEFAULT_CONFIG
    return {'config.json': dict(DEFAULT_CONFIG),
            'providers.json': {'format': 'workshop-providers-v1', 'profiles': {}},
            'completed.json': {'format': 'workshop-completed-v1', 'entries': []}}
