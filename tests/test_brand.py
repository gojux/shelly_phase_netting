import struct

import pytest
from homeassistant.setup import async_setup_component

import custom_components.shelly_phase_netting  # noqa: F401  (makes the package discoverable)

pytest.importorskip("homeassistant.components.brands")   # local brand images: Home Assistant 2026.3+

BRAND_IMAGES = [
    "icon.png", "icon@2x.png", "dark_icon.png", "dark_icon@2x.png",
    "logo.png", "logo@2x.png", "dark_logo.png", "dark_logo@2x.png",
]


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG file"
    return struct.unpack(">II", data[16:24])


@pytest.mark.parametrize("image", BRAND_IMAGES)
async def test_home_assistant_serves_the_brand_images(hass, hass_client, enable_custom_integrations, image):
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    response = await client.get(f"/api/brands/integration/shelly_phase_netting/{image}")
    assert response.status == 200, await response.text()
    assert response.content_type == "image/png"
    width, height = png_size(await response.read())
    factor = 2 if "@2x" in image else 1
    if "icon" in image:
        assert (width, height) == (256 * factor, 256 * factor)   # icons must be square
    else:
        assert height == 128 * factor and width > height          # logos are landscape
