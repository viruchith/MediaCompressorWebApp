# MediaCompressorWebApp — Current State

## Last Updated
2026-07-04T09:45:00+05:30

## Completed Changes
- [x] Created `VERSION` file (canonical version: `2.0.0`)
- [x] Centralized version metadata in `app/version.py` (`VERSION`, `APP_AUTHOR`, `APP_COPYRIGHT_YEAR`, `GITHUB_URL`)
- [x] Added `/version` and `/api/v1/version` API endpoints
- [x] Added copyright footer to all web templates via `_footer.html` partial
- [x] Created full `LICENSE` file (GNU GPL v3.0 + project copyright notice)
- [x] Created `CHANGELOG.md` (Keep a Changelog format, semver)
- [x] Rewrote `README.md` (badges, TOC, screenshots placeholders, GPL-3.0, versioning section)

## Files Created / Modified

| File | Summary |
|------|---------|
| `VERSION` | **Created** — canonical version string `2.0.0` |
| `LICENSE` | **Created** — full GPL-3.0 text + project copyright |
| `CHANGELOG.md` | **Created** — release history (1.0.0, 2.0.0, Unreleased) |
| `README.md` | **Modified** — professional README with badges, GPL, versioning |
| `app/version.py` | **Created** — reads VERSION file, exports metadata constants |
| `app/__init__.py` | **Modified** — re-exports VERSION from version.py |
| `app/factory.py` | **Modified** — context processor injects version, author, copyright |
| `app/routes.py` | **Modified** — `/version` and `/api/v1/version` endpoints |
| `templates/_footer.html` | **Created** — shared footer partial |
| `templates/index.html` | **Modified** — includes footer partial |
| `templates/settings.html` | **Modified** — includes footer partial |
| `templates/job_detail.html` | **Modified** — includes footer partial |
| `static/css/style.css` | **Modified** — `.site-footer` styles |

## Version Info

| Item | Value |
|------|-------|
| **Current version** | `2.0.0` |
| **Canonical source** | [`VERSION`](VERSION) file at project root |
| **Python module** | [`app/version.py`](app/version.py) — `VERSION`, `APP_AUTHOR`, `APP_COPYRIGHT_YEAR` |
| **Author** | Viruchith Ganesan |
| **Copyright** | 2025–2026 |
| **License** | GNU GPL v3.0 |

**To bump version:** edit `VERSION`, then update `CHANGELOG.md` and README badge/version references.

## Known Issues / TODOs

- Screenshot placeholders in README point to `docs/images/` — add actual screenshots when available
- Eventlet deprecation warning on Python 3.14
- README screenshot paths will 404 until images are added

## How to Run

```bash
pip install -r requirements.txt
python run.py
```

Verify version: `curl http://localhost:5000/api/v1/version`
