<!-- Ported from Hermes Agent skill collection. Original author: Hermes / Nous Research. -->
<!-- Licensed under the same terms as the original (MIT). -->

---
name: satellite-osint
description: "Satellite imagery access and geospatial OSINT for reconnaissance"
category: osint
tags: [satellite, imagery, geospatial, osint, recon, remote-sensing]
version: 1.0.0
created_by: agent
---

# Satellite Imagery OSINT

Access satellite imagery from multiple free sources for reconnaissance and geospatial analysis.

## Available Sources

### Free (no auth required)
- **OSM Satellite Tiles** — OpenStreetMap satellite layer
- **EOX Sentinel-2 Cloudless** — ESA Sentinel-2 cloudless mosaic (10m resolution)
- **Bing Satellite** — Microsoft Bing satellite imagery

### Free (account required)
- **NASA Earthdata** — Landsat, MODIS, Sentinel data (earthdata.nasa.gov)
- **USGS EarthExplorer** — Landsat historical data (earthexplorer.usgs.gov)

### Paid (API key required)
- **Mapbox** — High-res satellite tiles
- **Google Earth Engine** — Most comprehensive
- **Planet Labs** — Daily global imagery
- **Maxar** — Very high resolution

## Usage

```bash
# Get satellite tiles for a location
python3 ~/.hermes/scripts/satellite.py location <lat> <lon> [zoom]

# Geocode an address to coordinates
python3 ~/.hermes/scripts/satellite.py coords "Tashkent, Uzbekistan"

# Download satellite imagery at multiple zoom levels
python3 ~/.hermes/scripts/satellite.py download <lat> <lon> --output <path>

# Search NASA Earthdata (needs auth)
python3 ~/.hermes/scripts/satellite.py search "Sentinel-2" --bbox <w,s,e,n>
```

## Zoom Levels Reference

| Zoom | Resolution | Use Case |
|------|------------|----------|
| 1-3 | Country/Continent | Overview |
| 4-7 | Region/City | Area recon |
| 8-11 | City/District | Neighborhood |
| 12-15 | Street level | Building identification |
| 16-18 | High detail | Object/vehicle detection |

## OSINT Workflow

1. **Geocode** target location → get lat/lon
2. **Download** satellite tiles at multiple zoom levels
3. **Analyze** imagery for:
   - Building layouts and structures
   - Vehicle presence and types
   - Perimeter security (fences, walls)
   - Access points (gates, roads)
   - Nearby landmarks and terrain
4. **Cross-reference** with:
   - Google Maps/Street View
   - Social media geotags
   - Public records

## Output

Satellite tiles are cached in `~/.hermes/cache/satellite/`
Images are 256x256 pixel JPEG/PNG tiles.

## Limitations

- Free sources provide 10-30m resolution (not sub-meter)
- Historical imagery limited on free tiers
- Cloud cover may obscure targets
- No real-time feeds on free sources
