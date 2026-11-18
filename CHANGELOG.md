# Changelog
## 2.1.5 - 2026-11-17

- Show @rstuke82 as the fork maintainer in Home Assistant.
- Credit original author Alone (@al-one) and upstream contributors in the README.
- Fix the Home Assistant logo and clarify where to submit issues and contributions.

## 2.1.4 - 2026-11-17

- Keep authentication tokens out of logs when the CatLink API returns gateway errors or malformed responses.
- Remove account phone numbers, raw device payloads, and signed parameters from integration logs.
- Restrict API service requests to the configured HTTPS server and make status notifications opt-in.
- Keep session tokens in memory and remove the legacy token cache on startup.

## 2.1.3 - 2026-11-16

- Redacted credentials and account details from CatLink logs.
- Handled missing litter weight and deodorant countdown values.
- Removed warnings for successful device log requests that return no entries.
- Updated documentation, issue reporting, and installation links to the rstuke82 CatLink fork.

## 2.1.2 - 2026-06-19

### Fixed
- Removed hardcoded entity_id to resolve domain mismatch warnings in Home Assistant 2027.5.0

## 2.1.1 - 2026-02-06

### Added
- Open-X/C08 device support (thanks to this nice repo: https://github.com/eulemitkeule/pycatlink)
- Limited Scooper Pro Ultra support
- Reset litter and reset deodorant buttons for litterbox
- Config flow coverage for discovery, reauthentication, and options
- Test suite additions and GitHub Actions workflow for tests

### Fixed
- Device detail parsing fallback when API payloads are incomplete
- Home Assistant 2026.2.0 compatibility issues

### Changed
- Device and entity organization with new helpers and logs mixin
