#!/usr/bin/env python3
"""
Prometheus exporter for Suptronics X1201 / X1202 UPS HAT.

Reads battery data from the MAX17040 fuel gauge (I2C, address 0x36) and
power/charging status from GPIO pins. Designed for Raspberry Pi with the
Suptronics X120x series UPS HATs, but should work with any board using
a MAX17040/MAX17041 fuel gauge on I2C bus 1.

Metrics exposed:
  - x1201_battery_voltage_volts      Battery cell voltage
  - x1201_battery_soc_percent        State of charge (0-100)
  - x1201_battery_soc_raw            Raw SOC register value (higher precision)
  - x1201_ac_power_ok                1 = mains power present, 0 = on battery
  - x1201_charging_enabled           1 = charging circuit enabled, 0 = disabled
  - x1201_config_rcomp               RCOMP temperature compensation value
  - x1201_config_sleep               1 = fuel gauge in sleep mode
  - x1201_config_alert               1 = low SOC alert triggered
  - x1201_config_alert_threshold_pct Alert threshold percentage
  - x1201_fuel_gauge_version         MAX17040 chip version
  - x1201_scrape_ok                  1 = last scrape succeeded, 0 = failed
  - x1201_scrape_duration_seconds    Time taken to read all sensors

Usage:
  python3 x1201_exporter.py [--port 9120] [--interval 30] [--bus 1] [--address 0x36]

Environment variables (override CLI args):
  X1201_PORT              HTTP listen port (default: 9120)
  X1201_INTERVAL          Scrape interval in seconds (default: 30)
  X1201_I2C_BUS           I2C bus number (default: 1)
  X1201_I2C_ADDRESS       Fuel gauge I2C address (default: 0x36)
  X1201_GPIO_CHIP         GPIO chip device (default: /dev/gpiochip0)
  X1201_GPIO_AC_POWER     GPIO line for AC power detection (default: 6)
  X1201_GPIO_CHARGING     GPIO line for charging status (default: 16)
"""

import argparse
import os
import struct
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import smbus2
except ImportError:
    print("ERROR: smbus2 not installed. Run: apt install python3-smbus2", file=sys.stderr)
    sys.exit(1)

try:
    import gpiod
except ImportError:
    gpiod = None
    print("WARNING: gpiod not installed. GPIO metrics disabled. Run: apt install python3-libgpiod", file=sys.stderr)

# MAX17040 registers
REG_VCELL = 0x02
REG_SOC = 0x04
REG_MODE = 0x06
REG_VERSION = 0x08
REG_CONFIG = 0x0C

_metrics_lock = threading.Lock()
_metrics_text = ""


def read_word_swapped(bus, addr, reg):
    """Read a 16-bit register and byte-swap (MAX17040 is big-endian)."""
    raw = bus.read_word_data(addr, reg)
    return struct.unpack("<H", struct.pack(">H", raw))[0]


