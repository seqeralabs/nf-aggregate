# assets/ — Static Assets

## Brand

### brand.yml

Seqera brand color definitions. Single source of truth for all report colors.

| Token                       | Hex       | Usage                                             |
| --------------------------- | --------- | ------------------------------------------------- |
| Deep Green (accent)         | `#087F68` | Hover, links, text on light bg, stat numbers      |
| Seqera Green (accent_light) | `#31C9AC` | CTA buttons, icons, decorative. **NEVER as text** |
| Soft Green (accent_surface) | `#E2F7F3` | Tag bg, card bg, section bg                       |
| Dark Brand (heading)        | `#201637` | Headings, footer, primary text                    |
| Border                      | `#CFD0D1` | Border color                                      |
| Neutral                     | `#F7F7F7` | Section backgrounds                               |
| White                       | `#ffffff` | Page bg, text on dark surfaces                    |

**Critical rule:** Never use white text on Seqera Green bg — use Dark Brand instead.

### seqera-echarts-theme.json

Full eCharts theme derived from brand.yml. Registered via `echarts.registerTheme('seqera', ...)`. All charts init with `echarts.init(el, 'seqera')` — don't add per-chart color overrides.

### seqera_logo_color.svg

Official Seqera logo from `seqeralabs/logos` repo. Injected via `--logo` CLI flag as `{{ logo_svg }}` Jinja variable.

### Typography

Inter font (Google Fonts CDN, weights 300-600). Degular (commercial, headings) approximated with Inter at heavier weights (h1→600, h2/h3→500).

## Input

- `samplesheet.csv` — example input samplesheet
- `schema_input.json` — nf-schema input validation schema
