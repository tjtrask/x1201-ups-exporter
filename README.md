# x1201-ups-exporter

Prometheus exporter for the [Suptronics X1201](https://suptronics.com/Raspberrypi/Power_mgmt/x1201-v1.1.html) / X1202 UPS HAT for Raspberry Pi.

Reads battery voltage, state of charge, and power status from the **MAX17040** fuel gauge over I2C, plus AC power and charging status from GPIO pins. Should work with any board using a MAX17040/MAX17041 fuel gauge on I2C — the X1201 is just the one it was built for.

## Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `x1201_battery_voltage_volts` | gauge | Battery cell voltage (typically 3.0–4.2V) |
| `x1201_battery_soc_percent` | gauge | State of charge (0–100%) |
| `x1201_battery_soc_raw` | gauge | Raw SOC register value (higher precision) |
| `x1201_ac_power_ok` | gauge | 1 = mains power present, 0 = on battery |
| `x1201_charging_enabled` | gauge | 1 = charging circuit enabled, 0 = disabled |
| `x1201_config_rcomp` | gauge | RCOMP temperature compensation value |
| `x1201_config_sleep` | gauge | 1 = fuel gauge in sleep mode |
| `x1201_config_alert` | gauge | 1 = low SOC alert triggered |
| `x1201_config_alert_threshold_pct` | gauge | SOC percentage that triggers alert |
| `x1201_fuel_gauge_version` | gauge | MAX17040 chip version register |
| `x1201_scrape_ok` | gauge | 1 = last scrape succeeded, 0 = failed |
| `x1201_scrape_duration_seconds` | gauge | Time taken to read all sensors |

## Requirements

- Python 3.9+
- `python3-smbus2` — I2C communication
- `python3-libgpiod` — GPIO reading (optional, GPIO metrics skipped if missing)
- I2C enabled on the Pi (`dtparam=i2c_arm=on` in `/boot/firmware/config.txt`)

On Debian/Raspbian:

```bash
sudo apt install python3-smbus2 python3-libgpiod i2c-tools
```

## Usage

```bash
python3 x1201_exporter.py [--port 9120] [--interval 30]
```

Metrics are served at `http://localhost:9120/metrics`. Health check at `/healthz`.

## Configuration

All options can be set via CLI args or environment variables:

| Env Var | CLI Flag | Default | Description |
|---------|----------|---------|-------------|
| `X1201_PORT` | `--port` | 9120 | HTTP listen port |
| `X1201_INTERVAL` | `--interval` | 30 | Scrape interval (seconds) |
| `X1201_I2C_BUS` | `--bus` | 1 | I2C bus number |
| `X1201_I2C_ADDRESS` | `--address` | 0x36 | MAX17040 I2C address |
| `X1201_GPIO_CHIP` | `--gpio-chip` | /dev/gpiochip0 | GPIO chip device |
| `X1201_GPIO_AC_POWER` | `--gpio-ac-power` | 6 | GPIO line for AC power detection |
| `X1201_GPIO_CHARGING` | `--gpio-charging` | 16 | GPIO line for charging status |

## Systemd Service

```ini
[Unit]
Description=Suptronics X1201 UPS Prometheus Exporter
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/x1201_exporter.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Note: runs as root because I2C and GPIO access require it. On systems with
appropriate udev rules or group permissions (`i2c`, `gpio`), a non-root user
may work.

## Compatible Hardware

Built for the Suptronics X1201 V1.1, but should work with:

- **Suptronics X1202** (4-cell variant, same fuel gauge)
- **Geekworm X1201/X1202** (rebadged Suptronics)
- Any Raspberry Pi HAT or SBC board using a **MAX17040** or **MAX17041** fuel gauge on I2C

The GPIO pin assignments (AC power on GPIO6, charging on GPIO16) are specific to the X120x series. Other boards may use different pins — configure via `--gpio-ac-power` and `--gpio-charging`.

## License

MIT
