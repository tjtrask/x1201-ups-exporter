# x1201-ups-exporter

Prometheus exporter for the [Suptronics X1201](https://suptronics.com/Raspberrypi/Power_mgmt/x1201-v1.1.html) / X1202 UPS HAT for Raspberry Pi.

Reads battery voltage, state of charge, and power status from the **MAX17040** fuel gauge over I2C, plus AC power and charging status from GPIO pins. Each Prometheus scrape reads the hardware directly — no background polling, no stale data, ~2ms per scrape.

A [Grafana dashboard](#grafana-dashboard) is included.

## Compatible Hardware

Built for the Suptronics X1201 V1.1, but should work with:

- **Suptronics X1202** — 4-cell variant, same fuel gauge
- **Geekworm X1201/X1202** — rebadged Suptronics
- Any board using a **MAX17040** or **MAX17041** fuel gauge on I2C

The GPIO pin assignments (AC power on GPIO6, charging on GPIO16) are X120x-specific. Other boards may use different pins — configure via `--gpio-ac-power` and `--gpio-charging`, or omit `python3-libgpiod` to skip GPIO metrics entirely.

## Quick Start

```bash
# Install dependencies (Debian/Raspbian)
sudo apt install python3-smbus2 python3-prometheus-client python3-libgpiod i2c-tools

# Enable I2C
sudo raspi-config nonint do_i2c 0

# Verify the MAX17040 is detected (should show 0x36)
i2cdetect -y 1

# Run the exporter
python3 x1201_exporter.py
# Metrics at http://localhost:9121/metrics
```

## Installation

```bash
git clone https://github.com/deaddawg/x1201-ups-exporter.git
cd x1201-ups-exporter
sudo cp x1201_exporter.py /usr/local/bin/
sudo chmod +x /usr/local/bin/x1201_exporter.py
sudo cp contrib/x1201-exporter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now x1201-exporter
```

### Docker

```bash
docker build -t x1201-ups-exporter .
docker run -d --name x1201-exporter \
  --device /dev/i2c-1 --device /dev/gpiochip0 \
  -p 9121:9121 \
  x1201-ups-exporter
```

I2C and GPIO access require device passthrough (`--device`) or `--privileged`.

## Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `x1201_battery_voltage_volts` | gauge | Battery cell voltage (typically 3.0–4.2V) |
| `x1201_battery_soc_percent` | gauge | Battery state of charge (0–100) |
| `x1201_battery_soc_raw` | gauge | Raw SOC register value (higher precision) |
| `x1201_ac_power_ok` | gauge | Mains power present (1=AC OK, 0=on battery) |
| `x1201_charging_enabled` | gauge | Charging circuit enabled (1=enabled, 0=disabled) |
| `x1201_fuel_gauge_rcomp` | gauge | RCOMP temperature compensation value |
| `x1201_fuel_gauge_sleep` | gauge | Fuel gauge sleep mode (1=sleeping) |
| `x1201_fuel_gauge_alert` | gauge | Low SOC alert triggered (1=active) |
| `x1201_fuel_gauge_alert_threshold_percent` | gauge | SOC percentage that triggers alert |
| `x1201_fuel_gauge_version` | gauge | MAX17040 chip version register |
| `x1201_up` | gauge | Whether the exporter can reach the UPS hardware (1=ok) |
| `x1201_collect_duration_seconds` | gauge | Time taken to read all sensors |

## Configuration

All options can be set via CLI flags or environment variables:

| Env Var | CLI Flag | Default | Description |
|---------|----------|---------|-------------|
| `X1201_PORT` | `--port` | 9121 | HTTP listen port |
| `X1201_I2C_BUS` | `--bus` | 1 | I2C bus number |
| `X1201_I2C_ADDRESS` | `--address` | 0x36 | MAX17040 I2C address |
| `X1201_GPIO_CHIP` | `--gpio-chip` | /dev/gpiochip0 | GPIO chip device |
| `X1201_GPIO_AC_POWER` | `--gpio-ac-power` | 6 | GPIO line for AC power detection |
| `X1201_GPIO_CHARGING` | `--gpio-charging` | 16 | GPIO line for charging status |

## Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: 'x1201'
    scrape_interval: 30s
    static_configs:
      - targets: ['your-rpi-hostname:9121']
```

## Grafana Dashboard

An example dashboard is included at [`grafana/x1201-ups-dashboard.json`](grafana/x1201-ups-dashboard.json). Import it via the Grafana UI (Dashboards > Import > Upload JSON) or provision it from a ConfigMap.

It includes:
- Status row: power source, battery SOC, voltage, charging state, exporter health, low battery alert
- History row: SOC and voltage time series, power source transitions

The dashboard uses a `DS_PROMETHEUS` datasource variable — Grafana will prompt you to select your Prometheus instance on import.

## How It Works

Uses the [`prometheus_client`](https://github.com/prometheus/client_python) library with a [custom collector](https://prometheus.github.io/client_python/collector/custom/). The `collect()` method is called on each Prometheus scrape — no background polling thread, no stale data.

The exporter runs as root because I2C (`/dev/i2c-1`) and GPIO (`/dev/gpiochip0`) require elevated access. On systems with appropriate udev rules granting group access (`i2c`, `gpio`), a non-root user may work.

If `python3-libgpiod` is not installed, the exporter runs without GPIO metrics — AC power and charging status are omitted, but all I2C metrics (voltage, SOC, fuel gauge registers) still work.

## License

MIT
