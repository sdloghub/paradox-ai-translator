"""Developer-only automatic per-Mod translation patch generation."""


def export(service, item, files, version_id):
    config = service.config()
    if not config.get('developer_mode', False) or not config['aggregate_export']:
        return {'enabled': False}
    from mod_export import build
    return build(service, item, automatic=True, version_id=version_id)
