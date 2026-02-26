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
        import json
        import datetime
        url = f"{CARTO_API.base_url}v3/tokens"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        payload = {
            "name": f"QGIS deck.gl export {timestamp}",
            "grants": grants,
            "allowed_apis": ["maps"],
        }
        info(f"Token request payload: {json.dumps(payload)}")
        response = CARTO_API.session.post(
            url,
            headers={
                "Authorization": f"Bearer {CARTO_API.token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if not response.ok:
            error(f"Token API response ({response.status_code}): {response.text}")
            response.raise_for_status()
        result = response.json()
        token = result.get("token") or result.get("accessToken")
        info(f"Created scoped export token for {len(grants)} table(s)")
        return token
    except Exception as e:
        error(f"Failed to create export token: {e}")
        return None
