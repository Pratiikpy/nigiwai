# Third-party material

Nigiwai is MIT licensed (see LICENSE). It includes or builds on the following.

| Material | Where | Licence | Source |
|---|---|---|---|
| Bricolage Grotesque (font, static instances) | `apps/api/src/nigiwai_api/assets/fonts/` | SIL Open Font License 1.1 | https://github.com/ateliertriay/bricolage |
| DM Mono (font) | `apps/api/src/nigiwai_api/assets/fonts/` | SIL Open Font License 1.1 | https://github.com/googlefonts/dm-mono |
| Common-password list (entries of 10+ characters from `Pwdb_top-100000.txt`) | `apps/api/src/nigiwai_api/assets/common_passwords.txt` | MIT (SecLists, Daniel Miessler) | https://github.com/danielmiessler/SecLists |
| `@qloo/qloo-harness` (dev tool, not redistributed) | root `package.json` | MIT | https://www.npmjs.com/package/@qloo/qloo-harness |
| MapLibre GL JS (the map renderer, loaded in the browser) | `apps/web` dependency | BSD-3-Clause | https://github.com/maplibre/maplibre-gl-js |
| H3 (hexagonal cells for the catchment layer) | `apps/api` dependency | Apache-2.0 | https://github.com/uber/h3-py |
| Anthropic Python SDK (the AI-alone comparison) | `apps/api` dependency | MIT | https://github.com/anthropics/anthropic-sdk-python |
| Map tiles and style: OpenFreeMap, OpenMapTiles schema, OpenStreetMap data | fetched by the owner's browser at runtime, not redistributed | Free service ([terms](https://openfreemap.org/tos/)); data ODbL, attribution shown on the map | https://openfreemap.org |
| Place lookup for neighbourhood names: OpenStreetMap Nominatim | queried by the API at runtime, answers cached | ODbL data under the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/): one request a second, identified, cached | https://nominatim.openstreetmap.org |
| MusicBrainz (public lineups) | queried by the API at runtime | CC0 | https://musicbrainz.org |

The font licences are in `apps/api/src/nigiwai_api/assets/fonts/OFL-*.txt`.
