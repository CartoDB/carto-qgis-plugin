from carto.core.api import CARTO_API
from carto.core.layers import (
    is_carto_layer,
    fqn_from_layer,
    connection_from_layer,
)
from carto.core.logging import info, error


def create_export_token(layers):
    """Create a scoped API Access Token for the given CARTO layers.

    Uses POST /v3/tokens to create a permanent, read-only token scoped
    to only the specific tables being exported.

    Returns the token string, or None on failure.
    """
    grants = []
    seen = set()
    for layer in layers:
        if not is_carto_layer(layer):
            continue
        conn = connection_from_layer(layer)
        fqn = fqn_from_layer(layer)
        key = (conn, fqn)
        if key not in seen:
            seen.add(key)
            grants.append({
                "connection_name": conn,
                "source": fqn,
            })

    if not grants:
        error("No CARTO layers found for token creation")
        return None

    try:
        url = f"{CARTO_API.base_url}v3/tokens"
        response = CARTO_API.session.post(
            url,
            headers={"Authorization": f"Bearer {CARTO_API.token}"},
            json={"grants": grants},
        )
        response.raise_for_status()
        token = response.json()["token"]
        info(f"Created scoped export token for {len(grants)} table(s)")
        return token
    except Exception as e:
        error(f"Failed to create export token: {e}")
        return None