def collect_metrics(bus_num, i2c_addr, gpio_chip, gpio_ac, gpio_charging):
    """Read all sensors and return Prometheus-formatted text."""
    start = time.monotonic()
    lines = []

    try:
        bus = smbus2.SMBus(bus_num)

        # Voltage: 12-bit ADC, 1.25mV per unit, upper 12 bits of 16-bit register
        vcell_raw = read_word_swapped(bus, i2c_addr, REG_VCELL)
        voltage = vcell_raw * 1.25 / 1000 / 16

        # State of charge: integer part in high byte, fraction in low byte
        soc_raw = read_word_swapped(bus, i2c_addr, REG_SOC)
        soc_percent = soc_raw / 256.0

        # Version
        version = read_word_swapped(bus, i2c_addr, REG_VERSION)

        # Config register
        config = read_word_swapped(bus, i2c_addr, REG_CONFIG)
        rcomp = (config >> 8) & 0xFF
        sleep_bit = (config >> 7) & 1
        alert_bit = (config >> 5) & 1
        athd = config & 0x1F
        alert_threshold = 32 - athd

        bus.close()

        lines.append(f"# HELP x1201_battery_voltage_volts Battery cell voltage.")
        lines.append(f"# TYPE x1201_battery_voltage_volts gauge")
        lines.append(f"x1201_battery_voltage_volts {voltage:.4f}")

        lines.append(f"# HELP x1201_battery_soc_percent State of charge (0-100).")
        lines.append(f"# TYPE x1201_battery_soc_percent gauge")
        lines.append(f"x1201_battery_soc_percent {soc_percent:.2f}")

        lines.append(f"# HELP x1201_battery_soc_raw Raw SOC register value for higher precision.")
        lines.append(f"# TYPE x1201_battery_soc_raw gauge")
        lines.append(f"x1201_battery_soc_raw {soc_raw}")

        lines.append(f"# HELP x1201_config_rcomp RCOMP temperature compensation value.")
        lines.append(f"# TYPE x1201_config_rcomp gauge")
        lines.append(f"x1201_config_rcomp {rcomp}")

        lines.append(f"# HELP x1201_config_sleep Fuel gauge sleep mode (1=sleeping).")
        lines.append(f"# TYPE x1201_config_sleep gauge")
        lines.append(f"x1201_config_sleep {sleep_bit}")

        lines.append(f"# HELP x1201_config_alert Low SOC alert triggered (1=active).")
        lines.append(f"# TYPE x1201_config_alert gauge")
        lines.append(f"x1201_config_alert {alert_bit}")

        lines.append(f"# HELP x1201_config_alert_threshold_pct SOC percentage that triggers alert.")
        lines.append(f"# TYPE x1201_config_alert_threshold_pct gauge")
        lines.append(f"x1201_config_alert_threshold_pct {alert_threshold}")

        lines.append(f"# HELP x1201_fuel_gauge_version MAX17040 chip version.")
        lines.append(f"# TYPE x1201_fuel_gauge_version gauge")
        lines.append(f"x1201_fuel_gauge_version {version}")

        scrape_ok = 1
    except Exception as e:
        print(f"I2C read error: {e}", file=sys.stderr)
        scrape_ok = 0

    # GPIO readings
    if gpiod is not None:
        try:
            with gpiod.request_lines(
                gpio_chip,
                consumer="x1201-exporter",
                config={
                    gpio_ac: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT),
                    gpio_charging: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT),
                },
            ) as req:
                vals = req.get_values([gpio_ac, gpio_charging])
                ac_ok = 1 if vals[0] == gpiod.line.Value.ACTIVE else 0
                # GPIO16 HIGH = charging disabled, LOW = charging enabled (inverted)
                charging = 0 if vals[1] == gpiod.line.Value.ACTIVE else 1

            lines.append(f"# HELP x1201_ac_power_ok Mains power present (1=AC OK, 0=on battery).")
            lines.append(f"# TYPE x1201_ac_power_ok gauge")
            lines.append(f"x1201_ac_power_ok {ac_ok}")

            lines.append(f"# HELP x1201_charging_enabled Battery charging circuit enabled (1=enabled).")
            lines.append(f"# TYPE x1201_charging_enabled gauge")
            lines.append(f"x1201_charging_enabled {charging}")
        except Exception as e:
            print(f"GPIO read error: {e}", file=sys.stderr)

    duration = time.monotonic() - start

    lines.append(f"# HELP x1201_scrape_ok Whether the last scrape succeeded (1=ok, 0=error).")
    lines.append(f"# TYPE x1201_scrape_ok gauge")
    lines.append(f"x1201_scrape_ok {scrape_ok}")

    lines.append(f"# HELP x1201_scrape_duration_seconds Time taken to read all sensors.")
    lines.append(f"# TYPE x1201_scrape_duration_seconds gauge")
    lines.append(f"x1201_scrape_duration_seconds {duration:.6f}")

    return "\n".join(lines) + "\n"


def scrape_loop(interval, bus_num, i2c_addr, gpio_chip, gpio_ac, gpio_charging):
    """Background thread that periodically reads sensors."""
    global _metrics_text
    while True:
        text = collect_metrics(bus_num, i2c_addr, gpio_chip, gpio_ac, gpio_charging)
        with _metrics_lock:
            _metrics_text = text
        time.sleep(interval)


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            with _metrics_lock:
                body = _metrics_text.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress per-request logging


def main():
    parser = argparse.ArgumentParser(description="Prometheus exporter for Suptronics X1201 UPS HAT")
    parser.add_argument("--port", type=int, default=int(os.environ.get("X1201_PORT", "9120")))
    parser.add_argument("--interval", type=int, default=int(os.environ.get("X1201_INTERVAL", "30")))
    parser.add_argument("--bus", type=int, default=int(os.environ.get("X1201_I2C_BUS", "1")))
    parser.add_argument("--address", type=lambda x: int(x, 0), default=int(os.environ.get("X1201_I2C_ADDRESS", "0x36"), 0))
    parser.add_argument("--gpio-chip", default=os.environ.get("X1201_GPIO_CHIP", "/dev/gpiochip0"))
    parser.add_argument("--gpio-ac-power", type=int, default=int(os.environ.get("X1201_GPIO_AC_POWER", "6")))
    parser.add_argument("--gpio-charging", type=int, default=int(os.environ.get("X1201_GPIO_CHARGING", "16")))
    args = parser.parse_args()

    print(f"x1201-ups-exporter starting on :{args.port} (interval={args.interval}s, bus={args.bus}, addr=0x{args.address:02X})")

    # Initial scrape before starting server
    global _metrics_text
    _metrics_text = collect_metrics(args.bus, args.address, args.gpio_chip, args.gpio_ac_power, args.gpio_charging)

    t = threading.Thread(
        target=scrape_loop,
        args=(args.interval, args.bus, args.address, args.gpio_chip, args.gpio_ac_power, args.gpio_charging),
        daemon=True,
    )
    t.start()

    server = HTTPServer(("", args.port), MetricsHandler)
    print(f"Serving metrics at http://0.0.0.0:{args.port}/metrics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
