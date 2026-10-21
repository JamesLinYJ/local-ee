"""Application permissions, independent of the identity provider and UI."""
ROLES = {
    'admin': frozenset({'datasets:manage', 'users:manage', 'jobs:manage', 'audit:read', 'compute:run'}),
    'dataset_manager': frozenset({'datasets:manage', 'compute:run'}),
    'researcher': frozenset({'compute:run'}),
    'viewer': frozenset(),
}


def permissions(role):
    return sorted(ROLES.get(role, ()))


def permits(account, permission):
    return account.get('scope') == 'user' and permission in ROLES.get(account.get('role'), ())


def enforce_write(account, method, path):
    """Readonly accounts cannot write through alternate workbench/openEO/EE routes."""
    if method not in {'GET', 'HEAD', 'OPTIONS'} and path != '/workbench/logout':
        if 'compute:run' not in ROLES.get(account.get('role'), ()):
            from openeo_driver.errors import OpenEOApiException
            raise OpenEOApiException('当前账号为只读成员', code='PermissionDenied', status_code=403)
