# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-27

### Added
- Initial release
- MAX17040 fuel gauge support over I2C (voltage, SOC, config registers)
- GPIO-based AC power detection and charging status
- Prometheus metrics endpoint via `prometheus_client` custom collector
- CLI args and environment variable configuration
- Graceful degradation when `gpiod` is not installed (GPIO metrics skipped)
- Systemd service file in `contrib/`
- Dockerfile for containerized deployment
