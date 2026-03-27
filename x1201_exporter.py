#!/usr/bin/env python3
"""
Prometheus exporter for Suptronics X1201 / X1202 UPS HAT.

Reads battery data from the MAX17040 fuel gauge (I2C, address 0x36) and
power/charging status from GPIO pins. Designed for Raspberry Pi with the
Suptronics X120x series UPS HATs, but should work with any board using
a MAX17040/MAX17041 fuel gauge on I2C bus 1.
"""

import argparse
import os
import struct
import sys
import time

try:
    import smbus2
except ImportError:
    print("ERROR: smbus2 not installed. Run: apt install python3-smbus2", file=sys.stderr)
    sys.exit(1)

try:
    from prometheus_client import start_http_server
    from prometheus_client.core import GaugeMetricFamily, REGISTRY
    from prometheus_client.registry import Collector
except ImportError:
    print("ERROR: prometheus-client not installed. Run: apt install python3-prometheus-client", file=sys.stderr)
    sys.exit(1)

try:
    import gpiod
except ImportError:
    gpiod = None
    print("WARNING: gpiod not installed. GPIO metrics (AC power, charging) disabled.", file=sys.stderr)

# MAX17040 registers
REG_VCELL = 0x02
REG_SOC = 0x04
REG_MODE = 0x06
REG_VERSION = 0x08
REG_CONFIG = 0x0C


def read_word_swapped(bus, addr, reg):
    """Read a 16-bit register and byte-swap (MAX17040 is big-endian)."""
    raw = bus.read_word_data(addr, reg)
    return struct.unpack("<H", struct.pack(">H", raw))[0]


class X1201Collector(Collector):
    """Custom Prometheus collector for X1201 UPS HAT.

    collect() is called on each Prometheus scrape — no background thread needed.
    """

    def __init__(self, bus_num, i2c_addr, gpio_chip, gpio_ac, gpio_charging):
        self.bus_num = bus_num
        self.i2c_addr = i2c_addr
        self.gpio_chip = gpio_chip
        self.gpio_ac = gpio_ac
        self.gpio_charging = gpio_charging

    def collect(self):
        start = time.monotonic()
        scrape_ok = 1

        try:
            bus = smbus2.SMBus(self.bus_num)

            # Voltage: 12-bit ADC, 1.25mV per unit, upper 12 bits
            vcell_raw = read_word_swapped(bus, self.i2c_addr, REG_VCELL)
            voltage = vcell_raw * 1.25 / 1000 / 16

            # State of charge: integer part in high byte, fraction in low byte
            soc_raw = read_word_swapped(bus, self.i2c_addr, REG_SOC)
            soc_percent = soc_raw / 256.0

            # Version
            version = read_word_swapped(bus, self.i2c_addr, REG_VERSION)

            # Config register
            config = read_word_swapped(bus, self.i2c_addr, REG_CONFIG)
            rcomp = (config >> 8) & 0xFF
            sleep_bit = (config >> 7) & 1
            alert_bit = (config >> 5) & 1
            athd = config & 0x1F
            alert_threshold = 32 - athd

            bus.close()

            g = GaugeMetricFamily("x1201_battery_voltage_volts",
                                  "Battery cell voltage", value=voltage)
            yield g

            g = GaugeMetricFamily("x1201_battery_soc_percent",
                                  "Battery state of charge (0-100)", value=soc_percent)
            yield g

            g = GaugeMetricFamily("x1201_battery_soc_raw",
                                  "Raw SOC register value (higher precision)", value=soc_raw)
            yield g

            g = GaugeMetricFamily("x1201_fuel_gauge_rcomp",
                                  "RCOMP temperature compensation value", value=rcomp)
            yield g

            g = GaugeMetricFamily("x1201_fuel_gauge_sleep",
                                  "Fuel gauge sleep mode (1=sleeping)", value=sleep_bit)
            yield g

            g = GaugeMetricFamily("x1201_fuel_gauge_alert",
                                  "Low SOC alert triggered (1=active)", value=alert_bit)
            yield g

            g = GaugeMetricFamily("x1201_fuel_gauge_alert_threshold_percent",
                                  "SOC percentage that triggers low battery alert", value=alert_threshold)
            yield g

            g = GaugeMetricFamily("x1201_fuel_gauge_version",
                                  "MAX17040 chip version register", value=version)
            yield g

        except Exception as e:
            print(f"I2C read error: {e}", file=sys.stderr)
            scrape_ok = 0

        # GPIO readings
        if gpiod is not None:
            try:
                with gpiod.request_lines(
                    self.gpio_chip,
                    consumer="x1201-exporter",
                    config={
                        self.gpio_ac: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT),
                        self.gpio_charging: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT),
                    },
                ) as req:
                    vals = req.get_values([self.gpio_ac, self.gpio_charging])
                    ac_ok = 1 if vals[0] == gpiod.line.Value.ACTIVE else 0
                    # GPIO16: HIGH = charging disabled, LOW = charging enabled (inverted)
                    charging = 0 if vals[1] == gpiod.line.Value.ACTIVE else 1

                g = GaugeMetricFamily("x1201_ac_power_ok",
                                      "Mains power present (1=AC OK, 0=on battery)", value=ac_ok)
                yield g

                g = GaugeMetricFamily("x1201_charging_enabled",
                                      "Battery charging circuit enabled (1=enabled)", value=charging)
                yield g

            except Exception as e:
                print(f"GPIO read error: {e}", file=sys.stderr)

        duration = time.monotonic() - start

        g = GaugeMetricFamily("x1201_up",
                              "Whether the exporter can reach the UPS hardware (1=ok, 0=error)",
                              value=scrape_ok)
        yield g

        g = GaugeMetricFamily("x1201_collect_duration_seconds",
                              "Time taken to read all sensors", value=duration)
        yield g


def main():
    parser = argparse.ArgumentParser(description="Prometheus exporter for Suptronics X1201 UPS HAT")
    parser.add_argument("--port", type=int, default=int(os.environ.get("X1201_PORT", "9121")))
    parser.add_argument("--bus", type=int, default=int(os.environ.get("X1201_I2C_BUS", "1")))
    parser.add_argument("--address", type=lambda x: int(x, 0),
                        default=int(os.environ.get("X1201_I2C_ADDRESS", "0x36"), 0))
    parser.add_argument("--gpio-chip", default=os.environ.get("X1201_GPIO_CHIP", "/dev/gpiochip0"))
    parser.add_argument("--gpio-ac-power", type=int,
                        default=int(os.environ.get("X1201_GPIO_AC_POWER", "6")))
    parser.add_argument("--gpio-charging", type=int,
                        default=int(os.environ.get("X1201_GPIO_CHARGING", "16")))
    args = parser.parse_args()

    REGISTRY.register(X1201Collector(
        args.bus, args.address, args.gpio_chip, args.gpio_ac_power, args.gpio_charging,
    ))

    print(f"x1201-ups-exporter starting on :{args.port} (bus={args.bus}, addr=0x{args.address:02X})")
    start_http_server(args.port)
    print(f"Serving metrics at http://0.0.0.0:{args.port}/metrics")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
